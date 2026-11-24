from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Generator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .memory import Proofs, combine_proofs
from .ollama import Reply
from .packs import PACKS, Card, ExtractedFact, get_pack, plans
from .runner import canonical
from .validation import array_value, object_value, string_list, text_value


class StateChanged(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class Episode:
    id: str
    pack: str
    subject: str
    session: str
    title: str
    text: str
    status: str
    extraction_status: str
    error: str
    created_at: str
    supersedes: str


@dataclass(frozen=True)
class Claim:
    id: str
    pack: str
    subject: str
    relation: str
    value: str
    kind: str
    origin: str
    confidence: float
    status: str
    proofs: Proofs
    premise_groups: tuple[tuple[str, ...], ...]
    citations: tuple[str, ...]
    quotes: dict[str, str]
    reason: str
    created_at: str

    def public(self) -> dict[str, object]:
        value = asdict(self)
        value["proofs"] = sorted(sorted(proof) for proof in self.proofs)
        return value


@dataclass(frozen=True)
class Snapshot:
    pack: str
    epoch: int
    episodes: tuple[Episode, ...]
    claims: tuple[Claim, ...]
    events: tuple[dict[str, object], ...]
    calls: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]

    def facts(self, subject: str) -> tuple[Claim, ...]:
        return tuple(
            claim
            for claim in self.claims
            if (
                normalized(claim.subject) == normalized(subject)
                and claim.kind == "fact"
                and claim.status == "live"
            )
        )

    def public(self) -> dict[str, object]:
        return {
            "pack": self.pack,
            "epoch": self.epoch,
            "episodes": [asdict(item) for item in self.episodes],
            "claims": [claim.public() for claim in self.claims],
            "events": self.events,
            "calls": self.calls,
            "warnings": self.warnings,
        }


def _episode(row: sqlite3.Row) -> Episode:
    return Episode(*(str(row[key]) for key in Episode.__dataclass_fields__))


