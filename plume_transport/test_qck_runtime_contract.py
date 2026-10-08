#!/usr/bin/env python3
"""Focused tests for the survey-free bounded-QCK downstream contract."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from validate_pbl_ab import read_qck_v2_summary


class QckRuntimeContractTests(unittest.TestCase):
    def test_fortran_source_rejects_survey_plus_microclosure(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src/GEOS-Chem/GeosCore/tpcore_fvdas_mod.F90"
        ).read_text(encoding="utf-8")
        message = (
            "QCK_BOTTOM native survey and microclosure ceilings are mutually exclusive"
        )
        self.assertIn(message, source)
        call = "CALL Get_Qck_Bottom_Microclosure_Limits"
        conflict = "IF ( Survey_Native_Behavior .and. &"
        self.assertLess(source.index(call), source.index(conflict))

    def test_production_contract_has_optional_run_wide_ceiling(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src/GEOS-Chem/GeosCore/tpcore_fvdas_mod.F90"
        ).read_text(encoding="utf-8")
        self.assertIn("GC_QCK_BOTTOM_MICROCLOSURE_RUN_MAX_KG", source)
        self.assertIn("Qck_Bottom_Microclosure_Run_Total_Kg", source)
        self.assertIn(
            "QCK_BOTTOM microclosure run ceiling exceeded for tracer=", source
        )
        self.assertIn(
            "QCK_BOTTOM bounded-production run closure summary: closure_kg=",
            source,
        )
        self.assertIn(
            "!$OMP CRITICAL( Qck_Bottom_Limit_Initialization )", source
        )
        self.assertIn("!$OMP CRITICAL( Qck_Bottom_Run_Closure )", source)
        # Existing short diagnostic cases remain valid with only the event and
        # call pair; a run ceiling is an additional production control.
        self.assertIn("IF ( Run_Provided .and. .not. Event_Provided ) THEN", source)

    def test_v2_summary_accepts_three_passed_reports_without_survey(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "OutputDir"
            output.mkdir()
            reports = {
                "tpcore_budget_validation.json": {"status": "pass"},
                "tpcore_cell_diagnostic_validation.json": {
                    "status": "PASS",
                    "event_count": 12,
                    "microclosure_total_kg": 2.5e-8,
                    "microclosure_by_tag_kg": {"PLUME_PBL": 2.5e-8},
                },
                "tpcore_donor_diagnostic_validation.json": {
                    "status": "PASS",
                    "microclosure_total_kg": 2.5e-8,
                    "microclosure_by_tag_kg": {"PLUME_PBL": 2.5e-8},
                },
            }
            for name, payload in reports.items():
                (output / name).write_text(json.dumps(payload), encoding="utf-8")
            summary = read_qck_v2_summary(Path(temporary))
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["event_count"], 12)
            self.assertEqual(summary["microclosure_total_kg"], 2.5e-8)

    def test_v2_summary_rejects_native_survey_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "OutputDir"
            output.mkdir()
            (output / "qck_bottom_survey_v1.csv").write_text("header\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden"):
                read_qck_v2_summary(Path(temporary))


if __name__ == "__main__":
    unittest.main()
