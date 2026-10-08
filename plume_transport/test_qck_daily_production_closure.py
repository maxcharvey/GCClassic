from __future__ import annotations

import unittest

from validate_qck_daily_production_closure import validate_log


END = "**************   E N D   O F   G E O S -- C H E M   **************"


def _log(closure: str = "3.5", cap: str = "10.0") -> str:
    return (
        "model output\n"
        "QCK_BOTTOM bounded-production run closure summary: "
        f"closure_kg= {closure}, run_max_kg= {cap}\n"
        f"{END}\n"
    )


class QckDailyProductionClosureTests(unittest.TestCase):
    def test_daily_summary_below_cap_passes(self) -> None:
        result = validate_log(_log(), expected_run_cap_kg=10.0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["run_headroom_kg"], 6.5)

    def test_exact_cap_passes(self) -> None:
        result = validate_log(_log(closure="10.0"), expected_run_cap_kg=10.0)
        self.assertEqual(result["status"], "PASS")

    def test_above_cap_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_log(_log(closure="10.1"), expected_run_cap_kg=10.0)

    def test_wrong_cap_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "reviewed policy"):
            validate_log(_log(cap="11.0"), expected_run_cap_kg=10.0)

    def test_duplicate_summary_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_log(_log() + _log(), expected_run_cap_kg=10.0)

    def test_missing_end_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "end banner"):
            validate_log(_log().replace(END, ""), expected_run_cap_kg=10.0)

    def test_sizing_output_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "sizing diagnostics"):
            validate_log(
                _log() + "QCK_BOTTOM_SIZING_SUMMARY schema_version=1 enabled=1\n",
                expected_run_cap_kg=10.0,
            )


if __name__ == "__main__":
    unittest.main()
