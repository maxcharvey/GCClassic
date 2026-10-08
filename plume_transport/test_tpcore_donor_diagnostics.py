#!/usr/bin/env python3
"""Focused unit tests for Phase-D0 donor-inventory reconciliation."""

from __future__ import annotations

import unittest

from validate_tpcore_cell_diagnostics import G0_100_KG_PER_HPA_M2, CellEvent
from validate_tpcore_donor_diagnostics import DonorEvent, validate


def cell_event(**changes: object) -> CellEvent:
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
        "event_type": "QCK_BOTTOM",
        "i_tpcore": 1,
        "j_tpcore": 2,
        "k_tpcore": 72,
        "k_model": 1,
        "dq_after_horizontal_hpa": 0.0,
        "dq_after_fzppm_hpa": -10.0,
        "dq_at_correction_hpa": -10.0,
        "deficit_hpa": 10.0,
        "available_above_hpa": 7.0,
        "withdrawn_from_above_hpa": 7.0,
        "unfilled_deficit_hpa": 3.0,
        "q_before_kgkg": 0.0,
        "q_after_kgkg": 0.0,
        "delp_hpa": 1.0,
        "area_m2": 1.0,
        "event_mass_delta_kg": 3.0,
    }
    values.update(changes)
    return CellEvent(**values)  # type: ignore[arg-type]


def donor_event(**changes: object) -> DonorEvent:
    values: dict[str, object] = {
        "schema_version": "plume-tpcore-donor-events-v1",
        "run_id": "unit-run",
        "manifest_id": "unit-manifest",
        "model_date": 20190101,
        "model_time": 1000,
        "elapsed_seconds": 600,
        "heartbeat_index": 2,
        "omp_thread_count": 1,
        "tpcore_call_index": 1,
        "tag": "PLUME_PBL",
        "i_tpcore": 1,
        "j_tpcore": 2,
        "k_tpcore": 72,
        "k_model": 1,
        "deficit_hpa": 10.0,
        "immediate_available_above_hpa": 7.0,
        "withdrawn_from_immediate_hpa": 7.0,
        "column_total_above_hpa": 15.0,
        "column_positive_above_hpa": 15.0,
        "column_net_mass_hpa": 5.0,
        "unfilled_by_immediate_hpa": 3.0,
        "unfillable_column_mass_hpa": 0.0,
        "area_m2": 1.0,
        "event_mass_delta_kg": 3.0,
    }
    values.update(changes)
    return DonorEvent(**values)  # type: ignore[arg-type]


