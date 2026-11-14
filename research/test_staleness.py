from __future__ import annotations

import unittest

from research.staleness import (
    CONDITIONS,
    REGIMES,
    decide,
    dev_families,
    eval_seed,
    family_values,
    generate_families,
    ledger_stops,
    render_memory,
    scenario,
    score,
)


def billed(call_id: int, credits: float, status: str = "complete") -> dict[str, object]:
    return {
        "call_id": call_id,
        "event": "copilot-request-completed",
        "metrics": {
            "ai_credits_status": status,
            "total_nano_aiu": credits * 1e9,
            "model_metrics": {
                "m": {"usage": {"input_tokens": 1, "output_tokens": 1}, "requests": {"count": 1}}
            },
        },
    }


STARTED = {"event": "copilot-request-started"}


class StalenessTests(unittest.TestCase):
    def test_dev_fixtures_are_deterministic_and_eval_needs_a_tag_commit(self) -> None:
        self.assertEqual(dev_families(), dev_families())
        self.assertEqual(len(dev_families()), 4)
        with self.assertRaises(ValueError):
            eval_seed("memory-study-v2")
        other = generate_families(eval_seed("a" * 40), 48, family_values(dev_families()))
        self.assertFalse(family_values(other) & family_values(dev_families()))

    def test_ordinary_and_validity_see_same_metadata_and_labels_stay_hidden(self) -> None:
        family = dev_families()[0]
        for regime in REGIMES:
            case = scenario(family, regime)
            self.assertNotIn("'correct'", str(case["visible"]))
            self.assertNotIn("'obsolete'", str(case["visible"]))
            ordinary = render_memory(case["visible"], "ordinary")
            validity = render_memory(case["visible"], "validity")
            self.assertEqual(render_memory(case["visible"], "none"), "")
            self.assertTrue(set(validity.splitlines()) <= set(ordinary.splitlines()))
        reset = scenario(family, "reset")
        self.assertIn(family.new, render_memory(reset["visible"], "ordinary"))
        self.assertNotIn(family.new, render_memory(reset["visible"], "validity"))
        self.assertIn("restored", render_memory(reset["visible"], "validity"))
        corrected = render_memory(scenario(family, "corrected")["visible"], "validity")
        self.assertIn("Correction", corrected)
        self.assertNotIn("[m1;", corrected)
        current = scenario(family, "current")
        self.assertIn(family.new, render_memory(current["visible"], "validity"))
        self.assertIsNone(current["visible"]["tool_view"][f"default {family.kind}"])

    def test_score_classifies_targets_deterministically(self) -> None:
        family = dev_families()[1]
        hidden = scenario(family, "reset")["hidden"]
        self.assertEqual(score(hidden, f"  {family.old.upper()}. "), "correct")
        self.assertEqual(score(hidden, family.new), "obsolete")
        self.assertEqual(score(hidden, None), "abstain")
        self.assertEqual(score(hidden, "somewhere else"), "other")
        self.assertEqual(score(scenario(family, "current")["hidden"], family.old), "other")

    def test_decision_needs_effect_bound_and_both_gates(self) -> None:
        def rows(ordinary_obsolete: str, validity_current: str) -> list[dict[str, str]]:
            out = []
            for family in range(48):
                for condition in CONDITIONS:
                    out.append({"family": str(family), "regime": "current", "condition": condition,
                                "outcome": "abstain" if condition == "none" else
                                validity_current if condition == "validity" else "correct"})  # fmt: skip
                    for regime in ("reset", "corrected"):
                        stale = condition == "ordinary" and family % 2 == 0
                        out.append({"family": str(family), "regime": regime, "condition": condition,
                                    "outcome": ordinary_obsolete if stale else "correct"})  # fmt: skip
            return out

        result = decide(rows("obsolete", "correct"))
        self.assertEqual(result["effect_o_minus_v_obsolete"], 0.5)
        self.assertGreater(result["lower_bound_95"], 0)
        self.assertTrue(result["supported"])
        self.assertFalse(decide(rows("correct", "correct"))["supported"])
        harmed = decide(rows("obsolete", "abstain"))
        self.assertFalse(harmed["gates"]["non_harm"])
        self.assertFalse(harmed["supported"])

    def test_ledger_stops_on_cap_mismatch_missing_billing_and_expensive_calls(self) -> None:
        self.assertEqual(ledger_stops([STARTED, billed(1, 0.2)], request_cap=4), [])
        reasons = ledger_stops(
            [STARTED, STARTED, STARTED, billed(1, 1.5), billed(2, 0.1, status="incomplete")],
            request_cap=2,
            credit_stop=1.0,
        )
        self.assertEqual(
            [r.split(":")[0].split(" ")[0] for r in reasons],
            ["request", "count", "call", "missing", "settled"],
        )


if __name__ == "__main__":
    unittest.main()
