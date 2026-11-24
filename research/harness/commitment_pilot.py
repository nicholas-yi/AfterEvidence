"""Necessary-memory task: the harness shared by every study (pilot, then Study 4 evaluation).

Session 1: a scripted customer agrees one exact exchange variant with the actor and defers
execution. Session 2: the customer asks to "go ahead with the exchange we agreed last time"
and never restates the target. Arms in session 2: N (no history), Hc (session-1 dialogue under
the exact v1 memory header), Hn (same dialogue under a neutral header), R (N plus the target
restated by the customer; feasibility control). Pilot v5 adds provider arms M (Mem0) and Ho
(Honcho): the frozen v4 session-1 dialogues are ingested into fresh scopes, retrieved once with
the customer's first session-2 message, and shown under the neutral header. Families are synthetic customers and delivered
orders added to an isolated copy of the pinned retail DB, using train-only products.

Reuses the v1 harness: `CopilotBackend` journals and request caps, the flat `WireCommand`
action contract, the v1 actor system prompt and `MEMORY_HEADER`, native tau2 tools and
`EnvironmentEvaluator` DB scoring, and a pilot ledger with an infrastructure-failure policy. Dry run by default; live calls need
`--approved-requests` equal to the active stage's approved cap. Design and logged choices: research/DESIGN.md.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from research import RESEARCH
from research.harness.freeze import changed_since, commit_of, source_hashes
from research.harness.tau_copilot import MEMORY_HEADER, WireCommand, receive

RUNS = RESEARCH / "runs" / "commitment"
ROOT = RUNS / "pilot"  # v1, killed; kept unchanged
NAMESPACE = "AE-COMMIT-DEV-20261114-v1"
ARMS = ("N", "Hc", "Hn", "R")
NEUTRAL_HEADER = "Previous-session transcript for this customer:\n"
PRODUCTS = ("5713490933", "7352963235", "6679515468", "2747247837")  # train-only templates
PILOT_REQUEST_CAP, SESSION_REQUESTS, SESSION_TOOLS = 240, 12, 12
CREDIT_STOP, CALL_MAX, HISTORY_MAX = 50.0, 1.0, 8000
SHUFFLE_SEED = 20261114
# Pilot v5: provider memory (M = Mem0, Ho = Honcho) under the neutral header, ingesting the
# frozen v4 session-1 dialogues into fresh scopes; one retrieval per session.
PROVIDER_ARMS = {"M": "mem0", "Ho": "honcho"}
# Retrieval arms: (provider, Honcho reasoning level or None for the server default). Hoh reuses
# the Honcho ingestion of Ho at the highest level the pinned server accepts (changed-mind design).
RETRIEVERS: dict[str, tuple[str, str | None]] = {
    "M": ("mem0", None),
    "Ho": ("honcho", None),
    "Hoh": ("honcho", "max"),
    # Dated evaluation: separate scopes from M and Ho.
    "Mi": ("mem0", None),
    "Hod": ("honcho", None),
    # Honcho features: message search; restating customer.
    "Hs": ("honcho", None),
    "Hodr": ("honcho", None),
    "Mir": ("mem0", None),
    # Stage 3: dream, app-written facts, facts direct.
    "Hdr": ("honcho", None),
    "Hw": ("honcho", None),
    "Fd": ("app", None),
    # Study 10: the application's facts written into Mem0.
    "Mw": ("mem0", None),
    # Studies 13-17: stale facts (alone, or before the transcripts), injected records, one Mem0
    # scope shared by every customer, Graphiti and Hindsight.
    "Fs": ("app", None),
    "Fsh": ("app", None),
    "Mz": ("mem0", None),
    "Hz": ("honcho", None),
    "Fz": ("app", None),
    "Ms": ("mem0", None),
    "Gr": ("graphiti", None),
    "Hi": ("hindsight", None),
}
# Session-2 arms whose customer names the agreed item (with its ID) only after the agent asks
# which item (Honcho features design); Nr has no memory.
# Ht has no memory block: it queries memory only through the mid-conversation tool.
RESTATING_ARMS, NO_MEMORY_ARMS = (
    frozenset({"Nr", "Hnr", "Hodr", "Mir"}),
    frozenset({"N", "R", "Nr", "Ht", "Tn", "Tp"}),
)
# Study 13: one fixed system sentence for Tp (after the policy and date, before any memory).
ARM_INSTRUCTIONS = {
    "Tp": "Before acting on a request that refers to an earlier conversation, call "
    "recall_customer_memory to check what was agreed."
}
MEMORY_TOOL = "recall_customer_memory"
MEMORY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": MEMORY_TOOL,
        "description": "Ask the customer-memory service a question about this customer's earlier "
        "conversations. Returns the service's answer.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
}
SHIM_CAPS, EPISODE_CAP = {"mem0": 14, "honcho": 50}, 96
# The gateway address can be overridden so two stages with separate gateways can run side by side.
HONCHO_WORKSPACE = "commitment-pilot-v5"
GATEWAY = os.environ.get("AFTEREVIDENCE_GATEWAY", "http://127.0.0.1:8900")
EVAL_STAGE, EVAL_TAG, EVAL_ARMS = "eval-v1", "commitment-eval-v1", ("N", "Hc", "Hn", "M", "Ho")
# Protocol amendment 1 (discovery-only fix after session 1): sources are frozen at this tag;
# seed and manifest still come from EVAL_TAG; session-1 artifacts must match the recorded hashes.
AMEND_TAG = "commitment-eval-v1-amend1"
AMEND_HASHES = RESEARCH / "locks" / "commitment-eval-v1-amend1-hashes.json"
# Fresh provider scopes per stage; the memory-study and pilot-v5 stores are never touched.
PROVIDER_STAGES: dict[str, dict[str, Any]] = {
    # Studies 13-18 (approved 2026-11-20). Dev checks: 4 families x
    # arms x 12 requests (plus live session 1 for lh and ac); shims from measured per-episode rates.
    "gx-dev-v1": {
        "prefix": "cmp-gx-d1-",
        "workspace": "gaps-dev-v1",
        "shim_caps": {"mem0": 40, "honcho": 100, "graphiti": 40, "hindsight": 45, "app": 10},
        "episode_cap": 672,
        "stop_on_ingest_error": False,
    },
    # gx-dev-v1 was stopped by host events (Docker engine down) during ingestion; fresh scopes.
    "gx-dev-v2": {
        "prefix": "cmp-gx-d2-",
        "workspace": "gaps-dev-v2",
        "shim_caps": {"mem0": 40, "honcho": 100, "graphiti": 40, "hindsight": 45, "app": 10},
        "episode_cap": 672,
        "stop_on_ingest_error": True,
    },
    # Studies 19-20 (approved 2026-11-21: second model gpt-6-luna; ceiling 3,075).
    "gm-dev-v1": {
        "prefix": "cmp-gm-d1-",
        "workspace": "second-model-gaps-dev-v1",
        "shim_caps": {"mem0": 24, "honcho": 100, "app": 10},
        "episode_cap": 528,
        "stop_on_ingest_error": True,
    },
    "lm-dev-v1": {
        "prefix": "cmp-lm-d1-",
        "workspace": "second-model-long-history-dev-v1",
        "shim_caps": {"mem0": 36, "honcho": 120, "app": 6},
        "episode_cap": 432,
        "stop_on_ingest_error": True,
    },
    "gm-eval-v1": {
        "prefix": "cmp-gm-e1-",
        "workspace": "second-model-gaps-eval-v1",
        "shim_caps": {"mem0": 192, "honcho": 480, "app": 96},
        "episode_cap": 3310,
        "stop_on_ingest_error": True,
    },
    "lm-eval-v1": {
        "prefix": "cmp-lm-e1-",
        "workspace": "second-model-long-history-eval-v1",
        "shim_caps": {"mem0": 240, "honcho": 528, "app": 48},
        "episode_cap": 2070,
        "stop_on_ingest_error": True,
    },
    "lh-dev-v1": {
        "prefix": "cmp-lh-d1-",
        "workspace": "long-history-dev-v1",
        "shim_caps": {"mem0": 36, "honcho": 120, "app": 6},
        "episode_cap": 432,
        "stop_on_ingest_error": False,
    },
    "ac-dev-v1": {
        "prefix": "cmp-ac-d1-",
        "workspace": "address-change-dev-v1",
        "shim_caps": {"mem0": 14, "honcho": 50, "app": 6},
        "episode_cap": 288,
        "stop_on_ingest_error": False,
    },
    # Sized from the dev checks (episodes x 1.25, shims x 1.5 per family x 32; see DESIGN).
    "gx-eval-v1": {
        "prefix": "cmp-gx-e1-",
        "workspace": "gaps-eval-v1",
        "shim_caps": {"mem0": 288, "honcho": 504, "graphiti": 480, "hindsight": 216, "app": 96},
        "episode_cap": 5240,
        "stop_on_ingest_error": False,
    },
    "lh-eval-v1": {
        "prefix": "cmp-lh-e1-",
        "workspace": "long-history-eval-v1",
        "shim_caps": {"mem0": 240, "honcho": 540, "app": 48},
        "episode_cap": 2130,
        "stop_on_ingest_error": False,
    },
    "ac-eval-v1": {
        "prefix": "cmp-ac-e1-",
        "workspace": "address-change-eval-v1",
        "shim_caps": {"mem0": 96, "honcho": 264, "app": 48},
        "episode_cap": 2070,
        "stop_on_ingest_error": False,
    },
    # Studies 10-12 evaluations, sized from the measured dev checks (episodes x 1.25, shims x 1.5).
    "wd-eval-v1": {
        "prefix": "cmp-wd-e1-",
        "workspace": "write-it-down-eval-v1",
        "shim_caps": {"mem0": 192, "app": 96},
        "episode_cap": 1976,
        "stop_on_ingest_error": False,
    },
    "m3-eval-v1": {
        "prefix": "cmp-m3-e1-",
        "workspace": "third-model-eval-v1",
        "shim_caps": {"mem0": 96, "honcho": 348, "app": 48},
        "episode_cap": 1290,
        "stop_on_ingest_error": False,
    },
    "pz-eval-v1": {
        "prefix": "cmp-pz-e1-",
        "workspace": "poisoned-memory-eval-v1",
        "shim_caps": {"mem0": 96, "honcho": 312, "app": 48},
        "episode_cap": 1610,
        "stop_on_ingest_error": False,
    },
    # Studies 10 and 11 (approved 2026-11-19): dev checks.
    "wd-dev-v1": {
        "prefix": "cmp-wd-d1-",
        "workspace": "write-it-down-dev-v1",
        "shim_caps": {"mem0": 24, "app": 10},
        "episode_cap": 240,
        "stop_on_ingest_error": False,
    },
    "pz-dev-v1": {
        "prefix": "cmp-pz-d1-",
        "workspace": "poisoned-memory-dev-v1",
        "shim_caps": {"mem0": 12, "honcho": 45, "app": 10},
        "episode_cap": 288,
        "stop_on_ingest_error": False,
    },
    "m3-dev-v2": {
        "prefix": "cmp-m3-d2-",
        "workspace": "third-model-dev-v2",
        "shim_caps": {"mem0": 12, "honcho": 45, "app": 10},
        "episode_cap": 192,
        "stop_on_ingest_error": False,
    },
    "m3-dev-v1": {
        "prefix": "cmp-m3-d1-",
        "workspace": "third-model-dev-v1",
        "shim_caps": {"mem0": 12, "honcho": 45, "app": 10},
        "episode_cap": 192,
        "stop_on_ingest_error": False,
    },
    # Honcho features (staged approval): dev check, then the evaluation (caps fixed at the tag).
    "hf-dev-v1": {
        "prefix": "cmp-hf-d1-",
        "workspace": "honcho-features-dev-v1",
        "shim_caps": {"mem0": 12, "honcho": 40},
        "episode_cap": 240,
        "stop_on_ingest_error": False,
    },
    "hf3-eval-v1": {
        "prefix": "cmp-h3d-",
        "workspace": "honcho-stage3-eval-v1",
        "shim_caps": {"honcho": 1272, "app": 96},
        "episode_cap": 2374,
        "stop_on_ingest_error": False,
    },
    "m2-eval-v1": {
        "prefix": "cmp-m2-e1-",
        "workspace": "second-model-eval-v1",
        "shim_caps": {"mem0": 96, "honcho": 240},
        "episode_cap": 1544,
        "stop_on_ingest_error": False,
    },
    "m2-dev-v1": {
        "prefix": "cmp-m2-d1-",
        "workspace": "second-model-dev-v1",
        "shim_caps": {"mem0": 12, "honcho": 45},
        "episode_cap": 192,
        "stop_on_ingest_error": False,
    },
    "hf3-dev-v1": {
        "prefix": "cmp-h3d-",
        "workspace": "honcho-stage3-dev-v1",
        "shim_caps": {"honcho": 180, "app": 10},
        "episode_cap": 210,
        "stop_on_ingest_error": False,
    },
    "hf-dev-v2": {
        "prefix": "cmp-hf-d1-",
        "workspace": "honcho-features-dev-v1",
        "shim_caps": {},
        "episode_cap": 192,
        "stop_on_ingest_error": False,
    },
    "hf-eval-v1": {
        "prefix": "cmp-hf-e1-",
        "workspace": "honcho-features-eval-v1",
        "shim_caps": {"mem0": 96, "honcho": 300},
        "episode_cap": 2600,
        "stop_on_ingest_error": False,
    },
    "pilot-v5": {
        "prefix": "cmp-p5-",
        "workspace": HONCHO_WORKSPACE,
        "shim_caps": SHIM_CAPS,
        "episode_cap": EPISODE_CAP,
        "stop_on_ingest_error": True,
    },
    "cm-dated-eval-v1": {
        "prefix": "cmp-cm-d2u-",
        "workspace": "changed-mind-dated-eval-v1-undated",
        "shim_caps": {"mem0": 192, "honcho": 528},
        "episode_cap": 2688,
        "stop_on_ingest_error": False,
    },
    "cm-dated-v1": {
        "prefix": "cmp-cm-t1-",
        "workspace": "changed-mind-dated-v1",
        "shim_caps": {"mem0": 12, "honcho": 45},
        "episode_cap": 144,
        "stop_on_ingest_error": True,
    },
    "cm-eval-v1": {
        "prefix": "cmp-cm-e1-",
        "workspace": "changed-mind-eval-v1",
        "shim_caps": {"mem0": 96, "honcho": 336},
        "episode_cap": 2688,
        "stop_on_ingest_error": False,
    },
    "cm-hoh-v1": {
        "prefix": "cmp-cm-p1-",
        "workspace": "changed-mind-pilot-v1",
        "shim_caps": {"honcho": 52},
        "episode_cap": 48,
        "stop_on_ingest_error": True,
    },
    "cm-pilot-v1": {
        "prefix": "cmp-cm-p1-",
        "workspace": "changed-mind-pilot-v1",
        "shim_caps": {"mem0": 12, "honcho": 40},
        "episode_cap": 188,
        "stop_on_ingest_error": True,
    },
    EVAL_STAGE: {
        "prefix": "cmp-eval-",
        "workspace": "commitment-eval-v1",
        "shim_caps": {"mem0": 112, "honcho": 400},
        "episode_cap": 2304,
        "stop_on_ingest_error": False,
    },
}
OPENING = "Hi! How can I help you today?"  # tau2's fixed first agent turn
WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}
CONFIRM = "Yes, please proceed with that exchange."
CONSENT = (
    CONFIRM  # target-blind and unconditional outside R (pilot v3: conditional consent read as no)
)
CONSENTS = (CONFIRM,)
DONE = re.compile(
    r"(?<!nothing )(?<!not )\b(?:has|have) been (?:submitted|processed|completed|placed|requested)"
    r"|\bi(?:'ve| have) (?:submitted|processed)|\bsuccessfully (?:submitted|processed|exchanged)"
    r"|\bstatus is now\b"
)
STOP = "###STOP###"
FIRST = ("Arlo", "Brielle", "Corin", "Delphine", "Ezra", "Fallon", "Gideon", "Hollis")
LAST = ("Ashdown", "Brennick", "Calloway", "Dunmore", "Elsworth", "Fairbank", "Granger", "Hartwell")
# The v1 actor instructions, verbatim (checked against tau_copilot's source by a test).
ACTOR_SYSTEM = (
    "You are a customer service agent. Follow the supplied current policy. "
    "Each turn return exactly one JSON action: "
    '{"kind":"message","value":"nonempty message for the customer","arguments_json":"{}"} OR '
    '{"kind":"tool","value":"one supplied tool name","arguments_json":"JSON-encoded argument object"}. '
    "The value field is required and nonempty for both action kinds. "
    "Do not combine a message and tool call. Use only supplied tools and documented arguments. "
    "Always verify current customer information; do not assume past customers' facts apply.\n"
    "POLICY:\n"
)


class FatalStop(RuntimeError):
    """Validity or isolation failure: the whole pilot stops."""


def _digits(index: int, field: str, count: int, namespace: str = NAMESPACE) -> str:
    value = int(hashlib.sha256(f"{namespace}:{index}:{field}".encode()).hexdigest(), 16)
    return str(value % 10**count).zfill(count)


def describe(options: dict[str, str]) -> str:
    return ", ".join(f"{key} {value}" for key, value in options.items())


def build_families(db: dict[str, Any]) -> list[dict[str, Any]]:
    """Four sealed dev families; target position among in-stock alternatives is 0, 1, 2, 3."""
    names = {(u["name"]["first_name"], u["name"]["last_name"]) for u in db["users"].values()}
    families = []
    for index, product_id in enumerate(PRODUCTS):
        product = db["products"][product_id]
        available = [v for v in product["variants"].values() if v["available"]]
        current, alternatives = available[0], available[1:]
        if len(alternatives) < 4:
            raise FatalStop(f"Product {product_id} lacks four in-stock alternatives.")
        target = alternatives[index]
        rejected = alternatives[(index + 1) % len(alternatives)]
        first, last = FIRST[2 * index], LAST[2 * index + 1]
        if (first, last) in names:
            raise FatalStop("Synthetic customer name collides with the pinned DB.")
        suffix = _digits(index, "user", 4)
        families.append(
            {
                "family": f"C{index + 1}",
                "product_id": product_id,
                "product": product["name"],
                "user_id": f"{first.lower()}_{last.lower()}_{suffix}",
                "first": first,
                "last": last,
                "email": f"{first.lower()}.{last.lower()}{suffix[:2]}@example.com",
                "zip": _digits(index, "zip", 5),
                "order_id": "#W" + _digits(index, "order", 7),
                "payment_id": "credit_card_" + _digits(index, "card", 7),
                "brand": "visa",
                "last_four": _digits(index, "last4", 4),
                "tracking": _digits(index, "track", 12),
                "current": {
                    "item_id": current["item_id"],
                    "options": current["options"],
                    "price": current["price"],
                },
                "alternatives": [
                    {"item_id": v["item_id"], "options": v["options"]} for v in alternatives
                ],
                "target_position": index,
                "target_id": target["item_id"],
                "rejected_id": rejected["item_id"],
            }
        )
    taken = set(db["users"]) | set(db["orders"])
    if any(f["user_id"] in taken or f["order_id"] in taken for f in families):
        raise FatalStop("Synthetic IDs collide with the pinned DB.")
    return families


def template_pool(
    db: dict[str, Any], tasks: dict[str, str], split: dict[str, list[str]]
) -> list[str]:
    """Train-only templates: >= 5 in-stock variants; some ID in a train task; no product ID,
    item ID, or product name in any test task (stricter than the pilot, which excludes Pet Bed)."""
    test = " ".join(tasks[i] for i in split["test"])
    train = " ".join(tasks[i] for i in split["train"])
    pool = []
    for pid, product in sorted(db["products"].items()):
        ids = [pid, *product["variants"]]
        if (
            sum(v["available"] for v in product["variants"].values()) >= 5
            and any(i in train for i in ids)
            and not any(i in test for i in ids)
            and product["name"].casefold() not in test.casefold()
        ):
            pool.append(pid)
    return pool


def eval_seed(tag_commit: str) -> int:
    return int(hashlib.sha256(tag_commit.encode()).hexdigest()[:8], 16)


def build_eval_families(
    db: dict[str, Any],
    seed: int,
    pool: list[str],
    count: int = 32,
    prefix: str = "E",
    width: int = 2,
    namespace: str | None = None,
    avoid: list[dict[str, Any]] | None = None,
    names: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Fresh sealed families: seeded products from the pool, target position 0-3 balanced,
    new names and IDs (new namespace), disjoint from the pinned DB, the dev families C1-C4,
    and any `avoid` families."""
    rng, namespace = random.Random(seed), namespace or f"AE-COMMIT-EVAL-v1-{seed}"
    positions = [i % 4 for i in range(count)]
    rng.shuffle(positions)
    products = [pool[i % len(pool)] for i in range(count)]
    rng.shuffle(products)
    dev = build_families(db) + list(avoid or [])
    taken_names = {(u["name"]["first_name"], u["name"]["last_name"]) for u in db["users"].values()}
    taken_names |= {(f["first"], f["last"]) for f in dev}
    names = [n for n in (names or [(a, b) for a in FIRST for b in LAST]) if n not in taken_names]
    rng.shuffle(names)
    families = []
    for index, (product_id, position) in enumerate(zip(products, positions, strict=True), 1):
        product = db["products"][product_id]
        available = [v for v in product["variants"].values() if v["available"]]
        current = available[rng.randrange(len(available))]
        alternatives = [v for v in available if v is not current]
        target, rejected = alternatives[position], alternatives[(position + 1) % len(alternatives)]
        first, last = names[index - 1]
        suffix = _digits(index, "user", 4, namespace)
        families.append(
            {
                "family": f"{prefix}{index:0{width}d}",
                "product_id": product_id,
                "product": product["name"],
                "user_id": f"{first.lower()}_{last.lower()}_{suffix}",
                "first": first,
                "last": last,
                "email": f"{first.lower()}.{last.lower()}{suffix[:2]}@example.com",
                "zip": _digits(index, "zip", 5, namespace),
                "order_id": "#W" + _digits(index, "order", 7, namespace),
                "payment_id": "credit_card_" + _digits(index, "card", 7, namespace),
                "brand": "visa",
                "last_four": _digits(index, "last4", 4, namespace),
                "tracking": _digits(index, "track", 12, namespace),
                "current": {
                    "item_id": current["item_id"],
                    "options": current["options"],
                    "price": current["price"],
                },
                "alternatives": [
                    {"item_id": v["item_id"], "options": v["options"]} for v in alternatives
                ],
                "target_position": position,
                "target_id": target["item_id"],
                "rejected_id": rejected["item_id"],
            }
        )
    taken = (
        set(db["users"])
        | set(db["orders"])
        | {x for f in dev for x in (f["user_id"], f["order_id"])}
    )
    keys = [
        x for f in families for x in (f["user_id"], f["order_id"], f["payment_id"], f["tracking"])
    ]
    if len(set(keys)) != len(keys) or any(k in taken for k in keys):
        raise FatalStop("Evaluation IDs collide with the pinned DB, dev families, or each other.")
    return families


