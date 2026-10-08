from __future__ import annotations

import math
import unittest

from validate_qck_production_policy import validate_policy


MEASURED_EVENT_KG = 0.387317199880078
MEASURED_CALL_KG = 0.402193073080724
MEASURED_RUN_KG = 6.18367880730447


class QckProductionPolicyTests(unittest.TestCase):
    def test_reviewed_policy_accepts_measured_demands(self) -> None:
        result = validate_policy(
            measured_event_kg=MEASURED_EVENT_KG,
            measured_call_kg=MEASURED_CALL_KG,
            measured_run_kg=MEASURED_RUN_KG,
            event_cap_kg=0.40,
            call_cap_kg=0.41,
            run_cap_kg=10.0,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertAlmostEqual(result["event_headroom_kg"], 0.012682800119922)
        self.assertAlmostEqual(result["call_headroom_kg"], 0.007806926919276)
        self.assertAlmostEqual(result["run_headroom_kg"], 3.81632119269553)
        self.assertAlmostEqual(
            result["event_headroom_percent_over_measured"], 3.2745254081
        )
        self.assertAlmostEqual(
            result["call_headroom_percent_over_measured"], 1.9410893528
        )

    def test_value_equal_to_each_ceiling_is_accepted(self) -> None:
        result = validate_policy(
            measured_event_kg=0.40,
            measured_call_kg=0.41,
            measured_run_kg=10.0,
            event_cap_kg=0.40,
            call_cap_kg=0.41,
            run_cap_kg=10.0,
        )
        self.assertEqual(result["status"], "PASS")

    def test_event_above_reviewed_ceiling_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds event ceiling"):
            validate_policy(
                measured_event_kg=math.nextafter(0.40, math.inf),
                measured_call_kg=0.405,
                measured_run_kg=MEASURED_RUN_KG,
                event_cap_kg=0.40,
                call_cap_kg=0.41,
                run_cap_kg=10.0,
            )

    def test_call_above_reviewed_ceiling_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds call ceiling"):
            validate_policy(
                measured_event_kg=MEASURED_EVENT_KG,
                measured_call_kg=math.nextafter(0.41, math.inf),
                measured_run_kg=MEASURED_RUN_KG,
                event_cap_kg=0.40,
                call_cap_kg=0.41,
                run_cap_kg=10.0,
            )

    def test_run_above_daily_ceiling_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds run ceiling"):
            validate_policy(
                measured_event_kg=MEASURED_EVENT_KG,
                measured_call_kg=MEASURED_CALL_KG,
                measured_run_kg=math.nextafter(10.0, math.inf),
                event_cap_kg=0.40,
                call_cap_kg=0.41,
                run_cap_kg=10.0,
            )

    def test_call_ceiling_below_event_ceiling_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "call ceiling"):
            validate_policy(
                measured_event_kg=MEASURED_EVENT_KG,
                measured_call_kg=MEASURED_CALL_KG,
                measured_run_kg=MEASURED_RUN_KG,
                event_cap_kg=0.41,
                call_cap_kg=0.40,
                run_cap_kg=10.0,
            )

    def test_nonfinite_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            validate_policy(
                measured_event_kg=float("nan"),
                measured_call_kg=MEASURED_CALL_KG,
                measured_run_kg=MEASURED_RUN_KG,
                event_cap_kg=0.40,
                call_cap_kg=0.41,
                run_cap_kg=10.0,
            )


if __name__ == "__main__":
    unittest.main()
