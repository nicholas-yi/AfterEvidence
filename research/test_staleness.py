from __future__ import annotations

import unittest

from research.staleness import (
    DEV_REQUEST_CAP,
    EVAL_REQUEST_CAP,
    PAID_CONDITIONS,
    REGIMES,
    STORE_NOTE,
    AccountEnv,
    decide,
    dev_families,
    eval_seed,
    family_values,
    feasibility,
    generate_families,
    is_valid,
    ledger_stops,
    render_memory,
    scenario,
    score,
)


def billed(call_id: int, credits: float, status: str = "complete") -> dict[str, object]:
    usage = {"usage": {"input_tokens": 1, "output_tokens": 1}, "requests": {"count": 1}}
    return {
        "call_id": call_id,
        "event": "copilot-request-completed",
        "metrics": {
            "ai_credits_status": status,
            "total_nano_aiu": credits * 1e9,
            "model_metrics": {"m": usage},
        },
    }


STARTED = {"event": "copilot-request-started"}


class StalenessTests(unittest.TestCase):
    def test_fixtures_are_deterministic_and_eval_needs_a_tag_commit(self) -> None:
        self.assertEqual(dev_families(), dev_families())
        self.assertEqual((len(dev_families()), DEV_REQUEST_CAP, EVAL_REQUEST_CAP), (4, 144, 3456))
        with self.assertRaises(ValueError):
            eval_seed("memory-study-v2")
        other = generate_families(eval_seed("a" * 40), 48, family_values(dev_families()))
        self.assertFalse(family_values(other) & family_values(dev_families()))

    def test_validity_filter_keeps_post_restore_and_drops_rolled_back_or_superseded(self) -> None:
        self.assertTrue(is_valid({"epoch": 5}, STORE_NOTE))
        self.assertTrue(is_valid({"epoch": 2}, STORE_NOTE))
        self.assertFalse(is_valid({"epoch": 3}, STORE_NOTE))
        self.assertFalse(is_valid({"epoch": 4}, STORE_NOTE))
        self.assertFalse(is_valid({"epoch": 1, "superseded_by": "m2"}, None))
        family = dev_families()[0]
        current = scenario(family, "current")["visible"]
        self.assertIn(family.new, render_memory(current, "filtered"))
        reset = scenario(family, "reset")["visible"]
        self.assertNotIn(family.new, render_memory(reset, "filtered"))
        corrected = render_memory(scenario(family, "corrected")["visible"], "filtered")
        self.assertNotIn("[m1;", corrected)
        self.assertIn("[m2;", corrected)

    def test_regimes_offer_four_values_keep_obsolete_on_file_and_hide_labels(self) -> None:
        for family in dev_families():
            for regime in REGIMES:
                case = scenario(family, regime)
                visible, hidden = case["visible"], case["hidden"]
                on_file = visible["account"][f"{family.kind}s on file"]
                self.assertEqual(len(set(on_file)), 4)
                self.assertIn(hidden["correct"], on_file)
                if hidden["obsolete"]:
                    self.assertIn(hidden["obsolete"], on_file)
                    self.assertEqual(
                        visible["account"][f"default {family.kind}"], hidden["correct"]
                    )
                else:
                    self.assertIsNone(visible["account"][f"default {family.kind}"])
                self.assertNotIn("'correct'", str(visible))
                plain = render_memory(visible, "plain")
                annotated = render_memory(visible, "annotated")
                self.assertNotIn("epoch", plain)
                self.assertNotIn("superseded", plain)
                self.assertIn("epoch", annotated)
                self.assertEqual(render_memory(visible, "none"), "")
        current = render_memory(scenario(dev_families()[0], "current")["visible"], "annotated")
        self.assertIn("Store note", current)

    def test_env_records_lookup_before_submit_and_scores(self) -> None:
        family = dev_families()[1]
        case = scenario(family, "reset")
        env = AccountEnv(case)
        env.call("submit_target", {"value": family.new})
        self.assertEqual(env.outcome(), {"outcome": "obsolete", "looked_up_before_submit": False})
        env = AccountEnv(case)
        self.assertEqual(env.call("lookup_account", {})[f"default {family.kind}"], family.old)
        env.call("submit_target", {"value": f" {family.old.upper()}. "})
        self.assertEqual(env.outcome(), {"outcome": "correct", "looked_up_before_submit": True})
        self.assertEqual(AccountEnv(case).outcome()["outcome"], "failed")
        self.assertEqual(score(case["hidden"], None), "abstain")
        self.assertEqual(score(case["hidden"], family.decoys[0]), "other")

    def test_decision_needs_effect_bound_and_both_gates(self) -> None:
        def rows(plain_stale: str, annotated_current: str) -> list[dict[str, object]]:
            out: list[dict[str, object]] = []
            for family in range(48):
                for condition in PAID_CONDITIONS:
                    current = {
                        "none": "abstain",
                        "plain": "correct",
                        "annotated": annotated_current,
                    }
                    out.append(
                        {
                            "family": str(family),
                            "regime": "current",
                            "condition": condition,
                            "outcome": current[condition],
                            "looked_up_before_submit": True,
                        }
                    )
                    for regime in ("reset", "corrected"):
                        stale = condition == "plain" and family % 2 == 0
                        out.append(
                            {
                                "family": str(family),
                                "regime": regime,
                                "condition": condition,
                                "outcome": plain_stale if stale else "correct",
                            }
                        )
            return out

        result = decide(rows("obsolete", "correct"))
        self.assertEqual(result["effect_plain_minus_annotated_obsolete"], 0.5)
        self.assertGreater(result["lower_bound_95"], 0)
        self.assertTrue(result["supported"])
        self.assertFalse(decide(rows("correct", "correct"))["supported"])
        harmed = decide(rows("obsolete", "abstain"))
        self.assertFalse(harmed["gates"]["non_harm"])
        self.assertFalse(harmed["gates"]["positive_control"])
        self.assertFalse(harmed["supported"])

    def test_stage_a_floor_blocks_stage_b(self) -> None:
        rows = [
            {"condition": "plain", "regime": r, "outcome": "correct"}
            for r in ("reset", "corrected")
        ] * 4
        self.assertEqual(
            feasibility(rows), {"plain_obsolete": 0, "plain_episodes": 8, "request_stage_b": False}
        )
        rows[0]["outcome"] = "obsolete"
        self.assertTrue(feasibility(rows)["request_stage_b"])

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