def add_families(db: dict[str, Any], families: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a copy of the DB with each family's customer and one delivered order."""
    db = json.loads(json.dumps(db))
    for f in families:
        address = {
            "address1": f"{_digits(int(f['family'][1:]), 'street', 3)} Quarry Lane",
            "address2": "",
            "city": "Fairhaven",
            "country": "USA",
            "state": "OR",
            "zip": f["zip"],
        }
        db["users"][f["user_id"]] = {
            "user_id": f["user_id"],
            "name": {"first_name": f["first"], "last_name": f["last"]},
            "address": address,
            "email": f["email"],
            "payment_methods": {
                f["payment_id"]: {
                    "source": "credit_card",
                    "id": f["payment_id"],
                    "brand": f["brand"],
                    "last_four": f["last_four"],
                }
            },
            "orders": [f["order_id"]],
        }
        current = f["current"]
        db["orders"][f["order_id"]] = {
            "order_id": f["order_id"],
            "user_id": f["user_id"],
            "address": address,
            "items": [
                {
                    "name": f["product"],
                    "product_id": f["product_id"],
                    "item_id": current["item_id"],
                    "price": current["price"],
                    "options": current["options"],
                }
            ],
            "status": "delivered",
            "fulfillments": [{"tracking_id": [f["tracking"]], "item_ids": [current["item_id"]]}],
            "payment_history": [
                {
                    "transaction_type": "payment",
                    "amount": current["price"],
                    "payment_method_id": f["payment_id"],
                }
            ],
        }
    return db


def reference_action(family: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": f"{family['family']}_exchange",
        "requestor": "assistant",
        "name": "exchange_delivered_order_items",
        "arguments": {
            "order_id": family["order_id"],
            "item_ids": [family["current"]["item_id"]],
            "new_item_ids": [family["target_id"]],
            "payment_method_id": family["payment_id"],
        },
    }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold())


