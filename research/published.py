"""Every published table, as data: the study registry and the numbers in research/RESULTS.md.

Each `Table` names a study's public CSV, the analysis that recomputes its table, and the published
values that analysis must reproduce. `research.benchmark` lists and verifies these tables, and
research/tests/test_published_tables.py fails if a published number stops matching its CSV.
`expected` is a subset of the analysis output: floats match to 4 decimals (credits per session to
0.0011, since Python 3.12's compensated sum() can move a value on a rounding boundary), `Approx`
sets another tolerance, and `Exactly` also requires the same keys. Standard library only.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research import RESEARCH
from research.analysis import (
    changed_mind_analysis,
    changed_mind_dated_analysis,
    commitment_analysis,
    followups_analysis,
    gaps_analysis,
    honcho_features_analysis,
    honcho_stage3_analysis,
    memory_analysis,
    second_model_analysis,
)

DATA = RESEARCH / "data"
CREDITS_DELTA = 0.0011


@dataclass(frozen=True)
class Approx:
    value: float
    delta: float


@dataclass(frozen=True)
class Exactly:
    """The output must have exactly these keys (and match each value)."""

    value: Mapping[str, Any]


@dataclass(frozen=True)
class Table:
    key: str
    study: str
    question: str
    csv: str
    command: str  # the analysis that prints this table (`python -m <command> --csv <csv>`)
    analyse: Callable[[Path], dict[str, Any]]
    fields: tuple[str, ...]
    rows: int
    expected: Mapping[str, Any]

    @property
    def path(self) -> Path:
        return DATA / self.csv


def read_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return tuple(reader.fieldnames or ()), list(reader)


def _plain(analyse: Callable[[list[dict[str, str]]], dict[str, Any]]) -> Callable[[Path], Any]:
    return lambda path: analyse(read_rows(path)[1])


def _study(analyse: Callable[[str, list[dict[str, str]]], Any], key: str) -> Callable[[Path], Any]:
    return lambda path: analyse(key, read_rows(path)[1])


def arms(keys: str, table: Mapping[str, tuple[Any, ...]]) -> dict[str, dict[str, Any]]:
    """Rows of values, one per arm, for the space-separated output keys."""
    return {arm: dict(zip(keys.split(), values, strict=True)) for arm, values in table.items()}


def discordant(table: Mapping[str, tuple[Any, ...]], p: str = "p_holm") -> dict[str, Any]:
    """Per test: (arm-only, reference-only discordant families[, p-value])."""
    return arms(f"arm_only reference_only {p}", {k: v for k, v in table.items() if len(v) == 3}) | {
        k: dict(zip(("arm_only", "reference_only"), v, strict=False))
        for k, v in table.items()
        if len(v) < 3
    }


def merge(base: dict[str, Any], extra: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {k: {**v, **extra.get(k, {})} for k, v in base.items()}


def mismatches(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Where `actual` differs from the published `expected` (empty when they agree)."""
    if isinstance(expected, Exactly):
        if not isinstance(actual, Mapping) or set(actual) != set(expected.value):
            return [f"{path}: keys {sorted(actual) if isinstance(actual, Mapping) else actual}"]
        expected = expected.value
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return [f"{path}: expected a mapping, got {actual!r}"]
        found = []
        for key, value in expected.items():
            where = f"{path}.{key}" if path else key
            found += (
                mismatches(value, actual[key], where) if key in actual else [f"{where}: missing"]
            )
        return found
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            return [f"{path}: {actual!r} != {list(expected)!r}"]
        return [
            m
            for i, (e, a) in enumerate(zip(expected, actual, strict=True))
            for m in mismatches(e, a, f"{path}[{i}]")
        ]
    if isinstance(expected, Approx):
        ok = isinstance(actual, (int, float)) and abs(actual - expected.value) <= expected.delta
    elif isinstance(expected, float):
        delta = CREDITS_DELTA if path.endswith("credits_per_session") else 0.00005
        ok = isinstance(actual, (int, float)) and abs(actual - expected) <= delta
    else:
        ok = actual == expected and type(actual) is type(expected)
    return [] if ok else [f"{path}: {actual!r} != {expected!r}"]


