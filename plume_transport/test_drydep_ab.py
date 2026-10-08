#!/usr/bin/env python3
"""Focused unit tests for dry-deposition mass conversion and reconciliation."""

from __future__ import annotations

import unittest

import numpy as np

from validate_drydep_ab import (
    AVOGADRO_MOLEC_MOL,
    BUDGET_HISTORY_ABSOLUTE_PRECISION_KG,
    _heartbeat_order,
    absolute_record_times_seconds,
    budget_drydep_loss_kg,
    checkpoint_drydep_loss_kg,
    drydep_flux_to_mass_kg,
    reconcile_losses,
    reconciliation_tolerance_kg,
)


class DryDepositionValidatorTests(unittest.TestCase):
    def test_segmented_local_zero_times_reconstruct_two_heartbeats(self) -> None:
        first = absolute_record_times_seconds(
            np.array([0.0]), "minutes since 2019-01-01 00:00:00"
        )
        second = absolute_record_times_seconds(
            np.array([0.0]), "minutes since 2019-01-01 00:10:00 GMT"
        )
        order = _heartbeat_order([second, first], "synthetic segmented diagnostic")
        self.assertEqual(order.tolist(), [1, 0])

    def test_single_file_two_record_layout_remains_valid(self) -> None:
        records = absolute_record_times_seconds(
            np.array([0.0, 10.0]), "minutes since 2019-01-01 00:00:00"
        )
        self.assertEqual(_heartbeat_order([records], "synthetic diagnostic").tolist(), [0, 1])

    def test_time_layout_fails_unless_exactly_two_records_at_600_seconds(self) -> None:
        first = absolute_record_times_seconds(
            np.array([0.0]), "seconds since 2019-01-01 00:00:00"
        )
        with self.assertRaisesRegex(ValueError, "exactly two"):
            _heartbeat_order([first], "synthetic diagnostic")
        wrong = absolute_record_times_seconds(
            np.array([0.0]), "seconds since 2019-01-01 00:05:00"
        )
        with self.assertRaisesRegex(ValueError, "600-second"):
            _heartbeat_order([first, wrong], "synthetic diagnostic")

    def test_molecular_flux_conversion_uses_area_duration_and_carbon_mw(self) -> None:
        area = np.array([[2.0, 3.0], [5.0, 7.0]], dtype=np.float64)
        flux = np.full(area.shape, AVOGADRO_MOLEC_MOL, dtype=np.float64)
        actual = drydep_flux_to_mass_kg(flux, area)
        expected = float(area.sum()) * 1.0e4 * 600.0 * 12.01e-3
        self.assertAlmostEqual(actual, expected, places=9)

    def test_conversion_rejects_shape_negative_and_nonfinite_inputs(self) -> None:
        area = np.ones((2, 2), dtype=np.float64)
        with self.assertRaisesRegex(ValueError, "shape mismatch"):
            drydep_flux_to_mass_kg(np.ones((2, 3)), area)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            drydep_flux_to_mass_kg(-np.ones((2, 2)), area)
        with self.assertRaisesRegex(ValueError, "finite"):
            drydep_flux_to_mass_kg(np.array([[np.nan, 0.0], [0.0, 0.0]]), area)

    def test_checkpoint_loss_is_off_increment_minus_on_increment(self) -> None:
        self.assertAlmostEqual(checkpoint_drydep_loss_kg(250.0, 249.75), 0.25)

    def test_budget_loss_negates_on_minus_off_net_rate(self) -> None:
        off = np.array([[0.3, 0.2], [0.0, 0.0]], dtype=np.float64)
        on = np.array([[0.29, 0.18], [-0.01, 0.0]], dtype=np.float64)
        # ON-OFF sums to -0.04 kg/s, hence positive loss is 24 kg/600 s.
        self.assertAlmostEqual(budget_drydep_loss_kg(off, on), 24.0)

    def test_budget_loss_rejects_malformed_arrays(self) -> None:
        with self.assertRaisesRegex(ValueError, "shape mismatch"):
            budget_drydep_loss_kg(np.zeros((2, 2)), np.zeros((2, 3)))
        malformed = np.zeros((2, 2))
        malformed[0, 0] = np.inf
        with self.assertRaisesRegex(ValueError, "finite"):
            budget_drydep_loss_kg(np.zeros((2, 2)), malformed)

    def test_reconciliation_uses_absolute_floor_for_tiny_loss(self) -> None:
        native = 1.0e-12
        self.assertEqual(
            reconciliation_tolerance_kg(native),
            BUDGET_HISTORY_ABSOLUTE_PRECISION_KG,
        )
        result = reconcile_losses(native + 0.5e-5, native)
        self.assertEqual(
            result["tolerance_kg"], BUDGET_HISTORY_ABSOLUTE_PRECISION_KG
        )

    def test_reconciliation_uses_relative_tolerance_for_large_loss(self) -> None:
        native = 10.0
        self.assertAlmostEqual(reconciliation_tolerance_kg(native), 2.0e-3)
        result = reconcile_losses(native + 1.9e-3, native)
        self.assertAlmostEqual(result["checkpoint_minus_budget_kg"], 1.9e-3)

    def test_reconciliation_fails_outside_tolerance_or_for_negative_loss(self) -> None:
        with self.assertRaisesRegex(ValueError, "mismatch"):
            reconcile_losses(1.0 + 3.0e-4, 1.0)
        with self.assertRaisesRegex(ValueError, "materially negative"):
            reconcile_losses(-1.0e-4, 0.0)

    def test_tiny_negative_checkpoint_loss_is_reported_and_clipped(self) -> None:
        result = reconcile_losses(-0.5e-5, 0.0)
        self.assertEqual(result["checkpoint_loss_raw_kg"], -0.5e-5)
        self.assertEqual(result["checkpoint_loss_kg"], 0.0)
        self.assertIs(result["checkpoint_negative_roundoff_clipped"], True)


if __name__ == "__main__":
    unittest.main()