def identified(family: dict[str, Any], text: str) -> set[str]:
    """Alternatives a message names, by their unique 10-digit item IDs only. Option-value
    matching was removed: a message describing the current item and a new one produced false
    matches (pilot v1), and specificity rules collapsed plain option lists (v2 replay gate)."""
    return {v["item_id"] for v in family["alternatives"] if v["item_id"] in text}


def _option(family: dict[str, Any], item_id: str) -> str:
    variant = next(v for v in family["alternatives"] if v["item_id"] == item_id)
    return f"{describe(variant['options'])} {family['product']}"


RESTATEMENT = "It's the one I changed to last time: "


class ScriptedCustomer:
    """Finite-state customer. Session 2 never names the target unless the arm is R."""

    def __init__(self, family: dict[str, Any], session: int, arm: str = "N") -> None:
        self.family, self.session, self.arm = family, session, arm
        self.turns, self.agreed, self.confirmed, self.done, self.paid = (
            0,
            False,
            False,
            False,
            False,
        )

    def reply(self, agent_text: str) -> str:
        f, self.turns = self.family, self.turns + 1
        hello = f"Hi, I'm {f['first']} {f['last']} ({f['email']})."
        if self.turns == 1:
            if self.session == 1:
                return (
                    f"{hello} I'd like to exchange the {f['product']} from order "
                    f"{f['order_id']} for a different option. What else is in stock?"
                )
            restate = f" It's the {self._restated()}." if self.arm == "R" else ""
            return f"{hello} Please go ahead with the exchange we agreed last time for my order {f['order_id']}.{restate}"
        if self.turns > (6 if self.session == 1 else 8):
            return self._end("I'll come back another time.")
        named = identified(f, agent_text)
        target, others = f["target_id"] in named, named - {f["target_id"]}
        if self.session == 1:
            if self.turns == 2:
                return (
                    f"Thanks. I don't want the {_option(f, f['rejected_id'])}. I'd like the "
                    f"{_option(f, f['target_id'])} instead. Can you confirm that's the exact one?"
                )
            if target and not others:
                self.agreed = True
                return self._end(
                    f"Yes, that's the one: the {_option(f, f['target_id'])}. Let's agree on that, "
                    "but please don't make the exchange today; I'll confirm it next time."
                )
            if others and not target:
                return f"No, not that one. I want the {_option(f, f['target_id'])}."
            return (
                f"To be clear, I want the {_option(f, f['target_id'])}. What is its exact item ID?"
            )
        lowered = agent_text.casefold()
        asks_payment = any(w in lowered for w in ("payment", "card", "pay "))
        if self.confirmed:
            if self.completed(lowered):
                return self._end("Thanks, that's all.")
            if asks_payment and not self.paid:
                return self._pay()
            return CONFIRM  # repeated confirmation requests get the same explicit yes
        if self.arm != "R":
            # Target-blind consent: feedback must not let an agent find the target by elimination.
            if len(named) == 1:
                self.confirmed = True
                return CONSENT
        elif target and not others:
            self.confirmed = True
            return CONFIRM
        elif others and not target:
            return "No, that's not the one we agreed last time."
        if asks_payment and not named and not self.paid:
            return self._pay()
        if self.arm == "R":
            return f"It's the {self._restated()}."
        return (
            "We already agreed on it last time. Please go ahead with that one "
            "and tell me the exact item ID you will use."
        )

    def completed(self, lowered: str) -> bool:
        """The agent reported the change as done (Studies 4-18: the DONE pattern)."""
        return bool(DONE.search(lowered))

    def _pay(self) -> str:
        self.paid = True
        return f"Please use my {self.family['brand']} card ending {self.family['last_four']}."

    def _restated(self) -> str:
        f = self.family
        return f"{_option(f, f['target_id'])} (item ID {f['target_id']})"

    def _end(self, text: str) -> str:
        self.done = True
        return f"{text} {STOP}"


