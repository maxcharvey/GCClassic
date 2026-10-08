"""Focused tests for direct AOP-to-R3 interval aggregation."""

from __future__ import annotations

import numpy as np

from prepare_firex_aq_aop_merge import (
    ABSORPTION_FIELDS,
    aggregate_absorption,
)


def test_each_band_uses_half_open_intervals_and_its_own_valid_mask() -> None:
    times = np.array(
        [
            "2019-08-06T00:00:00",
            "2019-08-06T00:00:59",
            "2019-08-06T00:01:00",
        ],
        dtype="datetime64[s]",
    )
    bounds = np.array(
        [
            ["2019-08-06T00:00:00", "2019-08-06T00:01:00"],
            ["2019-08-06T00:01:00", "2019-08-06T00:02:00"],
        ],
        dtype="datetime64[s]",
    )
    measurements = {
        "abs_dry_405": np.array([1.0, 3.0, 9.0]),
        "abs_dry_532": np.array([-9999.0, 4.0, 8.0]),
        "abs_dry_664": np.array([2.0, -8888.0, 6.0]),
    }
    result = aggregate_absorption(times, measurements, bounds)
    np.testing.assert_allclose(result["abs_dry_405"]["mean"], [2.0, 9.0])
    np.testing.assert_allclose(result["abs_dry_532"]["mean"], [4.0, 8.0])
    np.testing.assert_allclose(result["abs_dry_664"]["mean"], [2.0, 6.0])
    np.testing.assert_array_equal(
        result["abs_dry_664"]["count"], [1, 1]
    )


def test_all_missing_band_remains_missing() -> None:
    times = np.array(["2019-08-06T00:00:00"], dtype="datetime64[s]")
    bounds = np.array(
        [["2019-08-06T00:00:00", "2019-08-06T00:01:00"]],
        dtype="datetime64[s]",
    )
    measurements = {
        name: np.array([-9999.0]) for name in ABSORPTION_FIELDS
    }
    result = aggregate_absorption(times, measurements, bounds)
    for name in ABSORPTION_FIELDS:
        assert np.isnan(result[name]["mean"][0])
        assert result[name]["count"][0] == 0
