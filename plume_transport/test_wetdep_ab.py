#!/usr/bin/env python3
"""Focused tests for wet-deposition HISTORY precision and status helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from validate_wetdep_ab import (
    CONVECTIVE_NONCLOSURE_CAUSALITY,
    FLOAT32_ULP_SAFETY_FACTOR,
    HEARTBEAT_SECONDS,
    NUMERICAL_FLOOR_KG,
    assess_native_loss,
    component_status,
    convective_activity,
    float32_ulp_tolerance_kg,
    final_status,
    integrated_native_loss_kg,
    large_scale_activity,
    load_ras_surface_reevap_report,
    ras_surface_reevap_report_passed,
    reconcile_native_loss,
    qck_common,
)


class WetDepositionValidatorTests(unittest.TestCase):
    def test_qck_v2_summary_reader_is_available_to_wetdep_validator(self) -> None:
        self.assertTrue(callable(qck_common.read_qck_v2_summary))

    def test_convective_nonclosure_causality_names_surface_diagnostic_omission(self) -> None:
        self.assertIn("K=1", CONVECTIVE_NONCLOSURE_CAUSALITY)
        self.assertIn("F(K,NA)>0", CONVECTIVE_NONCLOSURE_CAUSALITY)
        self.assertIn("re-evaporation gain", CONVECTIVE_NONCLOSURE_CAUSALITY)
        self.assertNotIn("DELQ", CONVECTIVE_NONCLOSURE_CAUSALITY)

    def test_global_ulp_bound_is_derived_from_every_archived_value(self) -> None:
        rates = np.array([[1.0, 2.0], [0.5, 0.0]], dtype=np.float32)
        expected = max(
            NUMERICAL_FLOOR_KG,
            FLOAT32_ULP_SAFETY_FACTOR
            * HEARTBEAT_SECONDS
            * float(np.spacing(np.abs(rates)).astype(np.float64).sum()),
        )
        self.assertEqual(float32_ulp_tolerance_kg(rates), expected)

    def test_column_ulp_bound_sums_only_vertical_ulps(self) -> None:
        rates = np.array(
            [[[1.0, 2.0]], [[0.5, 4.0]], [[0.25, 8.0]]], dtype=np.float32
        )
        actual = float32_ulp_tolerance_kg(rates, axes=(0,))
        expected = np.maximum(
            NUMERICAL_FLOOR_KG,
            FLOAT32_ULP_SAFETY_FACTOR
            * HEARTBEAT_SECONDS
            * np.spacing(np.abs(rates)).astype(np.float64).sum(axis=0),
        )
        np.testing.assert_array_equal(actual, expected)

    def test_ulp_gate_rejects_non_float32_and_nonfinite_arrays(self) -> None:
        with self.assertRaisesRegex(ValueError, "float32"):
            float32_ulp_tolerance_kg(np.ones((2, 2), dtype=np.float64))
        malformed = np.ones((2, 2), dtype=np.float32)
        malformed[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            float32_ulp_tolerance_kg(malformed)

    def test_native_loss_integration_preserves_signed_semantics(self) -> None:
        rates = np.array([1.0, -0.25], dtype=np.float32)
        self.assertEqual(integrated_native_loss_kg(rates), 450.0)

    def test_reconciliation_accepts_one_ulp_scale_and_rejects_excess(self) -> None:
        rates = np.array([1.0], dtype=np.float32)
        native = integrated_native_loss_kg(rates)
        tolerance = float(float32_ulp_tolerance_kg(rates))
        result = reconcile_native_loss(native + 0.9 * tolerance, native, rates, "test")
        self.assertAlmostEqual(result["checkpoint_minus_native_kg"], 0.9 * tolerance)
        with self.assertRaisesRegex(ValueError, "checkpoint_native_nonclosure"):
            reconcile_native_loss(native + 1.1 * tolerance, native, rates, "test")

    def test_nonclosure_assessment_preserves_machine_readable_partial_result(self) -> None:
        rates = np.array([1.0], dtype=np.float32)
        native = integrated_native_loss_kg(rates)
        tolerance = float(float32_ulp_tolerance_kg(rates))
        result = assess_native_loss(native + 2.0 * tolerance, native, rates, "test")
        self.assertEqual(result["status"], "fail")
        self.assertIn("checkpoint_native_nonclosure", result["failure_reason"])
        self.assertAlmostEqual(
            float(result["checkpoint_minus_native_kg"]), 2.0 * tolerance
        )

    def test_small_negative_roundoff_is_clipped_but_material_negative_fails(self) -> None:
        rates = np.zeros(1, dtype=np.float32)
        tolerance = float(float32_ulp_tolerance_kg(rates))
        result = reconcile_native_loss(-0.5 * tolerance, 0.0, rates, "test")
        self.assertEqual(result["checkpoint_loss_kg"], 0.0)
        self.assertIs(result["checkpoint_negative_roundoff_clipped"], True)
        with self.assertRaisesRegex(ValueError, "checkpoint_loss_materially_negative"):
            reconcile_native_loss(-1.1 * tolerance, 0.0, rates, "test")

    def test_component_specific_inconclusive_statuses(self) -> None:
        self.assertEqual(
            component_status(True, True), "diagnostic_pass_bounded_qck_v2"
        )
        self.assertIn("convective_overlap", component_status(False, True))
        self.assertIn("washout_overlap", component_status(True, False))
        self.assertIn("convective_or_washout", component_status(False, False))
        self.assertEqual(
            final_status(False, True, True),
            "diagnostic_pending_ras_surface_reevap",
        )
        self.assertEqual(
            final_status(False, True, True, True),
            "diagnostic_pass_bounded_qck_v2",
        )
        self.assertEqual(
            final_status(False, True, True, False),
            "diagnostic_fail_ras_surface_reevap_nonclosure",
        )
        self.assertEqual(
            final_status(False, True, True, True, False),
            "diagnostic_fail_convective_wetloss_nonclosure",
        )

    def test_ras_ledger_report_requires_passed_closure_and_thread_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ras.json"
            payload = {
                "schema_version": "ras-surface-reevap-ledger-v1",
                "status": "pass",
                "closure_failure_count": 0,
                "thread_determinism": {"off": True, "on": True},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = load_ras_surface_reevap_report(path)
            self.assertIs(ras_surface_reevap_report_passed(report), True)
            payload["status"] = "fail"
            payload["closure_failure_count"] = 1
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIs(
                ras_surface_reevap_report_passed(load_ras_surface_reevap_report(path)),
                False,
            )

    def test_convective_activity_requires_both_losses_above_ten_tolerances(self) -> None:
        result = {
            "float32_ulp_tolerance_kg": 2.0e-6,
            "checkpoint_loss_raw_kg": 2.1e-5,
            "native_loss_raw_kg": 2.2e-5,
        }
        self.assertIs(convective_activity(result)["active"], True)
        result["native_loss_raw_kg"] = 1.9e-5
        self.assertIs(convective_activity(result)["active"], False)

    def test_ls_activity_uses_larger_native_tolerance_and_all_three_signals(self) -> None:
        budget = {
            "float32_ulp_tolerance_kg": 1.0e-6,
            "native_loss_raw_kg": 3.1e-5,
        }
        wetlossls = {
            "float32_ulp_tolerance_kg": 3.0e-6,
            "native_loss_raw_kg": 3.2e-5,
        }
        result = large_scale_activity(3.3e-5, budget, wetlossls)
        self.assertEqual(result["activity_threshold_kg"], 3.0e-5)
        self.assertIs(result["active"], True)
        budget["native_loss_raw_kg"] = -3.1e-5
        self.assertIs(large_scale_activity(3.3e-5, budget, wetlossls)["active"], False)


if __name__ == "__main__":
    unittest.main()