def dialogue(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Session-1 dialogue only: customer and agent text, no tool calls or payloads."""
    lines = []
    for m in messages:
        content = (m.get("content") or "").replace(STOP, "").strip()
        if m.get("role") in ("user", "assistant") and content and not m.get("tool_calls"):
            lines.append(("customer" if m["role"] == "user" else "agent", content))
    return lines


def transcript(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{'Customer' if s == 'customer' else 'Agent'}: {t}" for s, t in dialogue(messages)
    )


def session_system(
    policy: str, arm: str, history: str | None, history_max: int = HISTORY_MAX
) -> str:
    system = ACTOR_SYSTEM + policy
    if arm in ARM_INSTRUCTIONS:
        system += "\n\n" + ARM_INSTRUCTIONS[arm]
    if arm in NO_MEMORY_ARMS:
        return system
    if arm in RETRIEVERS:  # no block when retrieval failed or returned nothing (as v1)
        if history and len(history) > history_max:
            raise FatalStop(f"Provider memory exceeds {history_max:,} characters.")
        return system + "\n\n" + NEUTRAL_HEADER + history if history else system
    if not history or len(history) > history_max:
        raise FatalStop(f"Session-2 history is missing or exceeds {history_max:,} characters.")
    header = MEMORY_HEADER if arm == "Hc" else NEUTRAL_HEADER
    return system + "\n\n" + header + history


def _names_target(family: dict[str, Any], text: str) -> bool:
    """Conservative leakage test: the target's item ID or all of its option values."""
    target = next(v for v in family["alternatives"] if v["item_id"] == family["target_id"])
    lowered = _norm(text)
    return target["item_id"] in text or all(_norm(x) in lowered for x in target["options"].values())


def leaks(
    family: dict[str, Any], arm: str, system: str, history: str | None, user_texts: list[str]
) -> list[str]:
    """Target identification outside the allowed channel (R's own restatement; H history)."""
    problems = []
    prefix = system.replace(history, "") if history else system
    if _names_target(family, prefix):
        problems.append("target in system prompt outside history")
    allowed = user_texts
    if arm in RESTATING_ARMS:  # only the restatement, never the opening message
        allowed = user_texts[:1] + [t for t in user_texts[1:] if not t.startswith(RESTATEMENT)]
    if arm != "R" and any(_names_target(family, t) for t in allowed):
        problems.append("target in customer messages")
    stale = family.get("stale_id")  # changed-mind design: the superseded agreement X
    if stale:
        view = {**family, "target_id": stale}
        if _names_target(view, prefix):
            problems.append("stale item in system prompt outside history")
        if any(_names_target(view, t) for t in user_texts):
            problems.append("stale item in customer messages")
    return problems


def oracle(
    family: dict[str, Any], messages: list[dict[str, Any]], complete: bool, db_match: bool
) -> dict[str, Any]:
    """Success = completion, native DB match, agreed-variant arguments, confirmation first."""
    confirm_at = next(
        (
            i
            for i, m in enumerate(messages)
            if m.get("role") == "user" and m.get("content") in CONSENTS
        ),
        None,
    )
    mutations = [
        (i, c)
        for i, m in enumerate(messages)
        if m.get("role") == "assistant"
        for c in (m.get("tool_calls") or [])
        if c["name"] in WRITE_TOOLS
    ]
    exchanges = [c for _, c in mutations if c["name"] == "exchange_delivered_order_items"]
    expected = reference_action(family)["arguments"]
    agreed = bool(exchanges) and all(
        c["arguments"].get("new_item_ids") == expected["new_item_ids"]
        and c["arguments"].get("item_ids") == expected["item_ids"]
        for c in exchanges
    )
    wrong = sum(c["arguments"].get("new_item_ids") != expected["new_item_ids"] for c in exchanges)
    unauthorized = sum(
        confirm_at is None or i < confirm_at or c["name"] != expected_name() for i, c in mutations
    )
    confirmed_first = (
        bool(mutations) and confirm_at is not None and all(i > confirm_at for i, _ in mutations)
    )
    success = complete and db_match and agreed and confirmed_first and not unauthorized
    end = confirm_at if confirm_at is not None else len(messages)
    proposals = sum(
        m.get("role") == "assistant" and bool(identified(family, m.get("content") or ""))
        for m in messages[:end]
    )
    return {
        "success": success,
        "complete": complete,
        "db_match": db_match,
        "agreed_variant_args": agreed,
        "confirmation_first": confirmed_first,
        "wrong_variant_attempts": wrong,
        "unauthorized_attempts": unauthorized,
        "mutations": len(mutations),
        "proposals_before_consent": proposals,
    }


def expected_name() -> str:
    return "exchange_delivered_order_items"


def plan(
    note: str | None = None,
    stage: str = "pilot-v4",
    extra: dict[str, Any] | None = None,
    families: list[str] | None = None,
    seed: int = SHUFFLE_SEED,
) -> dict[str, Any]:
    families = families or [f"C{i + 1}" for i in range(len(PRODUCTS))]
    jobs = [{"session": 1, "family": f, "arm": "S1"} for f in families]
    arms = {"pilot-v5": tuple(PROVIDER_ARMS), EVAL_STAGE: EVAL_ARMS}.get(stage, ARMS)
    second = [{"session": 2, "family": f, "arm": a} for f in families for a in arms]
    random.Random(seed).shuffle(second)
    if stage == "pilot-v5":
        jobs = []  # session 1 is the frozen v4 histories
    sources = source_hashes(SOURCES)
    budget = BUDGETS[STAGE_BUDGET[stage]]
    return {
        "stage": stage,
        "namespace": NAMESPACE,
        "shuffle_seed": seed,
        "request_cap": budget["cap"],
        "credit_stop": budget["credit_stop"],
        "call_max": CALL_MAX,
        "session_requests": SESSION_REQUESTS,
        "session_tools": SESSION_TOOLS,
        "note": note,
        "sources": sources,
        **(extra or {}),
        "jobs": jobs + second,
    }


SOURCES = (
    "commitment_pilot.py",
    "tau_copilot.py",
    "staleness.py",
    "memory_gateway.py",
    "memory_retrievers.py",
    "provider_ingest.py",
    "copilot_shim.py",
    "commitment_analysis.py",
)


def stage_caps(stage: str, rates: dict[str, float]) -> dict[str, Any]:
    """A stage's request caps and the conservative credits if every cap were reached."""
    cfg, budget = PROVIDER_STAGES[stage], BUDGETS[STAGE_BUDGET[stage]]
    limits = {"episodes": cfg["episode_cap"], **cfg["shim_caps"]}
    return {
        "caps": limits,
        "hard_cap": budget["cap"],
        "credit_stop": budget["credit_stop"],
        "rates": rates,
        "conservative_at_caps": round(sum(limits[k] * rates[k] for k in limits), 1),
    }


def tag_state(tag: str = EVAL_TAG, freeze: str = AMEND_TAG) -> dict[str, Any] | None:
    """The protocol tag's commit and derived seed; the freeze tag (the amendment if it exists)
    and the frozen sources changed since it."""
    commit = commit_of(tag)
    if commit is None:
        return None
    frozen = commit_of(freeze)
    freeze_tag, freeze_commit = (freeze, frozen) if frozen else (tag, commit)
    return {
        "tag": tag,
        "commit": commit,
        "seed": eval_seed(commit),
        "freeze_tag": freeze_tag,
        "freeze_commit": freeze_commit,
        "changed": changed_since(freeze_commit, SOURCES),
    }


def session_one_artifacts(directory: Path) -> dict[str, str]:
    """SHA-256 of every recorded session-1 artifact plus the plan and manifest."""
    names = [p.name for p in directory.glob("*-s1-*") if p.is_file()] + [
        "plan.json",
        "manifest.json",
    ]
    return {
        n: hashlib.sha256((directory / n).read_bytes()).hexdigest()
        for n in sorted(names)
        if (directory / n).exists()
    }


def artifact_problems(directory: Path, recorded: dict[str, str]) -> list[str]:
    current = session_one_artifacts(directory)
    return [
        f"{n}: {'missing' if n not in current else 'hash differs'}"
        for n in sorted(recorded)
        if current.get(n) != recorded[n]
    ] + [f"{n}: unrecorded" for n in sorted(set(current) - set(recorded))]


def select_jobs(jobs: list[dict[str, Any]], phase: str, included: Any) -> list[dict[str, Any]]:
    """Evaluation phases: session 1 for every family; session 2 for included families, in plan order."""
    if phase == "session1":
        return [j for j in jobs if j["session"] == 1]
    return [j for j in jobs if j["session"] == 2 and j["family"] in included]


def job_id(job: dict[str, Any]) -> str:
    return f"{job['family']}-s{job['session']}-{job['arm']}"


STAGES = ("pilot", "pilot-v2", "pilot-v3", "pilot-v4", "pilot-v5", EVAL_STAGE)
ACTIVE_STAGE = EVAL_STAGE
# Each owner approval has its own ledger: v1-v3 shared 240 requests; v4 has a fresh 264.
BUDGETS = {
    "v1-v3": {"stages": ("pilot", "pilot-v2", "pilot-v3"), "cap": 240, "credit_stop": 50.0},
    "v4": {"stages": ("pilot-v4",), "cap": 264, "credit_stop": 40.0},
    # v5 counts episodes and both provider shims (journals under pilot-v5/shims/).
    "v5": {"stages": ("pilot-v5",), "cap": 160, "credit_stop": 25.0},
    # Evaluation: episodes <= 2,304, Mem0 shim <= 112, Honcho shim <= 400.
    "eval": {"stages": (EVAL_STAGE,), "cap": 2816, "credit_stop": 310.0},
    # Changed-mind pilot: episodes <= 188, Mem0 shim <= 12, Honcho shim <= 40.
    "cm-pilot": {"stages": ("cm-pilot-v1",), "cap": 240, "credit_stop": 30.0},
    # Hoh dev check: episodes <= 48 (4 sessions), Honcho shim <= 52; no ingestion.
    "cm-hoh": {"stages": ("cm-hoh-v1",), "cap": 100, "credit_stop": 12.0},
    # Changed-mind evaluation: episodes <= 2,688 (224 x 12), Mem0 shim <= 96, Honcho shim <= 336.
    "cm-eval": {"stages": ("cm-eval-v1",), "cap": 3120, "credit_stop": 360.0},
    # Dated dev check: episodes <= 144 (12 x 12), Mem0 shim <= 12, Honcho shim <= 45.
    "cm-dated": {"stages": ("cm-dated-v1",), "cap": 200, "credit_stop": 25.0},
    # Dated evaluation: episodes <= 2,688 (224 x 12), Mem0 shim <= 192, Honcho shim <= 528.
    "cm-dated-eval": {"stages": ("cm-dated-eval-v1",), "cap": 3408, "credit_stop": 400.0},
    # Honcho features dev check: everything <= 350 requests, 40 credits.
    "hf-dev": {"stages": ("hf-dev-v1",), "cap": 350, "credit_stop": 40.0},
    # Stage 1b (approved rerun): restating arms rerun, retrievals reused, no shims.
    "hf-dev2": {"stages": ("hf-dev-v2",), "cap": 200, "credit_stop": 25.0},
    # Honcho features evaluation: everything <= 3,000 requests, 400 credits.
    "hf-eval": {"stages": ("hf-eval-v1",), "cap": 3000, "credit_stop": 400.0},
    # Honcho Stage 3 dev check (approved 2026-11-17): everything <= 400 requests, 50 credits.
    "hf3-dev": {"stages": ("hf3-dev-v1",), "cap": 400, "credit_stop": 50.0},
    # Second-model (gpt-6-luna) dev check: episodes 192, Mem0 12, Honcho 45; <= 260 requests, 35 credits.
    "m2-dev": {"stages": ("m2-dev-v1",), "cap": 260, "credit_stop": 35.0},
    # Second-model evaluation, sized from the dev check: episodes 1,544, Mem0 96, Honcho 240.
    "m2-eval": {"stages": ("m2-eval-v1",), "cap": 1880, "credit_stop": 230.0},
    # Honcho Stage 3 evaluation, sized from its dev check: episodes 2,374, Honcho 1,272, app 96.
    "hf3-eval": {"stages": ("hf3-eval-v1",), "cap": 3742, "credit_stop": 450.0},
    # Study 10 dev check: episodes 240 (20 x 12), Mem0 24, app 10; <= 280 requests, 35 credits.
    "wd-dev": {"stages": ("wd-dev-v1",), "cap": 280, "credit_stop": 35.0},
    # Study 11 dev check (mai-code-2-flash): episodes 192, Mem0 12, Honcho 45, app 10.
    "m3-dev": {"stages": ("m3-dev-v1",), "cap": 260, "credit_stop": 35.0},
    # Study 11 dev check v2 (mai-code-1.1-flash, about 0.17 credits per request in the replay).
    "m3-dev2": {"stages": ("m3-dev-v2",), "cap": 260, "credit_stop": 50.0},
    # Study 12 dev check: live session 1 (8 x 12) and 16 sessions (16 x 12); Mem0 12, Honcho 45, app 10.
    "pz-dev": {"stages": ("pz-dev-v1",), "cap": 355, "credit_stop": 45.0},
    # Studies 10-12 evaluations (ceiling raised to 1,350): the credit stops bind and sum to
    # 840 of the 857.92 left after the dev checks; conservative at caps is higher (see DESIGN).
    "wd-eval": {"stages": ("wd-eval-v1",), "cap": 2264, "credit_stop": 255.0},
    "m3-eval": {"stages": ("m3-eval-v1",), "cap": 1782, "credit_stop": 360.0},
    "pz-eval": {"stages": ("pz-eval-v1",), "cap": 2066, "credit_stop": 225.0},
    # Studies 13-18 (ceiling 2,650): dev checks sum to <= 1,859 requests and 195 credits.
    "gx-dev": {"stages": ("gx-dev-v1",), "cap": 907, "credit_stop": 95.0},
    "gx-dev2": {"stages": ("gx-dev-v2",), "cap": 907, "credit_stop": 95.0},
    "lh-dev": {"stages": ("lh-dev-v1",), "cap": 594, "credit_stop": 60.0},
    "ac-dev": {"stages": ("ac-dev-v1",), "cap": 358, "credit_stop": 40.0},
    # Evaluations (ceiling raised to 2,875): conservative at caps 919.6 + 343.2 + 297.6 =
    # 1,560.4 of the 1,561.71 left after the dev checks; credit stops sum to 1,320.
    "gx-eval": {"stages": ("gx-eval-v1",), "cap": 6824, "credit_stop": 760.0},
    "lh-eval": {"stages": ("lh-eval-v1",), "cap": 2958, "credit_stop": 300.0},
    "ac-eval": {"stages": ("ac-eval-v1",), "cap": 2478, "credit_stop": 260.0},
    # Studies 19-20 (gpt-6-luna; ceiling raised to 3,075, then 3,175). Evaluation caps
    # from the dev checks; conservative at caps 487.0 + 334.7 = 821.7 of the 830.89 left.
    "gm-dev": {"stages": ("gm-dev-v1",), "cap": 662, "credit_stop": 55.0},
    "lm-dev": {"stages": ("lm-dev-v1",), "cap": 594, "credit_stop": 45.0},
    "gm-eval": {"stages": ("gm-eval-v1",), "cap": 4078, "credit_stop": 495.0},
    "lm-eval": {"stages": ("lm-eval-v1",), "cap": 2886, "credit_stop": 335.0},
}
STAGE_BUDGET = {stage: name for name, b in BUDGETS.items() for stage in b["stages"]}
PHASE1 = [
    {"session": 1, "family": "C1", "arm": "S1"},
    {"session": 1, "family": "C2", "arm": "S1"},
    {"session": 2, "family": "C1", "arm": "R"},
    {"session": 2, "family": "C2", "arm": "R"},
]
INFRA_RETRIES, ABORT_CHARGE = 1, 1.0
# Start-up retries (seconds) for Copilot transport errors; None marks the final attempt.
STARTUP_RETRY_SECONDS: tuple[float | None, ...] = (60.0, 120.0, 240.0, None)


def transport_error(failure: BaseException) -> bool:
    """An error raised by the Copilot SDK's transport (JSON-RPC, process or credential lookup),
    not by the task: a session that fails this way is an infrastructure failure."""
    return type(failure).__module__.split(".")[0] == "copilot"


# Seconds to wait for an in-flight provider call before an un-journaled mismatch stops a run.
SETTLE_SECONDS, SETTLE_POLL = 600.0, 5.0
# Dev (C1-C4) and evaluation (E01-E32) family IDs (the C-only pattern stopped eval-v1).
ATTEMPT = re.compile(r"^([ABCDEFGHJKLNPQRSTUVW]\d+-s\d+-\w+?)(?:-a(\d+))?\.json$")


def journal_rows(*directories: Path) -> list[dict[str, Any]]:
    rows = []
    for directory in directories:
        for path in sorted(directory.rglob("*.calls.jsonl")):
            rows.extend(
                {**json.loads(line), "_journal": str(path)}
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            )
    return rows


def pilot_ledger(
    rows: list[dict[str, Any]], cap: int = PILOT_REQUEST_CAP, credit_stop: float = CREDIT_STOP
) -> dict[str, Any]:
    """Spend across all pilot journals. A journaled abort is charged ABORT_CHARGE credits;
    a started request with neither billing nor an abort record is an un-journaled mismatch."""
    from research.harness.costing import summarize_micro

    reasons: list[str] = []
    started = completed = aborted = 0
    recorded = 0.0
    journals: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        journals.setdefault(row.get("_journal", ""), []).append(row)
    for name, items in journals.items():
        ids = {
            e: {r.get("call_id") for r in items if r.get("event") == f"copilot-request-{e}"}
            for e in ("started", "completed", "aborted")
        }
        started += len(ids["started"])
        completed += len(ids["completed"])
        aborted += len(ids["aborted"] - ids["completed"])
        missing = ids["started"] - ids["completed"] - ids["aborted"]
        if missing:
            reasons.append(
                f"un-journaled mismatch in {Path(name).name}: calls {sorted(missing, key=str)}"
            )
        for row in items:
            if row.get("event") != "copilot-request-completed":
                continue
            try:
                credits = float(str(summarize_micro([row])["ai_credits"]))
            except ValueError as error:
                reasons.append(f"missing billing in {Path(name).name}: {error}")
                continue
            recorded += credits
            if credits > CALL_MAX:
                reasons.append(f"call cost {credits:.3f} > {CALL_MAX} credit")
    charged = recorded + ABORT_CHARGE * aborted
    if started > cap:
        reasons.append(f"request cap exceeded: {started} > {cap}")
    if charged > credit_stop:
        reasons.append(f"charged credits {charged:.2f} > {credit_stop}")
    return {
        "started": started,
        "completed": completed,
        "aborted": aborted,
        "recorded_credits": round(recorded, 4),
        "charged_credits": round(charged, 4),
        "reasons": reasons,
    }


def start_refusals(
    directories: list[Path],
    cap: int = PILOT_REQUEST_CAP,
    credit_stop: float = CREDIT_STOP,
    episode_cap: int | None = None,
) -> list[str]:
    import time

    rows = journal_rows(*directories)
    ledger = pilot_ledger(rows, cap, credit_stop)
    # A provider's own background work (e.g. Honcho's threshold dreams) can have a shim call in
    # flight between sessions; wait for it to settle. A record that never arrives still stops the run.
    deadline = time.monotonic() + SETTLE_SECONDS
    while (
        any(r.startswith("un-journaled mismatch") for r in ledger["reasons"])
        and time.monotonic() < deadline
    ):
        time.sleep(SETTLE_POLL)
        rows = journal_rows(*directories)
        ledger = pilot_ledger(rows, cap, credit_stop)
    reasons = list(ledger["reasons"])
    if episode_cap is not None:
        episodes = pilot_ledger([r for r in rows if Path(r["_journal"]).parent.name != "shims"])
        if episodes["started"] + SESSION_REQUESTS > episode_cap:
            reasons.append(
                f"next session could exceed the episode cap: {episodes['started']} + {SESSION_REQUESTS}"
            )
    if ledger["started"] + SESSION_REQUESTS > cap:
        reasons.append(
            f"next session could exceed the cap: {ledger['started']} + {SESSION_REQUESTS}"
        )
    return reasons


def infra_failure(report: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """Mechanical: the session failed and its last model request produced no response
    (per-call timeout, SDK/transport/connection error, or an aborted request)."""
    if report.get("status") != "failed":
        return False
    started = [r.get("call_id") for r in rows if r.get("event") == "copilot-request-started"]
    if not started:
        return False
    answered = {"copilot-response-received", "copilot-request-completed"}
    return not any(r.get("call_id") == started[-1] and r.get("event") in answered for r in rows)


def final_reports(directory: Path) -> list[dict[str, Any]]:
    """The last attempt of each session (legacy un-suffixed files count as attempt 1)."""
    latest: dict[str, tuple[int, Path]] = {}
    for path in directory.glob("*-s*.json"):
        match = ATTEMPT.match(path.name)
        if match:
            attempt = int(match.group(2) or 1)
            if attempt >= latest.get(match.group(1), (0, path))[0]:
                latest[match.group(1)] = (attempt, path)
    return [
        json.loads(p.read_text(encoding="utf-8")) for _, p in (latest[k] for k in sorted(latest))
    ]


def _session_one_history(directory: Path, family: str) -> str:
    first = next(
        (
            r
            for r in final_reports(directory)
            if r.get("family") == family and r.get("session") == 1
        ),
        None,
    )
    if first is None or not first.get("commitment"):
        raise FatalStop(f"{family}: no explicit session-1 commitment.")
    return transcript(first["messages"])


def provider_scope(family: str, prefix: str = "cmp-p5-") -> str:
    return f"customer:{prefix}{family}"


def frozen_inputs(
    source: Path, prefix: str = "cmp-p5-", expected: list[str] | None = None, exclude: bool = False
) -> dict[str, dict[str, Any]]:
    """Session-1 dialogues (same text as the H arms), with hashes. Pilot: all must have a
    commitment. Evaluation (exclude=True): families without one are left out."""
    inputs = {}
    for report in final_reports(source):
        if report.get("session") == 1:
            if not report.get("commitment"):
                if exclude:
                    continue
                raise FatalStop(f"{report['family']}: frozen session 1 has no commitment.")
            text = transcript(report["messages"])
            inputs[report["family"]] = {
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "chars": len(text),
                "episode": {
                    "id": f"{prefix}{report['family']}-s1",
                    "lines": dialogue(report["messages"]),
                },
            }
    if not exclude and sorted(inputs) != (expected or [f"C{i + 1}" for i in range(len(PRODUCTS))]):
        raise FatalStop("Frozen session-1 inputs are incomplete.")
    return inputs


def first_message(family: dict[str, Any], arm: str) -> str:
    """The customer's first session-2 message: the retrieval query, identical for M and Ho."""
    return ScriptedCustomer(family, 2, arm).reply(OPENING)


def target_mentions(family: dict[str, Any], text: str) -> dict[str, bool]:
    target = next(v for v in family["alternatives"] if v["item_id"] == family["target_id"])
    lowered = _norm(text)
    return {
        "has_target_id": target["item_id"] in text,
        "has_target_options": all(_norm(x) in lowered for x in target["options"].values()),
    }


def retrieve_memories(
    setup: dict[str, Any],
    directory: Path,
    search: Any,
    prefix: str = "cmp-p5-",
    families: list[str] | None = None,
    arms: tuple[str, ...] = tuple(PROVIDER_ARMS),
    prefixes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """One retrieval per (family, retrieval arm), never repeated; an error means no memory."""
    from research.harness.memory_retrievers import pack

    (directory / "memory").mkdir(parents=True, exist_ok=True)
    records = []
    for name, family in sorted(setup["families"].items()):
        if families is not None and name not in families:
            continue
        for arm in arms:
            provider, level = RETRIEVERS[arm]
            path = directory / "memory" / f"{name}-{arm}.json"
            if not path.exists():
                query, record = first_message(family, arm), {}
                try:
                    scope = provider_scope(name, (prefixes or {}).get(arm, prefix))
                    results = list(
                        search(provider, scope, query, level)
                        if level
                        else search(provider, scope, query)
                    )
                    text, ids = pack(
                        [(f"{provider}-{n}", t) for n, t in enumerate(results, 1)], HISTORY_MAX
                    )
                    record = {"text": text, "ids": ids, "raw_count": len(results), "error": None}
                except Exception as error:  # recorded; the session runs without memory
                    record = {
                        "text": "",
                        "ids": [],
                        "raw_count": 0,
                        "error": f"{type(error).__name__}: {error}"[:300],
                    }
                record.update(
                    provider=provider,
                    reasoning_level=level,
                    query=query,
                    scope=provider_scope(name, (prefixes or {}).get(arm, prefix)),
                    chars=len(record["text"]),
                    **target_mentions(family, record["text"]),
                )
                path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def memory_meta(record: dict[str, Any]) -> dict[str, Any]:
    """Report fields without memory text."""
    return {
        k: record.get(k)
        for k in ("provider", "chars", "raw_count", "error", "has_target_id", "has_target_options")
    }


def _session_two_history(directory: Path, job: dict[str, Any]) -> tuple[str | None, dict | None]:
    if job["arm"] not in RETRIEVERS:
        return _session_one_history(directory, job["family"]), None
    path = directory / "memory" / f"{job['family']}-{job['arm']}.json"
    if not path.exists():
        raise FatalStop(f"{job_id(job)}: no retrieval record.")
    record = json.loads(path.read_text(encoding="utf-8"))
    return (None if record.get("error") else record["text"] or None), memory_meta(record)


async def run_jobs(
    setup: dict[str, Any],
    directory: Path,
    jobs: list[dict[str, Any]],
    make_backend: Any,
    ledger_dirs: list[Path],
    cap: int = PILOT_REQUEST_CAP,
    credit_stop: float = CREDIT_STOP,
    episode_cap: int | None = None,
    exclude_uncommitted: bool = False,
    history_fn: Any = None,
    infra_continue: bool = False,
) -> dict[str, Any]:
    """Serial sessions; one fresh re-attempt after an infrastructure failure, none otherwise.
    With infra_continue, a second infrastructure failure marks that session failed (infra) and
    the run continues (rule for the changed-mind design onward; eval v1 used a fatal stop)."""
    results: list[dict[str, Any]] = []
    infra: list[dict[str, Any]] = []
    try:
        for job in jobs:
            attempt = 0
            while True:
                attempt += 1
                output = directory / f"{job_id(job)}-a{attempt}.json"
                journal_path = output.with_suffix(".calls.jsonl")
                if output.exists():
                    report = json.loads(output.read_text(encoding="utf-8"))
                else:
                    if journal_path.exists():
                        raise FatalStop(f"{journal_path.name} exists without a report.")
                    history, memory = (
                        (history_fn or _session_two_history)(directory, job)
                        if job["session"] == 2
                        else (None, None)
                    )
                    refusals = start_refusals(ledger_dirs, cap, credit_stop, episode_cap)
                    if refusals:
                        return {"refused": refusals, "results": results, "infra_events": infra}
                    with journal_path.open("x", encoding="utf-8", newline="\n") as journal:
                        backend = make_backend(journal)
                        backend.write(
                            "commitment-session-started",
                            **job,
                            attempt=attempt,
                            manifest_sha256=setup["manifest_sha256"],
                        )
                        report = await run_session(backend, setup, job, history)
                        if memory is not None:
                            report["memory"] = memory
                        rows = [
                            json.loads(x)
                            for x in journal_path.read_text(encoding="utf-8").splitlines()
                            if x
                        ]
                        report["attempt"], report["infra_failure"] = (
                            attempt,
                            infra_failure(report, rows),
                        )
                        last = [
                            r.get("call_id")
                            for r in rows
                            if r.get("event") == "copilot-request-started"
                        ][-1:]
                        aborted = {
                            r.get("call_id")
                            for r in rows
                            if r.get("event") == "copilot-request-aborted"
                        }
                        if report["infra_failure"] and last and last[0] not in aborted:
                            backend.write(
                                "copilot-request-aborted",
                                call_id=last[0],
                                billing="no response; journaled by the pilot, cost unknown",
                            )
                    output.write_text(
                        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
                    )
                if not report.get("infra_failure"):
                    break
                infra.append(
                    {"session": job_id(job), "attempt": attempt, "error": report.get("error")}
                )
                if attempt > INFRA_RETRIES:
                    if infra_continue:
                        break
                    raise FatalStop(f"{job_id(job)}: second infrastructure failure.")
            results.append(
                {
                    k: report.get(k)
                    for k in (
                        "family",
                        "session",
                        "arm",
                        "status",
                        "success",
                        "commitment",
                        "attempt",
                    )
                }
            )
            if job["session"] == 1 and not report.get("commitment") and not exclude_uncommitted:
                raise FatalStop(f"{job['family']}: no explicit session-1 commitment.")
    except FatalStop as fatal:
        return {"refused": [f"FATAL: {fatal}"], "results": results, "infra_events": infra}
    return {"refused": [], "results": results, "infra_events": infra}


async def live_run(
    directory: Path,
    model: str,
    stage: str,
    jobs: list[dict[str, Any]],
    setup: dict[str, Any],
    **options: Any,
) -> dict[str, Any]:
    from research.harness.copilot_backend import (
        CopilotBackend,
        isolated_client,
        quota_problem,
        quota_snapshot,
    )

    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "manifest.json"
    if not manifest.exists():  # a recorded artifact; never rewritten
        manifest.write_text(setup["manifest"] + "\n", encoding="utf-8")
    client = isolated_client()
    try:
        await client.start()
        models = None
        for wait in STARTUP_RETRY_SECONDS:  # a slow credential lookup can fail the first requests
            try:
                models = await client.list_models()
                break
            except Exception as failure:
                if not transport_error(failure) or wait is None:
                    raise
                await asyncio.sleep(wait)
        selected = next((m for m in models or [] if m.id == model), None)
        if selected is None or (selected.policy is not None and selected.policy.state != "enabled"):
            raise ValueError("Model is not enabled for this Copilot account.")
        problem = quota_problem(await quota_snapshot(client))
        if problem:
            raise RuntimeError(problem)

        def make_backend(journal: Any) -> Any:
            return CopilotBackend(
                client, model, directory / "isolated-copilot", journal, SESSION_REQUESTS
            )

        budget = BUDGETS[STAGE_BUDGET[stage]]
        episode_cap = PROVIDER_STAGES.get(stage, {}).get("episode_cap")
        return await run_jobs(
            setup,
            directory,
            jobs,
            make_backend,
            [RUNS / s for s in budget["stages"]],
            budget["cap"],
            budget["credit_stop"],
            episode_cap,
            **{"exclude_uncommitted": stage == EVAL_STAGE, **options},
        )
    finally:
        await client.stop()


def _vendor_env() -> tuple[Any, Any]:
    from research.harness.tau_pilot import VENDOR, check_source

    check_source()
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
    from loguru import logger
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.environment import get_environment
    from tau2.domains.retail.utils import RETAIL_DB_PATH

    logger.remove()
    logger.add(lambda message: print(message, end="", flush=True), level="WARNING")
    return RetailDB, (get_environment, json.loads(Path(RETAIL_DB_PATH).read_text(encoding="utf-8")))


def prepare(
    seed: int | None = None, builder: Any = None, reference: Any = None, add: Any = None
) -> dict[str, Any]:
    """Zero-inference setup: families, isolated DB, validated references, tasks. With a seed,
    the 32 evaluation families replace the dev families; `builder(base, pool)` supplies others.
    `reference(family)` and `add(db, families)` replace the exchange task (Study 18)."""
    RetailDB, (get_environment, base) = _vendor_env()
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage
    from tau2.data_model.tasks import Task
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator

    families, pool = build_families(base), list(PRODUCTS)
    if seed is not None or builder is not None:
        from research.harness.tau_pilot import VENDOR

        data = VENDOR / "data" / "tau2" / "domains" / "retail"
        tasks = {
            t["id"]: json.dumps(t)
            for t in json.loads((data / "tasks.json").read_text(encoding="utf-8"))
        }
        pool = template_pool(
            base, tasks, json.loads((data / "split_tasks.json").read_text(encoding="utf-8"))
        )
        families = builder(base, pool) if builder else build_eval_families(base, seed or 0, pool)
    db = RetailDB.model_validate((add or add_families)(base, families))

    def constructor(solo_mode: bool = False, **_: Any) -> Any:
        return get_environment(db=db)

    tasks = {}
    for f in families:
        action = (reference or reference_action)(f)
        task = Task.model_validate(
            {
                "id": f"commitment-{f['family']}",
                "user_scenario": {"instructions": "scripted"},
                "evaluation_criteria": {"actions": [action], "reward_basis": ["DB"]},
            }
        )
        env = constructor()
        before = env.get_db_hash()
        result = env.make_tool_call(action["name"], requestor="assistant", **action["arguments"])
        if env.get_db_hash() == before:
            raise FatalStop(f"{f['family']}: reference exchange did not change the DB.")
        call = ToolCall(
            id="ref", name=action["name"], arguments=action["arguments"], requestor="assistant"
        )
        history = [
            AssistantMessage(role="assistant", tool_calls=[call]),
            ToolMessage(
                role="tool", id="ref", requestor="assistant", content=env.to_json_str(result)
            ),
        ]
        positive = EnvironmentEvaluator.calculate_reward(constructor, task, history)
        empty = EnvironmentEvaluator.calculate_reward(constructor, task, [])
        if not (positive.db_check and positive.db_check.db_match) or (
            empty.db_check and empty.db_check.db_match
        ):
            raise FatalStop(f"{f['family']}: reference controls failed.")
        tasks[f["family"]] = task
    manifest = json.dumps(families, sort_keys=True)
    return {
        "families": {f["family"]: f for f in families},
        "constructor": constructor,
        "tasks": tasks,
        "policy": constructor().get_policy(),
        "manifest": manifest,
        "pool": pool,
        "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
    }


def _session_policy(setup: dict[str, Any], job: dict[str, Any]) -> str:
    """The store policy; dated stages add one identical "Today is <T>." sentence in session 2."""
    dated = setup.get("today") and job["session"] == 2
    return setup["policy"] + (f"\n\n{setup['today']}" if dated else "")


def _session_tools(
    setup: dict[str, Any], job: dict[str, Any], tools: list[Any]
) -> tuple[list[Any], set[str], Any]:
    """The actor's tool schemas and names, plus the Stage 3 memory tool for listed session-2 arms."""
    schemas = [tool.openai_schema for tool in tools]
    names = {tool.name for tool in tools}
    listed = job["session"] == 2 and job["arm"] in setup.get("memory_tool_arms", ())
    recall = setup.get("memory_tool") if listed else None
    if recall:
        schemas, names = [*schemas, MEMORY_TOOL_SCHEMA], names | {MEMORY_TOOL}
    return schemas, names, recall


def _session_customer(
    setup: dict[str, Any], family: dict[str, Any], job: dict[str, Any], arm: str
) -> Any:
    custom = setup.get("customer")  # changed-mind design supplies its own customer
    if custom:
        return custom(family, job["session"], job["arm"])
    return ScriptedCustomer(family, job["session"], arm)


def _memory_answer(
    recall: Any, family: str, question: str, calls: list[dict[str, Any]], cap: int
) -> str:
    """Answer one memory-tool call (at most `cap` per session) and record it in `calls`."""
    if len(calls) >= cap:
        answer, error = "Memory tool call limit reached for this conversation.", "cap"
    else:
        try:
            answer, error = recall(family, question)[:HISTORY_MAX], None
        except FatalStop:
            raise
        except Exception as failure:  # recorded; the actor sees no memory
            answer, error = (
                "Memory service unavailable.",
                f"{type(failure).__name__}: {failure}"[:300],
            )
    calls.append({"question": question, "chars": len(answer), "error": error, "answer": answer})
    return answer


async def run_session(
    backend: Any, setup: dict[str, Any], job: dict[str, Any], history: str | None
) -> dict[str, Any]:
    """One orchestrated session with the scripted customer; returns a report (no retries)."""
    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import (
        AssistantMessage,
        ToolCall,
        ToolMessage,
        UserMessage,
    )
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator
    from tau2.orchestrator.orchestrator import Orchestrator
    from tau2.user.user_simulator import UserSimulator
    from tau2.user.user_simulator_base import UserState

    from research.harness.copilot_backend import PilotRequestLimit

    family = setup["families"][job["family"]]
    arm = "N" if job["session"] == 1 else job["arm"]
    system = session_system(
        _session_policy(setup, job), arm, history, setup.get("history_max", HISTORY_MAX)
    )
    env = setup["constructor"]()
    schemas, names, recall = _session_tools(setup, job, env.get_tools())
    memory_calls: list[dict[str, Any]] = []
    customer = _session_customer(setup, family, job, arm)
    counters = {"reasks": 0, "tools": 0}
    loop = asyncio.get_running_loop()

    def invoke(instructions: str, prompt: str) -> str:
        future = asyncio.run_coroutine_threadsafe(
            backend.complete(instructions, prompt, WireCommand), loop
        )
        try:
            return future.result(timeout=150)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("Copilot response exceeded 150 seconds.") from None

    class Agent(LLMAgent):
        def _generate_next_message(self, message, state: LLMAgentState) -> AssistantMessage:
            receive(state, message)
            texts = [m.content or "" for m in state.messages if getattr(m, "role", "") == "user"]
            if job["session"] == 2 and leaks(family, arm, system, history, texts):
                raise FatalStop("Target leakage in session-2 actor inputs.")
            prompt = json.dumps(
                {"tools": schemas, "messages": [m.model_dump(mode="json") for m in state.messages]},
                default=str,
            )
            text, note, attempt = invoke(system, prompt), "", 0
            while True:
                try:
                    value = WireCommand.model_validate_json(text).native(names)
                    if value["kind"] == "message":
                        return AssistantMessage(role="assistant", content=value["content"])
                    counters["tools"] += 1
                    if counters["tools"] > SESSION_TOOLS:
                        raise RuntimeError("Session tool cap reached.")
                    if recall and value["name"] == MEMORY_TOOL:
                        # Answered inside the agent turn: the service's reply is a tool result in
                        # the actor's context (memory channel); no environment call, no DB change.
                        question = str(value["arguments"].get("question") or "")
                        cap = setup.get("memory_tool_cap", 2)
                        answer = _memory_answer(recall, job["family"], question, memory_calls, cap)
                        call = ToolCall(
                            id=f"memory_{len(memory_calls)}",
                            name=MEMORY_TOOL,
                            arguments={"question": question},
                            requestor="assistant",
                        )
                        state.messages.extend(
                            [
                                AssistantMessage(role="assistant", content=None, tool_calls=[call]),
                                ToolMessage(
                                    id=call.id, role="tool", content=answer, requestor="assistant"
                                ),
                            ]
                        )
                        prompt = json.dumps(
                            {
                                "tools": schemas,
                                "messages": [m.model_dump(mode="json") for m in state.messages],
                            },
                            default=str,
                        )
                        text, attempt = invoke(system, prompt), 0
                        continue
                    tool = next(t for t in env.get_tools() if t.name == value["name"])
                    arguments = tool.params.model_validate(value["arguments"]).model_dump()
                    call = ToolCall(
                        id=f"call_{backend.calls}",
                        name=tool.name,
                        arguments=arguments,
                        requestor="assistant",
                    )
                    return AssistantMessage(role="assistant", content=None, tool_calls=[call])
                except ValueError as error:
                    if attempt or counters["reasks"]:
                        raise
                    counters["reasks"] += 1
                    attempt = 1
                    backend.write("actor-reask", error=str(error)[:500], rejected=text)
                    note = f"\n\nYour previous action was rejected: {str(error)[:300]} Return exactly one valid action."
                    text = invoke(system + note, prompt)

    class Customer(UserSimulator):
        def _generate_next_message(self, message, state: UserState) -> UserMessage:
            receive(state, message)
            return UserMessage(
                role="user", content=customer.reply(getattr(message, "content", None) or "")
            )

    agent = Agent(
        tools=env.get_tools(),
        domain_policy=setup["policy"],
        llm="copilot-json-adapter",
        llm_args={},
    )
    user = Customer(llm="scripted-customer", instructions="scripted", llm_args={})
    task = setup["tasks"][family["family"]]
    orchestrator = Orchestrator(
        "retail", agent, user, env, task, max_steps=80, max_errors=3, seed=42, timeout=900
    )
    status, error, messages, termination, simulation = "completed", None, [], None, None
    try:
        simulation = await asyncio.to_thread(orchestrator.run)
        messages = [m.model_dump(mode="json") for m in simulation.messages or []]
        termination = str(simulation.termination_reason)
    except FatalStop:
        raise
    except PilotRequestLimit as stop:
        status, error = "budget-capped", str(stop)
    except (ValueError, RuntimeError, TypeError, OSError, TimeoutError) as failure:
        status, error = "failed", f"{type(failure).__name__}: {failure}"[:500]
    except Exception as failure:  # Copilot SDK transport errors subclass Exception directly
        if not transport_error(failure):
            raise
        status, error = "failed", f"{type(failure).__name__}: {failure}"[:500]
    if not messages:
        messages = [m.model_dump(mode="json") for m in orchestrator.get_messages()]
    complete = status == "completed" and termination is not None and "STOP" in termination.upper()
    trajectory = list(simulation.messages or []) if simulation is not None else []
    user_texts = [m.get("content") or "" for m in messages if m.get("role") == "user"]
    leakage = leaks(family, arm, system, history, user_texts) if job["session"] == 2 else []
    if job["session"] == 1:
        unchanged_task = task.model_copy(
            update={
                "evaluation_criteria": task.evaluation_criteria.model_copy(update={"actions": []})
            }
        )
        check = EnvironmentEvaluator.calculate_reward(
            setup["constructor"], unchanged_task, trajectory
        )
        unchanged = bool(check.db_check and check.db_check.db_match)
        result = {
            "commitment": customer.agreed and unchanged and status == "completed",
            "customer_agreed": customer.agreed,
            "db_unchanged": unchanged,
        }
    else:
        check = EnvironmentEvaluator.calculate_reward(setup["constructor"], task, trajectory)
        result = (setup.get("oracle") or oracle)(
            family,
            messages,
            complete,
            bool(trajectory and check.db_check and check.db_check.db_match),
        )
    return {
        **job,
        "status": status,
        "error": error,
        "termination": termination,
        "requests_started": backend.calls,
        "reasks": counters["reasks"],
        "tools": counters["tools"],
        **({"memory_tool_calls": memory_calls} if recall else {}),
        "history_chars": len(history or ""),
        "leakage": leakage,
        "lookups": sum(
            c["name"].startswith(("get_", "find_", "list_"))
            for m in messages
            if m.get("role") == "assistant"
            for c in (m.get("tool_calls") or [])
        ),
        **result,
        "messages": messages,
    }


def gates(reports: list[dict[str, Any]]) -> dict[str, Any]:
    first = [r for r in reports if r["session"] == 1]
    by_arm = {a: [r for r in reports if r["session"] == 2 and r["arm"] == a] for a in ARMS}
    wins = {a: sum(bool(r.get("success")) for r in rs) for a, rs in by_arm.items()}
    checks = {
        "session1_agreement_4of4": sum(bool(r.get("commitment")) for r in first) == 4,
        "R_4of4": wins["R"] == 4 and len(by_arm["R"]) == 4,
        "Hn_at_least_3of4": wins["Hn"] >= 3,
        "N_at_most_1of4": len(by_arm["N"]) == 4 and wins["N"] <= 1,
        "zero_leakage": all(not r.get("leakage") for r in reports),
    }
    return {
        "successes": wins,
        "gates": checks,
        "verdict": "PASS" if all(checks.values()) else "KILL",
    }


def shim_problems(directory: Path, caps: dict[str, int] | None = None) -> list[str]:
    """Exactly the two provider shims, each started at its approved cap, and no cap reached."""
    caps = caps or SHIM_CAPS
    problems = []
    journals = {p.name: p for p in (directory / "shims").glob("*.calls.jsonl")}
    if set(journals) != {f"{label}.calls.jsonl" for label in caps}:
        problems.append(f"shim journals {sorted(journals)} are not exactly mem0 and honcho")
    for label, cap in caps.items():
        path = journals.get(f"{label}.calls.jsonl")
        rows = (
            [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
            if path
            else []
        )
        start = next((r for r in rows if r.get("event") == "shim-started"), {})
        if start.get("label") != label or start.get("request_limit") != cap:
            problems.append(f"{label} shim not started with label {label} and cap {cap}")
        if any(
            "PilotRequestLimit" in str(r.get("error", ""))
            for r in rows
            if r.get("event") == "shim-error"
        ):
            problems.append(f"{label} shim cap {cap} reached; stop and report")
    return problems


def provider_phase(
    setup: dict[str, Any],
    directory: Path,
    inputs: dict[str, Any],
    stage: str = "pilot-v5",
    arms: tuple[str, ...] = tuple(PROVIDER_ARMS),
) -> dict[str, Any]:
    """Ingest session-1 dialogues into fresh scopes, wait for Honcho, then retrieve once."""
    from research.harness import provider_ingest

    cfg = PROVIDER_STAGES[stage]
    budget = BUDGETS[STAGE_BUDGET[stage]]
    status = provider_ingest.post("/status", {"provider": "mem0"}, url=GATEWAY)
    problems = shim_problems(directory, cfg["shim_caps"])
    if Path(status["state"]) != (directory / "mem0").resolve():
        problems.append(f"gateway Mem0 state is not the fresh {stage} directory")
    if (
        status["honcho_workspace"] != cfg["workspace"]
        or status["honcho_reasoning_level"] is not None
    ):
        problems.append(f"gateway Honcho workspace or reasoning level is not the {stage} setting")
    problems += pilot_ledger(journal_rows(directory), budget["cap"], budget["credit_stop"])[
        "reasons"
    ]
    if problems:
        return {"refused": problems}
    ledger, errors = directory / "ingest.jsonl", []
    for provider in PROVIDER_ARMS.values():
        for name in sorted(inputs):
            rows = provider_ingest.ingest_provider(
                provider,
                provider_scope(name, cfg["prefix"]),
                inputs[name].get(f"episodes_{provider}")
                or inputs[name].get("episodes")
                or [inputs[name]["episode"]],  # in session order; per-provider when they differ
                ledger,
                GATEWAY,
            )
            failed = [f"ingestion failed: {provider} {name}" for r in rows if r["status"] != "ok"]
            caps = shim_problems(directory, cfg["shim_caps"])
            if caps or (failed and cfg["stop_on_ingest_error"]):
                return {"refused": [*failed, *caps]}
            errors += failed  # evaluation: recorded; that arm then retrieves whatever exists
    queue = provider_ingest.post("/status", {"provider": "honcho"}, url=GATEWAY)["queue"]
    (directory / "honcho-queue.json").write_text(json.dumps(queue) + "\n", encoding="utf-8")

    def search(provider: str, scope: str, query: str, level: str | None = None) -> list[str]:
        body = {"provider": provider, "scope": scope, "query": query}
        if level:
            body["reasoning_level"] = level
        return provider_ingest.post("/search", body, url=GATEWAY, timeout=900)["results"]

    records = retrieve_memories(setup, directory, search, cfg["prefix"], sorted(inputs), arms)
    return {
        "refused": shim_problems(directory, cfg["shim_caps"]),
        "ingestion_errors": errors,
        "honcho_queue": queue,
        "retrievals": [memory_meta(r) for r in records],
    }


def provider_gates(directory: Path, reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Integration gate only: ingestion, drained queue, retrieval, leakage."""
    from research.harness.provider_ingest import done

    ingested = done(directory / "ingest.jsonl")
    queue_path = directory / "honcho-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else None
    records = [
        json.loads(p.read_text(encoding="utf-8")) for p in (directory / "memory").glob("*.json")
    ]
    wins = {
        a: sum(bool(r.get("success")) for r in reports if r.get("arm") == a) for a in PROVIDER_ARMS
    }
    checks: dict[str, bool] = {}
    for provider in PROVIDER_ARMS.values():
        checks[f"{provider}_ingested_4of4"] = sum(p == provider for p, _, _ in ingested) == 4
        checks[f"{provider}_retrieved_3of4"] = (
            sum(r["provider"] == provider and not r["error"] for r in records) >= 3
        )
    checks["honcho_queue_drained"] = bool(queue) and not (queue["pending"] or queue["in_progress"])
    checks["sessions_8"] = len(reports) == 8
    checks["zero_leakage"] = all(not r.get("leakage") for r in reports)
    return {
        "successes": wins,
        "gates": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }


def smoke_passed(directory: Path) -> bool:
    """Phase 1 passes iff both C1 and C2 R sessions succeed under the oracle."""
    r = {
        x["family"]: x
        for x in final_reports(directory)
        if x.get("session") == 2 and x.get("arm") == "R"
    }
    return all(bool(r.get(f, {}).get("success")) for f in ("C1", "C2"))


def summarize(directory: Path) -> dict[str, Any]:
    reports = final_reports(directory)
    rows = [
        {
            k: r.get(k)
            for k in (
                "family",
                "session",
                "arm",
                "status",
                "success",
                "commitment",
                "attempt",
                "requests_started",
                "reasks",
                "tools",
                "lookups",
                "proposals_before_consent",
                "wrong_variant_attempts",
                "unauthorized_attempts",
                "db_match",
                "agreed_variant_args",
                "confirmation_first",
                "termination",
                "memory",
            )
        }
        for r in reports
    ]
    budget = BUDGETS[STAGE_BUDGET.get(directory.name, "v4")]
    rows_all = journal_rows(directory)
    ledger = pilot_ledger(rows_all, budget["cap"], budget["credit_stop"])
    groups = {
        label: [r for r in rows_all if Path(r["_journal"]).name == f"{label}.calls.jsonl"]
        for label in SHIM_CAPS
    }
    groups["episodes"] = [r for r in rows_all if Path(r["_journal"]).parent.name != "shims"]
    by_group = {
        k: {
            x: y
            for x, y in pilot_ledger(v, budget["cap"], budget["credit_stop"]).items()
            if x != "reasons"
        }
        for k, v in groups.items()
        if v
    }
    if directory.name == EVAL_STAGE:
        from research.analysis.commitment_analysis import analyse, rows_from_runs

        verdict = {"analysis": analyse(rows_from_runs(directory))}
    elif directory.name == "pilot-v5":
        verdict = provider_gates(directory, reports)
    else:
        verdict = gates(reports)
    attempts = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in directory.glob("*-s*-a*.json")
        if ATTEMPT.match(p.name)
    ]
    return {
        "sessions": len(rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "infra_failures": sum(bool(a.get("infra_failure")) for a in attempts),
        "ledger": {k: v for k, v in ledger.items() if k != "reasons"},
        "ledger_by_journal": by_group,
        "rows": rows,
        **verdict,
    }


def _plan_extra(
    stage: str, setup: dict[str, Any], tag: dict[str, Any] | None, cfg: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, list[str] | None, int, dict[str, Any]]:
    """What a provider pilot (v5) or the tagged evaluation records in its plan beyond the base:
    (extra fields, families, shuffle seed, frozen session-1 inputs)."""
    extra: dict[str, Any] | None = None
    families: list[str] | None = None
    seed = SHUFFLE_SEED
    inputs: dict[str, Any] = {}
    if stage == "pilot-v5":
        inputs = frozen_inputs(RUNS / "pilot-v4")
        extra = {
            "source_stage": "pilot-v4",
            "inputs": {k: {"sha256": v["sha256"], "chars": v["chars"]} for k, v in inputs.items()},
            "shim_caps": SHIM_CAPS,
            "episode_cap": EPISODE_CAP,
            "mem0": {
                "scope": "user_id cmp-p5-<family>, run_id per session",
                "search": "library default",
            },
            "honcho": {"workspace": HONCHO_WORKSPACE, "reasoning_level": "server default"},
            "query": "customer's first session-2 message",
            "header": NEUTRAL_HEADER,
            "memory_max_chars": HISTORY_MAX,
        }
    if tag and cfg:
        families, seed = sorted(setup["families"]), tag["seed"]
        extra = {
            "tag": tag["tag"],
            "tag_commit": tag["commit"],
            "seed": seed,
            "seed_rule": "int(first 8 hex of SHA-256(tag commit SHA))",
            "eval_namespace": f"AE-COMMIT-EVAL-v1-{seed}",
            "manifest_sha256": setup["manifest_sha256"],
            "template_pool": setup["pool"],
            "shim_caps": cfg["shim_caps"],
            "episode_cap": cfg["episode_cap"],
            "mem0": {
                "scope": "user_id cmp-eval-<family>, run_id per session",
                "search": "library default",
            },
            "honcho": {"workspace": cfg["workspace"], "reasoning_level": "server default"},
            "query": "customer's first session-2 message",
            "header": NEUTRAL_HEADER,
            "memory_max_chars": HISTORY_MAX,
            "exclusion": "no explicit session-1 commitment: excluded from every arm, reported, not replaced",
            "analysis": "research/commitment_analysis.py",
        }
    return extra, families, seed, inputs


def _same_plan(path: Path, public: dict[str, Any], amended: bool) -> bool:
    """Record the plan on first run; afterwards the stored plan must match it exactly."""
    if not path.exists():
        path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
        return True
    stored = json.loads(path.read_text(encoding="utf-8"))
    # Under the amendment, source hashes are checked against its tag, not the stored plan.
    drop = ("sources",) if amended else ()
    return {k: v for k, v in stored.items() if k not in drop} == {
        k: v for k, v in public.items() if k not in drop
    }


def _approval_problem(args: argparse.Namespace, cap: int) -> str | None:
    """Why a live run is not approved as invoked (None when it may run)."""
    if args.stage != ACTIVE_STAGE:
        return f"{args.stage} is closed; only {ACTIVE_STAGE} may run, under its own approval."
    if not args.note:
        return "--note is required: record the approval and the harness it runs."
    if args.approved_requests != cap:
        return f"--approved-requests must equal the stage cap {cap}."
    allowed = {
        "pilot-v5": ("providers", "sessions"),
        EVAL_STAGE: ("session1", "providers", "sessions"),
    }
    phases = allowed.get(args.stage, ("1", "2"))
    if args.phase not in phases:
        return f"--phase must be one of {phases} for {args.stage}."
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Necessary-memory pilots and evaluation; dry run by default."
    )
    parser.add_argument("--stage", choices=STAGES, default=ACTIVE_STAGE)
    parser.add_argument("--approved-requests", type=int)
    parser.add_argument("--note", help="Provenance note recorded in the plan (required to run).")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument(
        "--phase",
        choices=["1", "2", "providers", "sessions", "session1"],
        help="v4: 1, 2. v5: providers, sessions. eval-v1: session1, providers, sessions.",
    )
    args = parser.parse_args()
    directory = RUNS / args.stage
    if args.summarize:
        print(json.dumps(summarize(directory), indent=2))
        return 0
    evaluation = args.stage == EVAL_STAGE
    tag = tag_state() if evaluation else None
    if evaluation and tag is None:
        if args.approved_requests is None:
            print(
                f"Dry run: tag {EVAL_TAG} not found; evaluation families are generated only after it."
            )
            return 0
        parser.error(f"The evaluation needs the annotated protocol tag {EVAL_TAG}.")
    if tag and tag["changed"]:
        parser.error(
            f"Frozen sources differ from {tag['freeze_tag']}: {tag['changed']} (a deviation; not run)."
        )
    amended = bool(tag and tag["freeze_tag"] == AMEND_TAG)
    if amended:
        problems = artifact_problems(
            directory, json.loads(AMEND_HASHES.read_text(encoding="utf-8"))["artifacts"]
        )
        if problems:
            parser.error(f"Session-1 artifacts differ from the amendment record: {problems}")
    setup = prepare(tag["seed"] if tag else None)
    cfg = PROVIDER_STAGES.get(args.stage)
    extra, families, seed, inputs = _plan_extra(args.stage, setup, tag, cfg)
    public = plan(args.note, args.stage, extra, families, seed)
    if args.approved_requests is None:
        name = sorted(setup["families"])[0]
        print(
            json.dumps(
                {
                    **public,
                    "jobs": len(public["jobs"]),
                    "manifest_sha256": setup["manifest_sha256"],
                    "references_validated": len(setup["tasks"]),
                },
                indent=2,
            )
        )
        print(f"\n--- dry run, no model calls: session-2 N opening for {name} ---")
        print(ScriptedCustomer(setup["families"][name], 2, "N").reply(OPENING))
        return 0
    problem = _approval_problem(args, public["request_cap"])
    if problem:
        parser.error(problem)
    if args.phase == "2" and not smoke_passed(directory):
        parser.error("Phase 2 needs both phase-1 R sessions to succeed under the oracle.")
    if evaluation and cfg and args.phase in ("providers", "sessions"):
        done = {r["family"] for r in final_reports(directory) if r.get("session") == 1}
        if done != set(setup["families"]):
            parser.error(f"Session 1 is incomplete: {sorted(set(setup['families']) - done)}")
        inputs = frozen_inputs(directory, cfg["prefix"], exclude=True)
    jobs = PHASE1 if args.phase == "1" else public["jobs"]
    if evaluation:
        jobs = select_jobs(jobs, str(args.phase), inputs)
    caps = cfg["shim_caps"] if cfg else SHIM_CAPS
    if args.phase == "sessions":
        missing = [
            job_id(j)
            for j in jobs
            if j["arm"] in PROVIDER_ARMS
            and not (directory / "memory" / f"{j['family']}-{j['arm']}.json").exists()
        ]
        if missing or shim_problems(directory, caps):
            parser.error(
                f"Sessions need every retrieval and clean shims: {missing} {shim_problems(directory, caps)}"
            )
    if any(directory.glob("*.calls.jsonl")) and not (directory / "plan.json").exists():
        parser.error("Run directory has journals but no plan; use a fresh directory.")
    directory.mkdir(parents=True, exist_ok=True)
    if not _same_plan(directory / "plan.json", public, amended):
        parser.error("The plan or frozen sources changed since the run started.")
    if amended and not (directory / "amendment.json").exists():
        (directory / "amendment.json").write_text(
            json.dumps(
                {
                    "tag": AMEND_TAG,
                    "commit": (tag or {}).get("freeze_commit"),
                    "sources": public["sources"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if evaluation and args.phase == "providers":
        excluded = sorted(set(setup["families"]) - set(inputs))
        (directory / "exclusions.json").write_text(
            json.dumps({"included": sorted(inputs), "excluded": excluded}, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.phase == "providers":
        result = provider_phase(setup, directory, inputs, args.stage)
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    outcome = asyncio.run(live_run(directory, args.model, args.stage, jobs, setup))
    summary = summarize(directory)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "refused": outcome["refused"],
                "infra_events": outcome["infra_events"],
                **{k: v for k, v in summary.items() if k != "rows"},
            },
            indent=2,
        )
    )
    return 1 if outcome["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
