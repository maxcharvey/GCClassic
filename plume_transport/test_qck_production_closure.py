from __future__ import annotations

import unittest

from validate_qck_production_closure import validate_log


EXPECTED_CLOSURE_KG = 6.18367880730447
END = "**************   E N D   O F   G E O S -- C H E M   **************"


def _log(closure: str = "6.18367880730447E+00", cap: str = "1.0E+01") -> str:
    return (
        "model output\n"
        "QCK_BOTTOM bounded-production run closure summary: "
        f"closure_kg= {closure}, run_max_kg= {cap}\n"
        f"{END}\n"
    )


class QckProductionClosureTests(unittest.TestCase):
    def test_expected_production_summary_passes(self) -> None:
        result = validate_log(
            _log(),
            expected_closure_kg=EXPECTED_CLOSURE_KG,
            expected_run_cap_kg=10.0,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["closure_difference_kg"], 0.0)

    def test_duplicate_summary_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_log(
                _log() + _log(),
                expected_closure_kg=EXPECTED_CLOSURE_KG,
                expected_run_cap_kg=10.0,
            )

    def test_missing_end_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "end banner"):
            validate_log(
                _log().replace(END, ""),
                expected_closure_kg=EXPECTED_CLOSURE_KG,
                expected_run_cap_kg=10.0,
            )

    def test_sizing_output_in_production_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "sizing diagnostics"):
            validate_log(
                _log() + "QCK_BOTTOM_SIZING_SUMMARY schema_version=1 enabled=1\n",
                expected_closure_kg=EXPECTED_CLOSURE_KG,
                expected_run_cap_kg=10.0,
            )

    def test_closure_difference_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "differs"):
            validate_log(
                _log(closure="6.20"),
                expected_closure_kg=EXPECTED_CLOSURE_KG,
                expected_run_cap_kg=10.0,
            )

    def test_wrong_run_cap_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "reviewed policy"):
            validate_log(
                _log(cap="9.0"),
                expected_closure_kg=EXPECTED_CLOSURE_KG,
                expected_run_cap_kg=10.0,
            )

    def test_run_cap_breach_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_log(
                _log(closure="10.1"),
                expected_closure_kg=10.1,
                expected_run_cap_kg=10.0,
            )


if __name__ == "__main__":
    unittest.main()
