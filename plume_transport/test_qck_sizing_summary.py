#!/usr/bin/env python3
"""Focused tests for QCK corrected-trajectory sizing summaries."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from validate_qck_sizing_summary import (
    compare_normalized_summaries,
    parse_qck_sizing_summary,
    validate_qck_sizing_summary,
)


VALID_LOG = """\
QCK_BOTTOM bounded-production run closure summary: closure_kg=  8.00000000000000E-01, run_max_kg=  1.00000000000000E+01
QCK_BOTTOM_SIZING_SUMMARY schema_version=1 enabled=1
QCK_BOTTOM_SIZING_MAX_ATTEMPTED event_kg=  3.31698345892059E-01 species_index=159 species_name=ISOP nymd=20190805 nhms=190000 ordinal=115 i=39 j=60 k=72 status=4
QCK_BOTTOM_SIZING_MAX_ACCEPTED event_kg=  3.31698345892059E-01 species_index=159 species_name=ISOP nymd=20190805 nhms=190000 ordinal=115 i=39 j=60 k=72
QCK_BOTTOM_SIZING_MAX_CALL closure_kg=  3.50000000000000E-01 species_index=159 species_name=ISOP nymd=20190805 nhms=190000 ordinal=115
QCK_BOTTOM_SIZING_TOTAL closure_kg=  8.00000000000001E-01 bounded_closure_kg=  8.00000000000000E-01 event_max_kg=  1.00000000000000E+01 call_max_kg=  1.00000000000000E+01 run_max_kg=  1.00000000000000E+01
"""


class QckSizingSummaryTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        temporary = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        )
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        temporary.write(text)
        temporary.close()
        return Path(temporary.name)

    def test_complete_summary_passes_and_reconciles(self) -> None:
        result = validate_qck_sizing_summary(
            self._write(VALID_LOG), 10.0, 10.0, 10.0
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["max_attempted"]["species_name"], "ISOP")
        self.assertEqual(result["max_attempted"]["ordinal"], "115")

    def test_missing_final_record_fails_closed(self) -> None:
        log = VALID_LOG.replace(
            "QCK_BOTTOM_SIZING_MAX_CALL closure_kg=", "REMOVED closure_kg="
        )
        with self.assertRaisesRegex(ValueError, "missing final"):
            parse_qck_sizing_summary(self._write(log))

    def test_non_reconciled_total_is_rejected(self) -> None:
        log = VALID_LOG.replace(
            "closure_kg=  8.00000000000001E-01 bounded_closure_kg=",
            "closure_kg=  9.00000000000000E-01 bounded_closure_kg=",
        )
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            parse_qck_sizing_summary(self._write(log))

    def test_cap_breach_is_rejected(self) -> None:
        log = VALID_LOG.replace(
            "event_kg=  3.31698345892059E-01 species_index=159",
            "event_kg=  1.10000000000000E+01 species_index=159",
            1,
        )
        with self.assertRaisesRegex(ValueError, "attempted-event maximum exceeds"):
            parse_qck_sizing_summary(self._write(log))

    def test_normalized_comparison_allows_preregistered_roundoff(self) -> None:
        left = parse_qck_sizing_summary(self._write(VALID_LOG))
        right_log = VALID_LOG.replace(
            "closure_kg=  8.00000000000001E-01 bounded_closure_kg=",
            "closure_kg=  8.00000000000002E-01 bounded_closure_kg=",
        )
        right = parse_qck_sizing_summary(self._write(right_log))
        compare_normalized_summaries(left, right)

    def test_normalized_comparison_requires_same_event_identity(self) -> None:
        left = parse_qck_sizing_summary(self._write(VALID_LOG))
        right = parse_qck_sizing_summary(
            self._write(VALID_LOG.replace("ordinal=115 i=39", "ordinal=116 i=39", 1))
        )
        with self.assertRaisesRegex(ValueError, "max_attempted"):
            compare_normalized_summaries(left, right)


if __name__ == "__main__":
    unittest.main()