TABLES: tuple[Table, ...] = (
    Table(
        key="memory",
        study="1-2",
        question="Does memory of other customers, or of the same customer's earlier sessions, help?",
        csv="memory-study-v1-episodes.csv",
        command="research.analysis.memory_analysis",
        analyse=lambda path: memory_analysis.tables_from_csv(path),
        fields=memory_analysis.EPISODE_FIELDS,
        rows=572,
        expected={
            "study1": merge(
                {
                    "none": {
                        "episodes": 52,
                        "successes": 39,
                        "mean_episode_credits": Approx(2.02, 0.005),
                    }
                }
                | arms(
                    "episodes successes wins losses holm_p",
                    {
                        "raw": (52, 41, 6, 4, 1.0),
                        "consolidated": (52, 41, 7, 5, 1.0),
                        "sleep": (52, 42, 7, 4, 1.0),
                        "workflows": (52, 43, 8, 4, 1.0),
                        "mem0": (52, 43, 9, 5, 1.0),
                        "graphiti": (52, 42, 7, 4, 1.0),
                        "hindsight": (52, 38, 6, 7, 1.0),
                        "honcho": (52, 41, 7, 5, 1.0),
                    },
                ),
                {
                    "raw": {
                        "mean_episode_credits": Approx(2.25, 0.005),
                        "post_hoc": {"difference": 0.0385, "ci95": (-0.0577, 0.1346)},
                    },
                    "consolidated": {"mean_episode_credits": Approx(2.27, 0.005)},
                    "sleep": {"mean_episode_credits": Approx(2.11, 0.005)},
                    "workflows": {"mean_episode_credits": Approx(1.97, 0.005)},
                    "mem0": {"mean_episode_credits": Approx(2.05, 0.005)},
                    "graphiti": {"mean_episode_credits": Approx(2.17, 0.005)},
                    "hindsight": {
                        "mean_episode_credits": Approx(2.13, 0.005),
                        "provider_credits_per_episode": Approx(0.31, 0.005),
                        "post_hoc": {"difference": -0.0192, "ci95": (-0.1538, 0.1154)},
                    },
                    "honcho": {
                        "mean_episode_credits": Approx(2.08, 0.005),
                        "provider_credits_per_episode": Approx(0.17, 0.005),
                    },
                },
            ),
            "study2": merge(
                {"none": {"episodes": 22, "successes": 20}}
                | arms(
                    "episodes successes wins losses holm_p",
                    {
                        "session": (22, 19, 1, 2, 1.0),
                        "mem0": (22, 18, 0, 2, 1.0),
                        "honcho": (22, 17, 1, 4, 1.0),
                    },
                ),
                {
                    "honcho": {
                        "failures": {"contract": 2},
                        "post_hoc": {"difference": -0.1364, "ci95": (-0.3333, 0.0476)},
                    }
                },
            ),
        },
    ),
    Table(
        key="commitment",
        study="4",
        question="When a task is impossible without memory, does memory let the agent finish it?",
        csv="commitment-eval-v1-episodes.csv",
        command="research.analysis.commitment_analysis",
        analyse=_plain(commitment_analysis.analyse),
        fields=commitment_analysis.FIELDS,
        rows=157,
        expected={
            "included": 32,
            "excluded": [],
            "complete": False,
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 credits_per_session",
                {
                    "N": (0, 28, (0.0, 0.121), 1.38),
                    "Hc": (23, 24, (0.798, 0.993), 0.832),
                    "Hn": (26, 26, (0.871, 1.0), 0.835),
                    "M": (24, 24, (0.862, 1.0), 0.859),
                    "Ho": (19, 23, (0.629, 0.93), 0.934),
                },
            ),
            "primary": {"pairs": 22, "wins": 22, "losses": 0, "significant": True},
            "secondaries": {
                "M vs Hn": {"pairs": 20, "wins": 0, "losses": 0, "p": 1.0, "p_holm": 1.0},
                "Ho vs Hn": {"pairs": 18, "wins": 0, "losses": 3, "p": 0.25, "p_holm": 0.75},
                "Hc vs Hn": {"pairs": 18, "wins": 0, "losses": 1, "p": 1.0, "p_holm": 1.0},
            },
            "provider_memory": {
                "M": {"has_target_id": 20, "lacking_id_recovered": [4, 4]},
                "Ho": {"has_target_id": 11, "lacking_id_recovered": [9, 12]},
            },
        },
    ),
    Table(
        key="changed-mind",
        study="5",
        question="After a change of mind, does memory make the agent act on the latest agreement?",
        csv="changed-mind-eval-v1-episodes.csv",
        command="research.analysis.changed_mind_analysis",
        analyse=_plain(changed_mind_analysis.analyse),
        fields=changed_mind_analysis.FIELDS,
        rows=219,
        expected={
            "included": 31,
            "excluded": ["F02"],
            "complete": True,
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 stale declined credits_per_session",
                {
                    "N": (0, 31, (0.0, 0.11), 0, 31, 1.34),
                    "Hn": (30, 31, (0.838, 0.994), 0, 0, 0.901),
                    "M": (13, 31, (0.264, 0.592), 13, 5, 0.927),
                    "Ho": (3, 31, (0.033, 0.249), 0, 28, 1.433),
                    "Hoh": (2, 31, (0.018, 0.207), 0, 29, 1.389),
                },
            ),
            "primary_success": discordant(
                {
                    "M vs Hn": (0, 17, 0.0),
                    "Ho vs Hn": (1, 28, 0.0),
                    "Hoh vs Hn": (0, 28, 0.0),
                }
            ),
            "secondary_stale": discordant(
                {
                    "M vs Hn": (13, 0, 0.0007),
                    "Ho vs Hn": (0, 0, 1.0),
                    "Hoh vs Hn": (0, 0, 1.0),
                }
            ),
            "hoh_vs_ho_success": {"arm_only": 1, "reference_only": 2, "p": 1.0},
            "manipulation_hn_vs_n": {"arm_only": 30},
            "provider_memory": arms(
                "has_Y has_X has_both", {"M": (31, 29, 29), "Ho": (26, 16, 13), "Hoh": (24, 15, 12)}
            ),
        },
    ),
    Table(
        key="dated",
        study="6",
        question="With real time between conversations, does dating the memories help?",
        csv="changed-mind-dated-eval-v1-episodes.csv",
        command="research.analysis.changed_mind_dated_analysis",
        analyse=_plain(changed_mind_dated_analysis.analyse),
        fields=changed_mind_dated_analysis.FIELDS,
        rows=219,
        expected={
            "included": 31,
            "excluded": ["G03"],
            "complete": True,
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 stale declined credits_per_session",
                {
                    "Hn": (29, 31, (0.793, 0.982), 0, 2, 0.91),
                    "M": (17, 31, (0.378, 0.708), 9, 5, 0.969),
                    "Mi": (17, 31, (0.378, 0.708), 5, 9, 1.002),
                    "Ho": (3, 31, (0.033, 0.249), 0, 28, 1.468),
                    "Hod": (8, 31, (0.137, 0.432), 0, 22, 1.294),
                },
            ),
            "primary_success": discordant(
                {
                    "Mi vs M": (9, 9, 1.0),
                    "Hod vs Ho": (7, 2, 0.3594),
                }
            ),
            "secondary_stale": discordant(
                {
                    "Mi vs M": (4, 8, 0.7754),
                    "Hod vs Ho": (0, 0),
                }
            ),
            "descriptive_vs_hn": {
                "M vs Hn": {"success": {"arm_only": 1, "reference_only": 13}},
                "Mi vs Hn": {"success": {"arm_only": 0, "reference_only": 12}},
                "Ho vs Hn": {"success": {"arm_only": 0, "reference_only": 26}},
                "Hod vs Hn": {"success": {"arm_only": 1, "reference_only": 22}},
            },
            "provider_memory": Exactly(
                arms(
                    "has_Y has_X date_correct deferral_present",
                    {
                        "M": (31, 29, 0, 9),
                        "Mi": (31, 28, 28, 0),
                        "Ho": (18, 19, 0, 10),
                        "Hod": (18, 21, 31, 3),
                    },
                )
            ),
        },
    ),
    Table(
        key="honcho-features",
        study="7",
        question="Does Honcho's message search beat its dialectic, and does memory harm a helpful customer?",
        csv="honcho-features-eval-v1-episodes.csv",
        command="research.analysis.honcho_features_analysis",
        analyse=_plain(honcho_features_analysis.analyse),
        fields=honcho_features_analysis.FIELDS,
        rows=256,
        expected={
            "included": 32,
            "excluded": [],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": merge(
                arms(
                    "successes n wilson95 stale declined restated_sessions credits_per_session",
                    {
                        "Hs": (14, 32, (0.282, 0.607), 0, 18, 0, 1.24),
                        "Hod": (8, 32, (0.133, 0.421), 0, 24, 0, 1.305),
                        "Nr": (32, 32, (0.893, 1.0), 0, 0, 32, 1.1),
                        "Hodr": (27, 32, (0.682, 0.931), 0, 4, 21, 1.049),
                        "Mir": (30, 32, (0.799, 0.983), 2, 0, 9, 0.861),
                        "Hnr": (32, 32, (0.893, 1.0), 0, 0, 1, 0.863),
                    },
                ),
                arms(
                    "memory_has_Y memory_has_X",
                    {"Hs": (32, 32), "Hod": (21, 17), "Mir": (32, 31)},
                ),
            ),
            "family_1": {
                "tests": discordant(
                    {
                        "Hs vs Hod (success)": (11, 5, 0.2101),
                    }
                )
            },
            "family_2": {
                "tests": discordant(
                    {
                        "Hodr vs Nr (stale)": (0, 0, 1.0),
                        "Mir vs Nr (stale)": (2, 0, 1.0),
                        "Hodr vs Nr (success)": (0, 5, 0.25),
                        "Mir vs Nr (success)": (0, 2, 1.0),
                    }
                )
            },
        },
    ),
    Table(
        key="honcho-stage3",
        study="8",
        question="Do Honcho's dreaming, an on-demand memory tool, or facts the app writes into Honcho help?",
        csv="honcho-stage3-eval-v1-episodes.csv",
        command="research.analysis.honcho_stage3_analysis",
        analyse=_plain(honcho_stage3_analysis.analyse),
        fields=honcho_stage3_analysis.FIELDS,
        rows=214,
        expected={
            "included": 30,
            "excluded": ["L03", "L04"],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 stale declined infra_failed tool_sessions credits_per_session",
                {
                    "Hod": (8, 30, (0.142, 0.444), 0, 22, 0, 0, 1.252),
                    "Hdr": (12, 30, (0.246, 0.577), 0, 18, 0, 0, 1.164),
                    "Ht": (1, 30, (0.006, 0.167), 0, 29, 0, 5, 1.509),
                    "Hw": (26, 30, (0.703, 0.947), 0, 4, 1, 0, 0.882),
                    "Fd": (29, 30, (0.833, 0.994), 0, 1, 0, 0, 0.865),
                },
            ),
            "primary_success": {
                "tests": merge(
                    discordant(
                        {
                            "Hdr vs Hod (success)": (8, 4, Approx(0.387695, 5e-7)),
                            "Ht vs Hod (success)": (1, 8, Approx(0.039062, 5e-7)),
                            "Hw vs Hod (success)": (18, 0, Approx(8e-06, 5e-7)),
                        },
                        p="p",
                    ),
                    {"Ht vs Hod (success)": {"p_holm": 0.0781}},
                )
            },
            "secondary_facts": {
                "tests": discordant(
                    {
                        "Hw vs Fd (success)": (1, 4, Approx(0.375, 5e-7)),
                        "Fd vs Hod (success)": (21, 0, Approx(1e-06, 5e-7)),
                    },
                    p="p",
                )
            },
            "secondary_stale": {
                "tests": Exactly(
                    discordant(
                        {
                            "Hdr vs Hod (stale)": (0,),
                            "Ht vs Hod (stale)": (0,),
                            "Hw vs Hod (stale)": (0,),
                        }
                    )
                )
            },
        },
    ),
    Table(
        key="second-model",
        study="9",
        question="Do the change-of-mind results hold with a second model (gpt-6-luna) in every role?",
        csv="second-model-eval-v1-episodes.csv",
        command="research.analysis.second_model_analysis",
        analyse=_plain(second_model_analysis.analyse),
        fields=second_model_analysis.FIELDS,
        rows=192,
        expected={
            "included": 32,
            "excluded": [],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": merge(
                arms(
                    "successes n wilson95 stale declined credits_per_session",
                    {
                        "Hn": (30, 32, (0.799, 0.983), 0, 0, 0.562),
                        "Mi": (20, 32, (0.453, 0.771), 10, 1, 0.537),
                        "Hod": (27, 32, (0.682, 0.931), 0, 2, 0.56),
                        "Hs": (28, 32, (0.719, 0.95), 0, 0, 0.582),
                    },
                ),
                arms(
                    "memory_has_Y memory_has_X",
                    {"Mi": (32, 32), "Hod": (24, 1), "Hs": (32, 32)},
                ),
            ),
            "primary_success": {
                "tests": discordant(
                    {
                        "Mi vs Hn (success)": (2, 12, 0.0388),
                        "Hod vs Hn (success)": (2, 5, 0.9062),
                        "Hs vs Hn (success)": (1, 3, 0.9062),
                    }
                )
            },
            "secondary_stale": {
                "tests": discordant(
                    {
                        "Mi vs Hn (stale)": (10, 0, 0.0059),
                        "Hod vs Hn (stale)": (0, 0, 1.0),
                        "Hs vs Hn (stale)": (0, 0, 1.0),
                    }
                )
            },
        },
    ),
    Table(
        key="wd",
        study="10",
        question="Does writing the app's facts into Mem0 help, and does a memory tool match memory up front?",
        csv="write-it-down-eval-v1-episodes.csv",
        command="research.analysis.followups_analysis --study wd",
        analyse=_study(followups_analysis.analyse, "wd"),
        fields=followups_analysis.FIELDS,
        rows=219,
        expected={
            "included": 31,
            "excluded": ["Q30"],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 stale declined infra_failed tool_sessions credits_per_session",
                {
                    "Mi": (14, 31, (0.292, 0.622), 8, 9, 2, 0, 0.979),
                    "Mw": (28, 31, (0.751, 0.967), 1, 2, 0, 0, 0.864),
                    "Hn": (30, 31, (0.838, 0.994), 0, 1, 1, 0, 0.866),
                    "Tn": (5, 31, (0.071, 0.326), 0, 26, 2, 9, 1.432),
                    "Fd": (28, 31, (0.751, 0.967), 0, 3, 0, 0, 0.907),
                },
            ),
            "primary_success": {
                "tests": discordant(
                    {
                        "Mw vs Mi (success)": (15, 1, 0.0005),
                        "Tn vs Hn (success)": (1, 26, 0.0),
                    }
                )
            },
            "secondary": {
                "tests": discordant(
                    {
                        "Mw vs Fd (success)": (2, 2, 1.0),
                        "Mw vs Mi (stale)": (1, 8, 0.0781),
                    }
                )
            },
        },
    ),
    Table(
        key="m3",
        study="11",
        question="Do the change-of-mind results hold with a third model (mai-code-1.1-flash)?",
        csv="third-model-eval-v1-episodes.csv",
        command="research.analysis.followups_analysis --study m3",
        analyse=_study(followups_analysis.analyse, "m3"),
        fields=followups_analysis.FIELDS,
        rows=188,
        expected={
            "included": 31,
            "excluded": ["R28"],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 stale declined infra_failed tool_sessions credits_per_session",
                {
                    "Hn": (30, 31, (0.838, 0.994), 0, 0, 0, 0, 1.236),
                    "Mi": (10, 31, (0.186, 0.499), 20, 1, 0, 0, 1.244),
                    "Hod": (19, 31, (0.438, 0.763), 0, 11, 0, 0, 1.577),
                    "Fd": (31, 31, (0.89, 1.0), 0, 0, 0, 0, 1.035),
                },
            ),
            "primary_success": {
                "tests": discordant(
                    {
                        "Mi vs Hn (success)": (0, 20, 0.0),
                        "Hod vs Hn (success)": (1, 12, 0.0068),
                        "Fd vs Hn (success)": (1, 0, 1.0),
                    }
                )
            },
            "secondary_stale": {
                "tests": discordant(
                    {
                        "Mi vs Hn (stale)": (20, 0, 0.0),
                        "Hod vs Hn (stale)": (0, 0, 1.0),
                        "Fd vs Hn (stale)": (0, 0, 1.0),
                    }
                )
            },
        },
    ),
    Table(
        key="pz",
        study="12",
        question="Does a quoted, disowned instruction stored in memory lead the agent to act on it?",
        csv="poisoned-memory-eval-v1-episodes.csv",
        command="research.analysis.followups_analysis --study pz",
        analyse=_study(followups_analysis.analyse, "pz"),
        fields=followups_analysis.FIELDS,
        rows=172,
        expected={
            "included": 27,
            "excluded": ["S21", "S22", "S23", "S24", "S32"],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n wilson95 stale declined infra_failed tool_sessions credits_per_session",
                {
                    "Hn": (23, 27, (0.675, 0.941), 0, 4, 0, 0, 0.979),
                    "Mi": (20, 27, (0.553, 0.868), 0, 7, 0, 0, 0.996),
                    "Hod": (14, 27, (0.34, 0.693), 0, 12, 0, 0, 1.114),
                    "Fd": (26, 27, (0.817, 0.993), 0, 1, 0, 0, 0.795),
                },
            ),
            "primary_harm": {
                "tests": discordant(
                    {
                        "Mi vs Hn (stale)": (0, 0, 1.0),
                        "Hod vs Hn (stale)": (0, 0, 1.0),
                        "Fd vs Hn (stale)": (0, 0, 1.0),
                    }
                )
            },
            "secondary_success": {
                "tests": discordant(
                    {
                        "Mi vs Hn (success)": (2, 5, 0.75),
                        "Hod vs Hn (success)": (4, 13, 0.1471),
                        "Fd vs Hn (success)": (4, 1, 0.75),
                    }
                )
            },
        },
    ),
    Table(
        key="gx",
        study="13/15/16/17",
        question="Stale app summary and a tool prompt; one injected record; Graphiti and Hindsight; one shared scope.",
        csv="gaps-eval-v1-episodes.csv",
        command="research.analysis.gaps_analysis --study gx",
        analyse=_study(gaps_analysis.analyse, "gx"),
        fields=gaps_analysis.FIELDS,
        rows=498,
        expected={
            "included": 31,
            "excluded": ["U09"],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n stale superseded injected foreign declined infra_failed tool_sessions wilson95 credits_per_session",
                {
                    "Hn": (31, 31, 0, 0, 0, 0, 0, 0, 0, (0.89, 1.0), 0.859),
                    "Fd": (28, 31, 0, 0, 0, 0, 3, 0, 0, (0.751, 0.967), 0.838),
                    "Fs": (0, 31, 30, 30, 0, 0, 1, 0, 0, (-0.0, 0.11), 0.764),
                    "Fsh": (29, 31, 0, 0, 0, 0, 2, 0, 0, (0.793, 0.982), 0.926),
                    "Tn": (2, 31, 0, 0, 0, 0, 28, 0, 7, (0.018, 0.207), 1.526),
                    "Tp": (31, 31, 0, 0, 0, 0, 0, 0, 31, (0.89, 1.0), 0.997),
                    "Mi": (20, 31, 4, 4, 0, 0, 6, 0, 0, (0.469, 0.789), 0.962),
                    "Mz": (4, 31, 3, 3, 9, 5, 15, 0, 0, (0.051, 0.289), 1.199),
                    "Fz": (0, 31, 0, 0, 31, 16, 0, 0, 0, (-0.0, 0.11), 0.852),
                    "Hod": (6, 31, 0, 0, 0, 0, 25, 0, 0, (0.092, 0.363), 1.346),
                    "Hz": (0, 31, 0, 0, 8, 4, 23, 0, 0, (-0.0, 0.11), 1.302),
                    "Ms": (9, 31, 5, 5, 0, 0, 17, 0, 0, (0.161, 0.466), 1.255),
                    "Gr": (12, 31, 8, 8, 0, 0, 11, 0, 0, (0.237, 0.562), 1.059),
                    "Hi": (25, 31, 0, 0, 0, 0, 5, 0, 0, (0.637, 0.908), 0.991),
                },
            ),
            "study13_primary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Fsh vs Fs (success)": (29, 0, 0.0),
                            "Tp vs Tn (success)": (29, 0, 0.0),
                        }
                    )
                )
            },
            "study13_secondary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Fs vs Fd (success)": (0, 28, 0.0),
                            "Fsh vs Hn (success)": (0, 2, 0.5),
                            "Fs vs Fd (stale)": (30, 0, 0.0),
                        }
                    )
                )
            },
            "study15_primary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mz vs Mi (injected)": (9, 0, 0.0078),
                            "Hz vs Hod (injected)": (8, 0, 0.0078),
                            "Fz vs Fd (injected)": (31, 0, 0.0),
                        }
                    )
                )
            },
            "study15_secondary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mz vs Mi (success)": (1, 17, 0.0003),
                            "Hz vs Hod (success)": (0, 6, 0.0312),
                            "Fz vs Fd (success)": (0, 28, 0.0),
                        }
                    )
                )
            },
            "study16_primary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Gr vs Hn (success)": (0, 19, 0.0),
                            "Hi vs Hn (success)": (0, 6, 0.0312),
                        }
                    )
                )
            },
            "study16_secondary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Gr vs Mi (success)": (4, 12, 0.1536),
                            "Hi vs Mi (success)": (7, 2, 0.1797),
                        }
                    )
                )
            },
            "study17_primary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Ms vs Mi (success)": (2, 13, 0.0074),
                        }
                    )
                )
            },
            "study17_secondary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Ms vs Mi (foreign)": (0, 0, 1.0),
                        }
                    )
                )
            },
        },
    ),
    Table(
        key="lh",
        study="14",
        question="With five conversations and two changes of mind, does memory follow the latest?",
        csv="long-history-eval-v1-episodes.csv",
        command="research.analysis.gaps_analysis --study lh",
        analyse=_study(gaps_analysis.analyse, "lh"),
        fields=gaps_analysis.FIELDS,
        rows=288,
        expected={
            "included": 32,
            "excluded": [],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n stale superseded injected foreign declined infra_failed tool_sessions wilson95 credits_per_session",
                {
                    "Hn": (32, 32, 0, 0, 0, 0, 0, 0, 0, (0.893, 1.0), 0.831),
                    "Mi": (4, 32, 4, 5, 0, 0, 23, 0, 0, (0.05, 0.281), 1.326),
                    "Hod": (2, 32, 0, 0, 0, 0, 30, 0, 0, (0.017, 0.201), 1.399),
                    "Fd": (32, 32, 0, 0, 0, 0, 0, 0, 0, (0.893, 1.0), 0.795),
                },
            ),
            "primary_success": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mi vs Hn (success)": (0, 28, 0.0),
                            "Hod vs Hn (success)": (0, 30, 0.0),
                            "Fd vs Hn (success)": (0, 0, 1.0),
                        }
                    )
                )
            },
            "secondary_superseded": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mi vs Hn (superseded)": (5, 0, 0.1875),
                            "Hod vs Hn (superseded)": (0, 0, 1.0),
                            "Fd vs Hn (superseded)": (0, 0, 1.0),
                        }
                    )
                )
            },
        },
    ),
    Table(
        key="ac",
        study="18",
        question="Does the change-of-mind result hold for another decision (a pending order's address)?",
        csv="address-change-eval-v1-episodes.csv",
        command="research.analysis.gaps_analysis --study ac",
        analyse=_study(gaps_analysis.analyse, "ac"),
        fields=gaps_analysis.FIELDS,
        rows=192,
        expected={
            "included": 32,
            "excluded": [],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n stale superseded injected foreign declined infra_failed tool_sessions wilson95 credits_per_session",
                {
                    "Hn": (27, 32, 0, 0, 0, 0, 5, 0, 0, (0.682, 0.931), 0.866),
                    "Mi": (17, 32, 3, 3, 0, 0, 12, 0, 0, (0.364, 0.691), 0.919),
                    "Hod": (4, 32, 0, 0, 0, 0, 27, 0, 0, (0.05, 0.281), 1.211),
                    "Fd": (25, 32, 0, 0, 0, 0, 7, 0, 0, (0.612, 0.89), 0.783),
                },
            ),
            "primary_success": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mi vs Hn (success)": (1, 11, 0.0127),
                            "Hod vs Hn (success)": (3, 26, 0.0),
                            "Fd vs Hn (success)": (3, 5, 0.7266),
                        }
                    )
                )
            },
            "secondary_stale": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mi vs Hn (stale)": (3, 0, 0.75),
                            "Hod vs Hn (stale)": (0, 0, 1.0),
                            "Fd vs Hn (stale)": (0, 0, 1.0),
                        }
                    )
                )
            },
        },
    ),
    Table(
        key="gm",
        study="19",
        question="Do the stale-summary, check-memory and injected-record findings hold with gpt-6-luna?",
        csv="second-model-gaps-eval-v1-episodes.csv",
        command="research.analysis.gaps_analysis --study gm",
        analyse=_study(gaps_analysis.analyse, "gm"),
        fields=gaps_analysis.FIELDS,
        rows=416,
        expected={
            "included": 32,
            "excluded": [],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n stale superseded injected foreign declined infra_failed tool_sessions wilson95 credits_per_session",
                {
                    "Hn": (32, 32, 0, 0, 0, 0, 0, 0, 0, (0.893, 1.0), 0.492),
                    "Fd": (31, 32, 0, 0, 0, 0, 0, 0, 0, (0.843, 0.994), 0.492),
                    "Fs": (0, 32, 31, 31, 0, 0, 1, 0, 0, (0.0, 0.107), 0.507),
                    "Fsh": (32, 32, 0, 0, 0, 0, 0, 0, 0, (0.893, 1.0), 0.554),
                    "Tn": (32, 32, 0, 0, 0, 0, 0, 0, 32, (0.893, 1.0), 0.632),
                    "Tp": (32, 32, 0, 0, 0, 0, 0, 0, 32, (0.893, 1.0), 0.562),
                    "Mi": (22, 32, 9, 9, 0, 0, 0, 0, 0, (0.514, 0.82), 0.51),
                    "Mz": (3, 32, 3, 3, 26, 15, 0, 0, 0, (0.032, 0.242), 0.495),
                    "Fz": (0, 32, 0, 0, 32, 18, 0, 0, 0, (0.0, 0.107), 0.496),
                    "Hod": (31, 32, 0, 0, 0, 0, 0, 0, 0, (0.843, 0.994), 0.491),
                    "Hz": (0, 32, 0, 0, 32, 18, 0, 0, 0, (0.0, 0.107), 0.483),
                },
            ),
            "study13_primary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Fsh vs Fs (success)": (32, 0, 0.0),
                            "Tp vs Tn (success)": (0, 0, 1.0),
                        }
                    )
                )
            },
            "study13_secondary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Fs vs Fd (success)": (0, 31, 0.0),
                            "Fsh vs Hn (success)": (0, 0, 1.0),
                            "Fs vs Fd (stale)": (31, 0, 0.0),
                        }
                    )
                )
            },
            "study15_primary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mz vs Mi (injected)": (26, 0, 0.0),
                            "Hz vs Hod (injected)": (32, 0, 0.0),
                            "Fz vs Fd (injected)": (32, 0, 0.0),
                        }
                    )
                )
            },
            "study15_secondary": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mz vs Mi (success)": (1, 20, 0.0),
                            "Hz vs Hod (success)": (0, 31, 0.0),
                            "Fz vs Fd (success)": (0, 31, 0.0),
                        }
                    )
                )
            },
        },
    ),
    Table(
        key="lm",
        study="20",
        question="Does the five-conversation result hold with gpt-6-luna?",
        csv="second-model-long-history-eval-v1-episodes.csv",
        command="research.analysis.gaps_analysis --study lm",
        analyse=_study(gaps_analysis.analyse, "lm"),
        fields=gaps_analysis.FIELDS,
        rows=288,
        expected={
            "included": 32,
            "excluded": [],
            "not_run_arms": [],
            "leakage_sessions": 0,
            "arms": arms(
                "successes n stale superseded injected foreign declined infra_failed tool_sessions wilson95 credits_per_session",
                {
                    "Hn": (30, 32, 0, 0, 0, 0, 2, 0, 0, (0.799, 0.983), 0.509),
                    "Mi": (15, 32, 8, 16, 0, 6, 1, 0, 0, (0.309, 0.636), 0.573),
                    "Hod": (28, 32, 0, 0, 0, 0, 3, 0, 0, (0.719, 0.95), 0.527),
                    "Fd": (32, 32, 0, 0, 0, 0, 0, 0, 0, (0.893, 1.0), 0.478),
                },
            ),
            "primary_success": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mi vs Hn (success)": (1, 16, 0.0008),
                            "Hod vs Hn (success)": (2, 4, 1.0),
                            "Fd vs Hn (success)": (2, 0, 1.0),
                        }
                    )
                )
            },
            "secondary_superseded": {
                "tests": Exactly(
                    discordant(
                        {
                            "Mi vs Hn (superseded)": (16, 0, 0.0001),
                            "Hod vs Hn (superseded)": (0, 0, 1.0),
                            "Fd vs Hn (superseded)": (0, 0, 1.0),
                        }
                    )
                )
            },
        },
    ),
)
