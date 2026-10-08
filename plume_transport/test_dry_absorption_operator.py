#!/usr/bin/env python3
"""Focused tests for the Stage-1 dry absorption numerical oracle."""

from __future__ import annotations

import unittest

import numpy as np

from dry_absorption_operator import (
    DryAbsorptionContractError,
    absorption_angstrom_exponent,
    assert_component_closure,
    component_total_mm1,
    convert_ambient_to_reference_volume,
    dry_absorption_optical_depth,
    exact_band_dry_absorption_mm1,
    layer_absorption_coefficient_mm1,
    log_log_interpolate_absorption,
)


class DryAbsorptionOperatorTests(unittest.TestCase):
    def test_dry_absorption_from_extinction_and_ssa(self) -> None:
        actual = dry_absorption_optical_depth([0.2, 0.4], [0.75, 1.0])
        np.testing.assert_allclose(actual, [0.05, 0.0], rtol=0.0, atol=1e-16)

    def test_invalid_ssa_fails_closed(self) -> None:
        with self.assertRaises(DryAbsorptionContractError):
            dry_absorption_optical_depth(0.2, 1.01)

    def test_layer_coefficient_is_ambient_volume_mm1(self) -> None:
        actual = layer_absorption_coefficient_mm1(2.0e-4, 100.0)
        self.assertAlmostEqual(float(actual), 2.0)

    def test_exact_lut_node_preserves_zero(self) -> None:
        actual = log_log_interpolate_absorption(400.0, 400.0, 500.0, 0.0, 2.0)
        self.assertEqual(float(actual), 0.0)

    def test_power_law_interpolation(self) -> None:
        target = 450.0
        actual = log_log_interpolate_absorption(
            target,
            400.0,
            500.0,
            4.0,
            4.0 * (500.0 / 400.0) ** -2.0,
        )
        expected = 4.0 * (target / 400.0) ** -2.0
        self.assertAlmostEqual(float(actual), expected, places=14)

    def test_two_zero_endpoints_remain_zero(self) -> None:
        actual = log_log_interpolate_absorption(450.0, 400.0, 500.0, 0.0, 0.0)
        self.assertEqual(float(actual), 0.0)

    def test_mixed_zero_bracket_fails_closed(self) -> None:
        with self.assertRaises(DryAbsorptionContractError):
            log_log_interpolate_absorption(450.0, 400.0, 500.0, 0.0, 1.0)

    def test_exact_band_operator_interpolates_absorption_not_ssa(self) -> None:
        actual = exact_band_dry_absorption_mm1(
            450.0,
            400.0,
            500.0,
            lower_dry_extinction_optical_depth=4.0e-4,
            upper_dry_extinction_optical_depth=2.56e-4,
            lower_dry_single_scattering_albedo=0.5,
            upper_dry_single_scattering_albedo=0.5,
            box_height_m=100.0,
        )
        expected_aaod = 2.0e-4 * (450.0 / 400.0) ** -2.0
        self.assertAlmostEqual(float(actual), expected_aaod / 100.0 * 1e6)

    def test_reference_volume_conversion_requires_explicit_state(self) -> None:
        actual = convert_ambient_to_reference_volume(
            10.0,
            ambient_pressure_hpa=800.0,
            ambient_temperature_k=280.0,
            reference_pressure_hpa=1000.0,
            reference_temperature_k=250.0,
        )
        self.assertAlmostEqual(float(actual), 14.0)
        with self.assertRaises(DryAbsorptionContractError):
            convert_ambient_to_reference_volume(10.0, 800.0, 280.0, np.nan, 250.0)

    def test_component_total_and_closure(self) -> None:
        components = {"wet_brc": [1.0, 2.0], "dry_brc": [0.5, 0.0]}
        total = component_total_mm1(components)
        np.testing.assert_array_equal(total, [1.5, 2.0])
        assert_component_closure(total, components)

    def test_component_nonclosure_fails(self) -> None:
        with self.assertRaisesRegex(
            DryAbsorptionContractError, "closure failed"
        ):
            assert_component_closure(
                2.0,
                {"wet_brc": 1.0, "dry_brc": 0.5},
            )

    def test_aae_uses_positive_405_and_664_endpoints(self) -> None:
        long_absorption = 2.0
        short_absorption = long_absorption * (405.0 / 664.0) ** -3.0
        actual = absorption_angstrom_exponent(
            short_absorption, long_absorption
        )
        self.assertAlmostEqual(float(actual), 3.0, places=14)
        with self.assertRaises(DryAbsorptionContractError):
            absorption_angstrom_exponent(-0.1, long_absorption)


if __name__ == "__main__":
    unittest.main()
