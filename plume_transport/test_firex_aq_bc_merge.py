#!/usr/bin/env python3
"""Focused tests for interval-aware FIREX-AQ SP2 aggregation."""

from __future__ import annotations

import unittest

import numpy as np

from prepare_firex_aq_bc_merge import aggregate_sp2


class FirexAqBcMergeTests(unittest.TestCase):
    def test_half_open_interval_membership(self) -> None:
        times = np.array([
            "2019-08-06T00:00:00",
            "2019-08-06T00:00:59",
            "2019-08-06T00:01:00",
        ], dtype="datetime64[s]")
        bounds = np.array([
            ["2019-08-06T00:00:00", "2019-08-06T00:01:00"],
            ["2019-08-06T00:01:00", "2019-08-06T00:02:00"],
        ], dtype="datetime64[s]")
        result = aggregate_sp2(
            times,
            np.array([1.0, 3.0, 9.0]),
            np.array([0.0, 0.0, 1.0]),
            bounds,
        )
        np.testing.assert_allclose(result["mass_mean"], [2.0, 9.0])
        np.testing.assert_array_equal(result["sample_count"], [2, 1])

    def test_mixed_dilution_state_is_not_coerced_to_binary(self) -> None:
        times = np.array([
            "2019-08-06T00:00:00",
            "2019-08-06T00:00:01",
        ], dtype="datetime64[s]")
        bounds = np.array([[
            "2019-08-06T00:00:00", "2019-08-06T00:01:00"
        ]], dtype="datetime64[s]")
        result = aggregate_sp2(
            times,
            np.array([2.0, 4.0]),
            np.array([0.0, 1.0]),
            bounds,
        )
        self.assertEqual(result["dilution_binary"][0], -127)
        self.assertEqual(result["dilution_mixed"][0], 1)
        self.assertAlmostEqual(float(result["dilution_fraction"][0]), 0.5)

    def test_declared_sentinels_are_excluded(self) -> None:
        times = np.array([
            "2019-08-06T00:00:00",
            "2019-08-06T00:00:01",
            "2019-08-06T00:00:02",
        ], dtype="datetime64[s]")
        bounds = np.array([[
            "2019-08-06T00:00:00", "2019-08-06T00:01:00"
        ]], dtype="datetime64[s]")
        result = aggregate_sp2(
            times,
            np.array([-9999.99, -8888.0, 6.0]),
            np.array([0.0, 0.0, 0.0]),
            bounds,
        )
        self.assertEqual(result["sample_count"][0], 1)
        self.assertAlmostEqual(float(result["mass_mean"][0]), 6.0)

    def test_no_valid_mass_remains_missing(self) -> None:
        times = np.array(
            ["2019-07-22T00:00:00"], dtype="datetime64[s]"
        )
        bounds = np.array([[
            "2019-07-22T00:00:00", "2019-07-22T00:01:00"
        ]], dtype="datetime64[s]")
        result = aggregate_sp2(
            times,
            np.array([-9999.99]),
            np.array([0.0]),
            bounds,
        )
        self.assertTrue(np.isnan(result["mass_mean"][0]))
        self.assertEqual(result["sample_count"][0], 0)


if __name__ == "__main__":
    unittest.main()