def _claim(row: sqlite3.Row) -> Claim:
    proofs = frozenset(
        frozenset(string_list(item, "Stored proof"))
        for item in array_value(
            json.loads(row["proofs"]),
            "Stored proofs",
            256,
        )
    )
    groups = tuple(
        string_list(item, "Stored premises")
        for item in array_value(
            json.loads(row["premise_groups"]),
            "Stored premise groups",
        )
    )
    raw_quotes = object_value(json.loads(row["quotes"]), "Stored quotes")
    quotes = {key: text_value(value, "Stored quote", 4000) for key, value in raw_quotes.items()}
    return Claim(
        row["id"],
        row["pack"],
        row["subject"],
        row["relation"],
        row["value"],
        row["kind"],
        row["origin"],
        row["confidence"],
        row["status"],
        proofs,
        groups,
        string_list(json.loads(row["citations"]), "Stored citations"),
        quotes,
        row["reason"],
        row["created_at"],
    )


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError(f"Unsupported application database version: {version}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (
                    pack TEXT PRIMARY KEY, epoch INTEGER NOT NULL DEFAULT 0,
                    warnings TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY, pack TEXT NOT NULL REFERENCES meta(pack),
                    subject TEXT NOT NULL, session TEXT NOT NULL, title TEXT NOT NULL,
                    text TEXT NOT NULL, status TEXT NOT NULL, extraction_status TEXT NOT NULL,
                    error TEXT NOT NULL, created_at TEXT NOT NULL, supersedes TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY, pack TEXT NOT NULL REFERENCES meta(pack),
                    subject TEXT NOT NULL, relation TEXT NOT NULL, value TEXT NOT NULL,
                    kind TEXT NOT NULL, origin TEXT NOT NULL, confidence REAL NOT NULL,
                    status TEXT NOT NULL, proofs TEXT NOT NULL, premise_groups TEXT NOT NULL,
                    citations TEXT NOT NULL, quotes TEXT NOT NULL, reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, pack TEXT NOT NULL, epoch INTEGER NOT NULL,
                    kind TEXT NOT NULL, entity_id TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY, pack TEXT NOT NULL, task TEXT NOT NULL,
                    metrics TEXT NOT NULL, error TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS episodes_pack ON episodes(pack);
                CREATE INDEX IF NOT EXISTS claims_pack ON claims(pack);
                PRAGMA user_version=1;
            """)
            db.executemany(
                "INSERT OR IGNORE INTO meta(pack) VALUES (?)", ((pack.id,) for pack in PACKS)
            )

    @contextmanager
    def _connection(self, write: bool = False) -> Generator[sqlite3.Connection, None, None]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
        finally:
            db.close()

    @staticmethod
    def _epoch(db: sqlite3.Connection, pack: str) -> int:
        row = db.execute("SELECT epoch FROM meta WHERE pack=?", (pack,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown scenario pack: {pack}")
        return int(row["epoch"])

    def _check_epoch(self, db: sqlite3.Connection, pack: str, expected: int) -> None:
        if self._epoch(db, pack) != expected:
            raise StateChanged(
                "Evidence changed while the model was working. No stale result was saved; retry."
            )

    def _event(
        self, db: sqlite3.Connection, pack: str, kind: str, entity_id: str, detail: object
    ) -> None:
        db.execute("UPDATE meta SET epoch=epoch+1 WHERE pack=?", (pack,))
        db.execute(
            "INSERT INTO events(pack,epoch,kind,entity_id,detail,created_at) VALUES (?,?,?,?,?,?)",
            (pack, self._epoch(db, pack), kind, entity_id, canonical(detail), now()),
        )

    @staticmethod
    def _claims(db: sqlite3.Connection, pack: str) -> list[Claim]:
        return [
            _claim(row)
            for row in db.execute(
                "SELECT * FROM claims WHERE pack=? ORDER BY created_at,id", (pack,)
            )
        ]

    @staticmethod
    def _save(db: sqlite3.Connection, claim: Claim) -> None:
        db.execute(
            """
            INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET subject=excluded.subject,value=excluded.value,
                confidence=excluded.confidence,status=excluded.status,proofs=excluded.proofs,
                premise_groups=excluded.premise_groups,citations=excluded.citations,
                quotes=excluded.quotes,reason=excluded.reason
        """,
            (
                claim.id,
                claim.pack,
                claim.subject,
                claim.relation,
                claim.value,
                claim.kind,
                claim.origin,
                claim.confidence,
                claim.status,
                canonical(sorted(sorted(proof) for proof in claim.proofs)),
                canonical(claim.premise_groups),
                canonical(claim.citations),
                canonical(claim.quotes),
                claim.reason,
                claim.created_at,
            ),
        )

    @staticmethod
    def _id(pack: str, subject: str, relation: str, value: str, origin: str) -> str:
        return (
            "c_"
            + sha256(
                canonical(
                    [
                        pack,
                        normalized(subject),
                        relation,
                        normalized(value),
                        origin,
                    ]
                ).encode()
            ).hexdigest()[:24]
        )

    def snapshot(self, pack: str) -> Snapshot:
        get_pack(pack)
        with self._connection() as db:
            epoch = self._epoch(db, pack)
            episodes = tuple(
                _episode(row)
                for row in db.execute(
                    "SELECT * FROM episodes WHERE pack=? ORDER BY rowid",
                    (pack,),
                )
            )
            events = tuple(
                dict(row)
                for row in db.execute(
                    "SELECT * FROM events WHERE pack=? ORDER BY id DESC LIMIT 40",
                    (pack,),
                )
            )
            calls = tuple(
                dict(row)
                for row in db.execute(
                    "SELECT * FROM calls WHERE pack=? ORDER BY id DESC LIMIT 40",
                    (pack,),
                )
            )
            warnings = tuple(
                text_value(item, "Stored warning", 1000)
                for item in array_value(
                    json.loads(
                        db.execute(
                            "SELECT warnings FROM meta WHERE pack=?",
                            (pack,),
                        ).fetchone()["warnings"]
                    ),
                    "Stored warnings",
                )
            )
            return Snapshot(
                pack, epoch, episodes, tuple(self._claims(db, pack)), events, calls, warnings
            )

    def epoch(self, pack: str) -> int:
        with self._connection() as db:
            return self._epoch(db, pack)

    def episode(self, episode_id: str) -> Episode:
        with self._connection() as db:
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row is None:
                raise LookupError("Source episode does not exist.")
            return _episode(row)

    def add_episode(self, pack: str, subject: str, text: str, title: str, session: str) -> Episode:
        get_pack(pack)
        episode = Episode(
            "e_" + uuid4().hex,
            pack,
            text_value(subject, "Subject", 100),
            text_value(session, "Session", 100),
            text_value(title, "Title", 160),
            text_value(text, "Note"),
            "active",
            "pending",
            "",
            now(),
            "",
        )
        with self._connection(True) as db:
            db.execute(
                "INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(asdict(episode).values()),
            )
            self._event(db, pack, "wake-started", episode.id, {"status": "pending"})
        return episode

    def _refresh(self, db: sqlite3.Connection, pack: str) -> None:
        active = {
            str(row["id"])
            for row in db.execute(
                "SELECT id FROM episodes WHERE pack=? AND status='active'",
                (pack,),
            )
        }
        for claim in self._claims(db, pack):
            surviving = frozenset(proof for proof in claim.proofs if proof <= active)
            if claim.proofs and not surviving:
                self._save(
                    db,
                    replace(
                        claim,
                        subject="",
                        value="",
                        status="withdrawn",
                        proofs=frozenset(),
                        quotes={},
                        citations=(),
                        reason="Supporting source removed; content cleared.",
                    ),
                )
            elif claim.proofs:
                self._save(
                    db,
                    replace(
                        claim,
                        proofs=surviving,
                        quotes={key: value for key, value in claim.quotes.items() if key in active},
                    ),
                )
        facts_by_key: dict[tuple[str, str], list[Claim]] = defaultdict(list)
        for claim in self._claims(db, pack):
            if claim.kind == "fact" and claim.status in {"live", "conflict"} and claim.proofs:
                facts_by_key[(normalized(claim.subject), claim.relation)].append(claim)
        for group in facts_by_key.values():
            conflict = len({normalized(claim.value) for claim in group}) > 1
            for claim in group:
                self._save(
                    db,
                    replace(
                        claim,
                        status="conflict" if conflict else "live",
                        reason="Conflicting assertions; add an explicit correction."
                        if conflict
                        else "",
                    ),
                )
        claims = self._claims(db, pack)
        lookup = {claim.id: claim for claim in claims}
        for claim in claims:
            if (
                claim.kind == "fact"
                or not claim.value
                or claim.status in {"superseded", "rejected"}
            ):
                continue
            subject_facts = {
                item.id
                for item in claims
                if (
                    item.kind == "fact"
                    and item.status == "live"
                    and normalized(item.subject) == normalized(claim.subject)
                )
            }
            families: list[Proofs] = []
            for group in claim.premise_groups:
                if claim.origin == "qwen-sleep" and set(group) != subject_facts:
                    continue
                if group and all(key in lookup and lookup[key].status == "live" for key in group):
                    families.append(
                        combine_proofs((lookup[key].proofs for key in group), limit=256)
                    )
            proofs = frozenset(proof for family in families for proof in family)
            self._save(
                db,
                replace(
                    claim,
                    proofs=proofs or claim.proofs,
                    status="live" if proofs else "dirty",
                    reason=""
                    if proofs
                    else "A premise changed. Run Sleep / repair before using this memory.",
                ),
            )

    def _repair_rules(self, db: sqlite3.Connection, pack: str) -> list[str]:
        claims = self._claims(db, pack)
        by_subject: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            if claim.origin == "rule" and claim.status != "withdrawn":
                self._save(db, replace(claim, status="superseded", reason="Rule plan recomputed."))
            if claim.kind == "fact" and claim.status == "live":
                by_subject[normalized(claim.subject)].append(claim)
        warnings: list[str] = []
        for facts in by_subject.values():
            subject = facts[0].subject
            indexed = {fact.relation: (fact.value, fact.id) for fact in facts}
            candidates, messages = plans(pack, subject, indexed)
            warnings.extend(messages)
            lookup = {fact.id: fact for fact in facts}
            for candidate in candidates:
                self._save(
                    db,
                    Claim(
                        self._id(pack, subject, "next_action", candidate.text, "rule"),
                        pack,
                        subject,
                        "next_action",
                        candidate.text,
                        "plan",
                        "rule",
                        min(lookup[key].confidence for key in candidate.premises),
                        "live",
                        combine_proofs(
                            (lookup[key].proofs for key in candidate.premises), limit=256
                        ),
                        (candidate.premises,),
                        candidate.premises,
                        {},
                        "",
                        now(),
                    ),
                )
        db.execute("UPDATE meta SET warnings=? WHERE pack=?", (canonical(warnings), pack))
        return warnings

    def apply_extraction(
        self, episode_id: str, expected_epoch: int, facts: tuple[ExtractedFact, ...]
    ) -> None:
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row is None or row["status"] != "active":
                raise StateChanged("Source was removed while extraction was running.")
            episode = _episode(row)
            self._check_epoch(db, episode.pack, expected_epoch)
            for fact in facts:
                if fact.relation not in get_pack(episode.pack).fields or fact.operation not in {
                    "assert",
                    "correct",
                    "retract",
                }:
                    raise ValueError("Unsupported extracted relation or operation.")
                if not fact.quote or fact.quote not in episode.text:
                    raise ValueError("Extracted evidence quote is not verbatim source text.")
                if fact.operation != "retract" and (
                    not fact.value or fact.value.casefold() not in fact.quote.casefold()
                ):
                    raise ValueError("Extracted value is not present in its evidence quote.")
                current = self._claims(db, episode.pack)
                same_key = [
                    claim
                    for claim in current
                    if (
                        claim.kind == "fact"
                        and normalized(claim.subject) == normalized(episode.subject)
                        and claim.relation == fact.relation
                        and claim.status in {"live", "conflict"}
                    )
                ]
                claim_id = self._id(
                    episode.pack, episode.subject, fact.relation, fact.value, "qwen-wake"
                )
                if fact.operation in {"correct", "retract"}:
                    for previous in same_key:
                        if previous.id != claim_id or fact.operation == "retract":
                            self._save(
                                db,
                                replace(
                                    previous,
                                    status="superseded",
                                    reason="Explicit correction or retraction.",
                                ),
                            )
                if fact.operation == "retract":
                    continue
                previous = next((claim for claim in current if claim.id == claim_id), None)
                reusable = previous is not None and previous.status in {
                    "live",
                    "conflict",
                    "rejected",
                }
                proofs = (previous.proofs if reusable and previous is not None else frozenset()) | {
                    frozenset((episode.id,))
                }
                quotes = dict(previous.quotes) if reusable and previous is not None else {}
                quotes[episode.id] = fact.quote
                self._save(
                    db,
                    Claim(
                        claim_id,
                        episode.pack,
                        episode.subject,
                        fact.relation,
                        fact.value,
                        "fact",
                        "qwen-wake",
                        fact.confidence,
                        "rejected"
                        if previous is not None and previous.status == "rejected"
                        else "live",
                        proofs,
                        (),
                        (),
                        quotes,
                        "Rejected by user review."
                        if previous is not None and previous.status == "rejected"
                        else "",
                        previous.created_at if previous else now(),
                    ),
                )
            db.execute(
                "UPDATE episodes SET extraction_status='ready',error='' WHERE id=?", (episode.id,)
            )
            self._refresh(db, episode.pack)
            self._repair_rules(db, episode.pack)
            self._event(db, episode.pack, "wake-completed", episode.id, {"extracted": len(facts)})

    def extraction_failed(self, episode_id: str, message: str) -> None:
        with self._connection(True) as db:
            row = db.execute(
                "SELECT pack,status,extraction_status FROM episodes WHERE id=?", (episode_id,)
            ).fetchone()
            if (
                row is not None
                and row["status"] == "active"
                and row["extraction_status"] != "ready"
            ):
                db.execute(
                    "UPDATE episodes SET extraction_status='error',error=? WHERE id=?",
                    (message, episode_id),
                )
                self._event(db, row["pack"], "wake-failed", episode_id, {"status": "error"})

    def remove_episode(self, episode_id: str, replacement: str | None = None) -> Episode | None:
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row is None:
                raise LookupError("Source episode does not exist.")
            old = _episode(row)
            if old.status != "active":
                if replacement is not None:
                    raise StateChanged("Only an active source can be corrected.")
                return None
            db.execute(
                "UPDATE episodes SET subject='',session='',title='',text='',error='',status=?,extraction_status='removed' WHERE id=?",
                ("superseded" if replacement is not None else "deleted", episode_id),
            )
            new: Episode | None = None
            if replacement is not None:
                new = Episode(
                    "e_" + uuid4().hex,
                    old.pack,
                    old.subject,
                    old.session,
                    old.title,
                    text_value(replacement, "Replacement note"),
                    "active",
                    "pending",
                    "",
                    now(),
                    old.id,
                )
                db.execute(
                    "INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(asdict(new).values()),
                )
            self._refresh(db, old.pack)
            self._repair_rules(db, old.pack)
            self._event(
                db,
                old.pack,
                "source-corrected" if new else "source-deleted",
                old.id,
                {"replacement_id": new.id if new else "", "content_cleared": True},
            )
            return new

    def remove_session(self, pack: str, session: str) -> None:
        get_pack(pack)
        with self._connection(True) as db:
            rows = db.execute(
                "SELECT id FROM episodes WHERE pack=? AND session=? AND status='active'",
                (pack, session),
            ).fetchall()
            if not rows:
                raise LookupError("No active sources exist in that session.")
            db.execute(
                "UPDATE episodes SET subject='',session='',title='',text='',error='',status='deleted',"
                "extraction_status='removed' WHERE pack=? AND session=? AND status='active'",
                (pack, session),
            )
            self._refresh(db, pack)
            self._repair_rules(db, pack)
            self._event(
                db, pack, "session-deleted", "", {"count": len(rows), "content_cleared": True}
            )

    def apply_sleep(
        self, pack: str, subject: str, expected_epoch: int, cards: tuple[Card, ...]
    ) -> tuple[int, int]:
        with self._connection(True) as db:
            self._check_epoch(db, pack, expected_epoch)
            facts = tuple(
                claim
                for claim in self._claims(db, pack)
                if (
                    claim.kind == "fact"
                    and claim.status == "live"
                    and normalized(claim.subject) == normalized(subject)
                )
            )
            if not facts:
                raise ValueError("No current facts are available to consolidate.")
            lookup = {claim.id: claim for claim in facts}
            inputs = tuple(sorted(lookup))
            for previous in self._claims(db, pack):
                if (
                    previous.origin == "qwen-sleep"
                    and normalized(previous.subject) == normalized(subject)
                    and previous.value
                    and previous.status != "rejected"
                ):
                    self._save(
                        db,
                        replace(
                            previous,
                            status="superseded",
                            reason="Replaced by a newer consolidation.",
                        ),
                    )
            rejected = {claim.id for claim in self._claims(db, pack) if claim.status == "rejected"}
            saved = 0
            suppressed = 0
            for card in cards:
                if card.kind not in {"summary", "hypothesis", "procedure", "plan"}:
                    raise ValueError("Unsupported consolidated memory kind.")
                if not card.citations or any(key not in lookup for key in card.citations):
                    raise ValueError("Consolidation cited an unavailable premise.")
                claim_id = self._id(pack, subject, card.kind, card.text, "qwen-sleep")
                if claim_id in rejected:
                    suppressed += 1
                    continue
                self._save(
                    db,
                    Claim(
                        claim_id,
                        pack,
                        subject,
                        card.kind,
                        card.text,
                        card.kind,
                        "qwen-sleep",
                        card.confidence,
                        "live",
                        combine_proofs((claim.proofs for claim in facts), limit=256),
                        (inputs,),
                        card.citations,
                        {},
                        "",
                        now(),
                    ),
                )
                saved += 1
            self._event(
                db,
                pack,
                "sleep-completed",
                "",
                {"cards": saved, "review_suppressed": suppressed, "inputs": inputs},
            )
            return saved, suppressed

    def review_claim(self, claim_id: str, reject: bool) -> str:
        if not isinstance(reject, bool):
            raise ValueError("Review action must declare reject=true or false.")
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if row is None:
                raise LookupError("Memory claim does not exist.")
            claim = _claim(row)
            if claim.origin == "rule":
                raise ValueError(
                    "Rule plans are changed through their source premises, not model review."
                )
            if not claim.value or not claim.proofs:
                raise StateChanged(
                    "This claim no longer has available evidence; erased content cannot be restored."
                )
            if not reject and claim.status != "rejected":
                raise ValueError("Only a rejected claim can be restored for review.")
            self._save(
                db,
                replace(
                    claim,
                    status="rejected" if reject else "live",
                    reason="Rejected by user review." if reject else "",
                ),
            )
            self._refresh(db, claim.pack)
            self._repair_rules(db, claim.pack)
            self._event(
                db,
                claim.pack,
                "claim-rejected" if reject else "claim-restored",
                claim.id,
                {"source_preserved": True},
            )
            current = db.execute("SELECT status FROM claims WHERE id=?", (claim.id,)).fetchone()
            return str(current["status"])

    def log_call(self, pack: str, task: str, reply: Reply | None, error: str = "") -> None:
        with self._connection(True) as db:
            db.execute(
                "INSERT INTO calls(pack,task,metrics,error,created_at) VALUES (?,?,?,?,?)",
                (pack, task, canonical(reply.metrics()) if reply else "{}", error, now()),
            )
