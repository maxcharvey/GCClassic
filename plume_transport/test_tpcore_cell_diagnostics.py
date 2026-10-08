#!/usr/bin/env python3
"""Focused unit tests for per-cell TPCORE event reconciliation."""

from __future__ import annotations

import unittest

from validate_tpcore_budget import Record
from validate_tpcore_cell_diagnostics import (
    G0_100_KG_PER_HPA_M2,
    CellEvent,
    validate,
)


def ledger_record(boundary: str, **changes: object) -> Record:
    values: dict[str, object] = {
        "schema_version": "plume-tpcore-budget-v2",
        "run_id": "unit-run",
        "manifest_id": "unit-manifest",
        "model_date": 20190101,
        "model_time": 1000,
        "elapsed_seconds": 600,
        "heartbeat_index": 2,
        "omp_thread_count": 1,
        "tpcore_call_index": 1,
        "boundary": boundary,
        "tag": "PLUME_PBL",
        "global_mass_kg": 1.0,
        "boundary_delta_kg": 0.0,
        "global_dry_air_mass_kg": 1.0,
        "negative_cell_count": 0,
        "minimum_mixing_ratio": 0.0,
        "total_negative_mass_kg": 0.0,
        "corrected_cell_count": 0,
        "correction_mass_delta_kg": 0.0,
        "qckxyz_invoked": 1,
    }
    values.update(changes)
    return Record(**values)  # type: ignore[arg-type]


def event(event_type: str, **changes: object) -> CellEvent:
    values: dict[str, object] = {
        "schema_version": "plume-tpcore-cell-events-v1",
        "run_id": "unit-run",
        "manifest_id": "unit-manifest",
        "model_date": 20190101,
        "model_time": 1000,
        "elapsed_seconds": 600,
        "heartbeat_index": 2,
        "omp_thread_count": 1,
        "tpcore_call_index": 1,
        "tag": "PLUME_PBL",
        "event_type": event_type,
        "i_tpcore": 1,
        "j_tpcore": 2,
        "k_tpcore": 72,
        "k_model": 1,
        "dq_after_horizontal_hpa": 0.1,
        "dq_after_fzppm_hpa": -2.0,
        "dq_at_correction_hpa": -2.0,
        "deficit_hpa": 2.0,
        "available_above_hpa": 0.0,
        "withdrawn_from_above_hpa": 0.0,
        "unfilled_deficit_hpa": 2.0,
        "q_before_kgkg": 0.0,
        "q_after_kgkg": 0.0,
        "delp_hpa": 1.0,
        "area_m2": 1.0,
        "event_mass_delta_kg": 2.0,
    }
    values.update(changes)
    return CellEvent(**values)  # type: ignore[arg-type]


class CellDiagnosticTests(unittest.TestCase):
    def test_bottom_and_floor_events_reconcile(self) -> None:
        ledger = [
            ledger_record(
                "POST_QCKXYZ", corrected_cell_count=1, correction_mass_delta_kg=2.0
            ),
            ledger_record("PRE_QPTR_NEGATIVE_FLOOR", negative_cell_count=1),
            ledger_record(
                "POST_QPTR_NEGATIVE_FLOOR",
                corrected_cell_count=1,
                correction_mass_delta_kg=3.0,
            ),
        ]
        events = [
            event("QCK_BOTTOM"),
            event(
                "QPTR_NEGATIVE_FLOOR",
                dq_after_horizontal_hpa=0.0,
                dq_after_fzppm_hpa=0.0,
                dq_at_correction_hpa=0.0,
                deficit_hpa=0.0,
                available_above_hpa=0.0,
                withdrawn_from_above_hpa=0.0,
                unfilled_deficit_hpa=0.0,
                q_before_kgkg=-0.5,
                q_after_kgkg=1.0e-26,
                event_mass_delta_kg=3.0,
            ),
        ]
        report = validate(ledger, events, 1.0e-12, 1.0e-12)
        self.assertEqual(report["status"], "PASS")

    def test_rejects_event_from_another_run(self) -> None:
        ledger = [
            ledger_record(
                "POST_QCKXYZ", corrected_cell_count=1, correction_mass_delta_kg=2.0
            ),
            ledger_record("PRE_QPTR_NEGATIVE_FLOOR"),
            ledger_record("POST_QPTR_NEGATIVE_FLOOR"),
        ]
        with self.assertRaisesRegex(ValueError, "run_id"):
            validate(
                ledger,
                [event("QCK_BOTTOM", run_id="other-run")],
                1.0e-12,
                1.0e-12,
            )

    def test_v2_conservative_bottom_event_reconciles_without_mass_creation(self) -> None:
        ledger = [
            ledger_record(
                "POST_QCKXYZ", corrected_cell_count=1, correction_mass_delta_kg=0.0
            ),
            ledger_record("PRE_QPTR_NEGATIVE_FLOOR", negative_cell_count=0),
            ledger_record(
                "POST_QPTR_NEGATIVE_FLOOR",
                corrected_cell_count=0,
                correction_mass_delta_kg=0.0,
            ),
        ]
        events = [
            event(
                "QCK_BOTTOM",
                schema_version="plume-tpcore-cell-events-v2",
                dq_after_fzppm_hpa=-10.0,
                dq_at_correction_hpa=-10.0,
                deficit_hpa=10.0,
                available_above_hpa=7.0,
                withdrawn_from_above_hpa=7.0,
                unfilled_deficit_hpa=3.0,
                event_mass_delta_kg=0.0,
                correction_policy="full_column_nearest_above_v1",
                correction_outcome="exact",
                donor_count=2,
                full_column_withdrawn_hpa=10.0,
                declared_roundoff_closure_hpa=0.0,
                correction_tolerance_hpa=1.0e-8,
            )
        ]
        report = validate(ledger, events, 1.0e-12, 1.0e-12)
        self.assertEqual(report["status"], "PASS")

    def test_v3_microclosure_is_distinct_and_mass_capped(self) -> None:
        closure_kg = 3.0 * G0_100_KG_PER_HPA_M2
        ledger = [
            ledger_record(
                "POST_QCKXYZ",
                corrected_cell_count=1,
                correction_mass_delta_kg=closure_kg,
            ),
            ledger_record("PRE_QPTR_NEGATIVE_FLOOR"),
            ledger_record("POST_QPTR_NEGATIVE_FLOOR"),
        ]
        events = [
            event(
                "QCK_BOTTOM",
                schema_version="plume-tpcore-cell-events-v3",
                dq_after_fzppm_hpa=-10.0,
                dq_at_correction_hpa=-10.0,
                deficit_hpa=10.0,
                available_above_hpa=7.0,
                withdrawn_from_above_hpa=7.0,
                unfilled_deficit_hpa=3.0,
                event_mass_delta_kg=closure_kg,
                correction_policy="full_column_nearest_above_microclosure_v2",
                correction_outcome="microclosure_closed",
                donor_count=1,
                full_column_withdrawn_hpa=7.0,
                declared_closure_hpa=3.0,
                ordinary_roundoff_tolerance_hpa=1.0e-8,
                microclosure_event_max_kg=40.0,
                microclosure_call_max_kg=40.0,
            )
        ]
        report = validate(
            ledger,
            events,
            1.0e-12,
            1.0e-12,
            40.0,
            40.0,
            50.0,
            60.0,
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["microclosure_total_kg"], closure_kg)


if __name__ == "__main__":
    unittest.main()
