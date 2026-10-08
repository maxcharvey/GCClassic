"""Focused tests for deterministic FIREX aircraft/model matching."""

from __future__ import annotations

import numpy as np

from plume_transport.firex_model_match import (
    cyclic_longitude_delta_degrees,
    geometric_layer_centres_m,
    match_aircraft_to_model,
)


def _model():
    times = np.array(
        ["2019-08-06T00:00:00", "2019-08-06T01:00:00"],
        dtype="datetime64[s]",
    )
    lat = np.array([-2.0, 2.0])
    lon = np.array([-177.5, 177.5])
    height = np.full((2, 3, 2, 2), 1000.0)
    phis = np.zeros((2, 2))
    field = np.arange(2 * 3 * 2 * 2).reshape(2, 3, 2, 2)
    return times, lat, lon, height, phis, field


def test_longitude_delta_wraps_dateline() -> None:
    delta = cyclic_longitude_delta_degrees(
        np.array([-179.0, 170.0]), 179.0
    )
    np.testing.assert_allclose(delta, [2.0, -9.0])


def test_layer_centres_include_surface_geopotential() -> None:
    centres = geometric_layer_centres_m(
        [100.0, 200.0], 9.80665 * 1000.0
    )
    np.testing.assert_allclose(centres, [1050.0, 1200.0])


def test_nearest_match_returns_indices_offsets_and_value() -> None:
    times, lat, lon, height, phis, field = _model()
    result = match_aircraft_to_model(
        observation_time=np.array(["2019-08-06T00:10:00"]),
        observation_latitude=[1.5],
        observation_longitude=[179.0],
        observation_altitude_m=[1600.0],
        model_time=times,
        model_latitude=lat,
        model_longitude=lon,
        model_box_height_m=height,
        model_surface_geopotential_m2_s2=phis,
        model_fields={"abs405": field},
    )
    assert result.valid[0]
    assert result.model_time_index[0] == 0
    assert result.model_level_index[0] == 1
    assert result.model_lat_index[0] == 1
    assert result.model_lon_index[0] == 1
    assert result.time_offset_seconds[0] == -600.0
    assert result.longitude_offset_degrees[0] == -1.5
    assert result.altitude_offset_m[0] == -100.0
    assert result.sampled_fields["abs405"][0] == field[0, 1, 1, 1]


def test_time_and_vertical_limits_reject_without_sampling() -> None:
    times, lat, lon, height, phis, field = _model()
    result = match_aircraft_to_model(
        observation_time=np.array(
            ["2019-08-06T03:00:00", "2019-08-06T00:00:00"]
        ),
        observation_latitude=[0.0, 0.0],
        observation_longitude=[0.0, 0.0],
        observation_altitude_m=[500.0, 10000.0],
        model_time=times,
        model_latitude=lat,
        model_longitude=lon,
        model_box_height_m=height,
        model_surface_geopotential_m2_s2=phis,
        model_fields={"abs405": field},
        maximum_time_offset_seconds=1800.0,
        maximum_vertical_offset_m=1000.0,
    )
    assert result.rejection_reason.tolist() == [
        "time_offset_exceeds_limit",
        "vertical_offset_exceeds_limit",
    ]
    assert np.all(np.isnan(result.sampled_fields["abs405"]))