class DonorDiagnosticTests(unittest.TestCase):
    def test_farther_up_donor_is_column_feasible(self) -> None:
        report = validate(
            [cell_event()], [donor_event()], 1.0e-12, 1.0e-12, 1.0e-12
        )
        summary = report["summary"]
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(summary["immediate_shortfall_event_count"], 1)
        self.assertEqual(summary["column_feasible_event_count"], 1)
        self.assertEqual(summary["column_infeasible_event_count"], 0)

    def test_no_donor_column_is_infeasible(self) -> None:
        report = validate(
            [cell_event()],
            [
                donor_event(
                    column_total_above_hpa=7.0,
                    column_positive_above_hpa=7.0,
                    column_net_mass_hpa=-3.0,
                    unfillable_column_mass_hpa=3.0,
                )
            ],
            1.0e-12,
            1.0e-12,
            1.0e-12,
        )
        summary = report["summary"]
        self.assertEqual(summary["column_feasible_event_count"], 0)
        self.assertEqual(summary["column_infeasible_event_count"], 1)
        self.assertEqual(summary["total_unfillable_column_mass_hpa"], 3.0)

    def test_roundoff_limited_column_is_feasible_within_tolerance(self) -> None:
        column_total = 10.0 - 1.0e-12
        column_net = column_total - 10.0
        report = validate(
            [cell_event()],
            [
                donor_event(
                    column_total_above_hpa=column_total,
                    column_positive_above_hpa=column_total,
                    column_net_mass_hpa=column_net,
                    unfillable_column_mass_hpa=-column_net,
                )
            ],
            1.0e-9,
            1.0e-30,
            1.0e-12,
        )
        summary = report["summary"]
        self.assertEqual(summary["column_feasible_event_count"], 1)
        self.assertEqual(summary["column_strictly_feasible_event_count"], 0)
        self.assertEqual(summary["column_roundoff_limited_event_count"], 1)
        self.assertEqual(summary["column_infeasible_event_count"], 0)

    def test_positive_deficit_below_absolute_tolerance_is_valid(self) -> None:
        deficit = 5.0e-31
        report = validate(
            [
                cell_event(
                    deficit_hpa=deficit,
                    dq_after_fzppm_hpa=-deficit,
                    dq_at_correction_hpa=-deficit,
                    available_above_hpa=0.0,
                    withdrawn_from_above_hpa=0.0,
                    unfilled_deficit_hpa=deficit,
                    event_mass_delta_kg=0.0,
                )
            ],
            [
                donor_event(
                    deficit_hpa=deficit,
                    immediate_available_above_hpa=0.0,
                    withdrawn_from_immediate_hpa=0.0,
                    column_total_above_hpa=deficit,
                    column_positive_above_hpa=deficit,
                    column_net_mass_hpa=0.0,
                    unfilled_by_immediate_hpa=deficit,
                    unfillable_column_mass_hpa=0.0,
                    event_mass_delta_kg=0.0,
                )
            ],
            1.0e-9,
            1.0e-30,
            1.0e-9,
        )
        self.assertEqual(report["status"], "PASS")

    def test_rejects_inconsistent_column_net_mass(self) -> None:
        with self.assertRaisesRegex(ValueError, "column net mass"):
            validate(
                [cell_event()],
                [donor_event(column_net_mass_hpa=4.0)],
                1.0e-12,
                1.0e-12,
                1.0e-12,
            )

    def test_v2_conservative_full_column_withdrawal(self) -> None:
        cell = cell_event(
            schema_version="plume-tpcore-cell-events-v2",
            event_mass_delta_kg=0.0,
            correction_policy="full_column_nearest_above_v1",
            correction_outcome="exact",
            donor_count=2,
            full_column_withdrawn_hpa=10.0,
            declared_roundoff_closure_hpa=0.0,
            correction_tolerance_hpa=1.0e-8,
        )
        donor = donor_event(
            schema_version="plume-tpcore-donor-events-v2",
            event_mass_delta_kg=0.0,
            correction_policy="full_column_nearest_above_v1",
            correction_outcome="exact",
            donor_count=2,
            full_column_withdrawn_hpa=10.0,
            declared_roundoff_closure_hpa=0.0,
            correction_tolerance_hpa=1.0e-8,
        )
        report = validate([cell], [donor], 1.0e-12, 1.0e-12, 1.0e-12)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["column_feasible_event_count"], 1)

    def test_v3_microclosure_reconciles_pressure_mass_and_caps(self) -> None:
        closure_kg = 3.0 * G0_100_KG_PER_HPA_M2
        common = {
            "event_mass_delta_kg": closure_kg,
            "correction_policy": "full_column_nearest_above_microclosure_v2",
            "correction_outcome": "microclosure_closed",
            "donor_count": 1,
            "full_column_withdrawn_hpa": 7.0,
            "declared_closure_hpa": 3.0,
            "ordinary_roundoff_tolerance_hpa": 1.0e-8,
            "microclosure_event_max_kg": 40.0,
            "microclosure_call_max_kg": 40.0,
        }
        cell = cell_event(
            schema_version="plume-tpcore-cell-events-v3",
            **common,
        )
        donor = donor_event(
            schema_version="plume-tpcore-donor-events-v3",
            column_total_above_hpa=7.0,
            column_positive_above_hpa=7.0,
            column_net_mass_hpa=-3.0,
            unfillable_column_mass_hpa=3.0,
            **common,
        )
        report = validate(
            [cell],
            [donor],
            1.0e-12,
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
