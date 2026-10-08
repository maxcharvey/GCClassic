#!/usr/bin/env python3
"""Deterministic aircraft-to-GEOS-Chem matching for FIREX-AQ.

This module contains no file-format assumptions and performs no fitting.  It
matches observations to the nearest model time, horizontal grid centre, and
geometric layer centre while retaining all offsets and explicit rejection
reasons.  The caller must provide numeric AOP reference conditions before
using the optional standard-volume conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray

from plume_transport.dry_absorption_operator import (
    convert_ambient_to_reference_volume,
)


G_STANDARD_M_S2 = 9.80665


class FirexModelMatchError(ValueError):
    """Raised when model/aircraft arrays violate the matching contract."""


@dataclass(frozen=True)
class MatchResult:
    valid: NDArray[np.bool_]
    rejection_reason: NDArray[np.str_]
    model_time_index: NDArray[np.int64]
    model_level_index: NDArray[np.int64]
    model_lat_index: NDArray[np.int64]
    model_lon_index: NDArray[np.int64]
    time_offset_seconds: NDArray[np.float64]
    latitude_offset_degrees: NDArray[np.float64]
    longitude_offset_degrees: NDArray[np.float64]
    altitude_offset_m: NDArray[np.float64]
    model_layer_centre_altitude_m: NDArray[np.float64]
    sampled_fields: dict[str, NDArray[np.float64]]


def cyclic_longitude_delta_degrees(
    model_longitude: ArrayLike,
    observation_longitude: ArrayLike,
) -> NDArray[np.float64]:
    """Return signed shortest model-minus-observation longitude difference."""

    model = np.asarray(model_longitude, dtype=np.float64)
    observation = np.asarray(observation_longitude, dtype=np.float64)
    return (model - observation + 180.0) % 360.0 - 180.0


def geometric_layer_centres_m(
    box_height_m: ArrayLike,
    surface_geopotential_m2_s2: float,
) -> NDArray[np.float64]:
    """Return MSL layer-centre altitudes from bottom-up box heights."""

    height = np.asarray(box_height_m, dtype=np.float64)
    if height.ndim != 1 or not np.all(np.isfinite(height)) or np.any(height <= 0):
        raise FirexModelMatchError(
            "box heights must be one-dimensional, finite, and positive"
        )
    if not np.isfinite(surface_geopotential_m2_s2):
        raise FirexModelMatchError("surface geopotential must be finite")
    surface_m = surface_geopotential_m2_s2 / G_STANDARD_M_S2
    return surface_m + np.cumsum(height) - 0.5 * height


def _datetime_ns(values: ArrayLike, name: str) -> NDArray[np.datetime64]:
    result = np.asarray(values).astype("datetime64[ns]")
    if result.ndim != 1 or np.any(np.isnat(result)):
        raise FirexModelMatchError(f"{name} must be finite one-dimensional times")
    return result


def match_aircraft_to_model(
    *,
    observation_time: ArrayLike,
    observation_latitude: ArrayLike,
    observation_longitude: ArrayLike,
    observation_altitude_m: ArrayLike,
    model_time: ArrayLike,
    model_latitude: ArrayLike,
    model_longitude: ArrayLike,
    model_box_height_m: ArrayLike,
    model_surface_geopotential_m2_s2: ArrayLike,
    model_fields: Mapping[str, ArrayLike],
    maximum_time_offset_seconds: float = 1800.0,
    maximum_vertical_offset_m: float = 1000.0,
) -> MatchResult:
    """Match aircraft rows to nearest model centres with fail-closed bounds.

    Model 3-D fields and box height must have shape ``(time, lev, lat, lon)``.
    Surface geopotential may be ``(lat, lon)`` or ``(time, lat, lon)``.
    Longitude matching is cyclic.  Rows outside time or vertical tolerances
    are retained with NaN sampled fields and an explicit rejection reason.
    """

    obs_time = _datetime_ns(observation_time, "observation_time")
    mod_time = _datetime_ns(model_time, "model_time")
    obs_lat = np.asarray(observation_latitude, dtype=np.float64)
    obs_lon = np.asarray(observation_longitude, dtype=np.float64)
    obs_alt = np.asarray(observation_altitude_m, dtype=np.float64)
    mod_lat = np.asarray(model_latitude, dtype=np.float64)
    mod_lon = np.asarray(model_longitude, dtype=np.float64)
    bxheight = np.asarray(model_box_height_m, dtype=np.float64)
    phis = np.asarray(model_surface_geopotential_m2_s2, dtype=np.float64)

    n_obs = obs_time.size
    if any(array.shape != (n_obs,) for array in (obs_lat, obs_lon, obs_alt)):
        raise FirexModelMatchError("aircraft coordinate arrays must share time shape")
    if not np.all(np.isfinite(obs_lat)) or not np.all(np.isfinite(obs_lon)):
        raise FirexModelMatchError("aircraft latitude and longitude must be finite")
    if mod_lat.ndim != 1 or mod_lon.ndim != 1:
        raise FirexModelMatchError("model latitude and longitude must be 1-D")
    if bxheight.ndim != 4:
        raise FirexModelMatchError("model box height must be time,lev,lat,lon")
    expected = (mod_time.size, bxheight.shape[1], mod_lat.size, mod_lon.size)
    if bxheight.shape != expected:
        raise FirexModelMatchError(
            f"model box height shape {bxheight.shape} != {expected}"
        )
    if phis.shape not in (
        (mod_lat.size, mod_lon.size),
        (mod_time.size, mod_lat.size, mod_lon.size),
    ):
        raise FirexModelMatchError("surface geopotential has incompatible shape")
    if maximum_time_offset_seconds < 0 or maximum_vertical_offset_m < 0:
        raise FirexModelMatchError("matching tolerances must be nonnegative")

    fields = {
        name: np.asarray(value, dtype=np.float64)
        for name, value in model_fields.items()
    }
    for name, field in fields.items():
        if field.shape != expected:
            raise FirexModelMatchError(
                f"model field {name} shape {field.shape} != {expected}"
            )

    invalid_index = np.int64(-1)
    ti = np.full(n_obs, invalid_index, dtype=np.int64)
    ki = np.full(n_obs, invalid_index, dtype=np.int64)
    yi = np.full(n_obs, invalid_index, dtype=np.int64)
    xi = np.full(n_obs, invalid_index, dtype=np.int64)
    dt = np.full(n_obs, np.nan)
    dlat = np.full(n_obs, np.nan)
    dlon = np.full(n_obs, np.nan)
    dz = np.full(n_obs, np.nan)
    centre_alt = np.full(n_obs, np.nan)
    reason = np.full(n_obs, "accepted", dtype="<U32")
    sampled = {name: np.full(n_obs, np.nan) for name in fields}

    model_ns = mod_time.astype(np.int64)
    for row in range(n_obs):
        if not np.isfinite(obs_alt[row]):
            reason[row] = "nonfinite_observation_altitude"
            continue
        time_index = int(np.argmin(np.abs(model_ns - obs_time[row].astype(np.int64))))
        time_delta = (
            model_ns[time_index] - obs_time[row].astype(np.int64)
        ) / 1.0e9
        dt[row] = time_delta
        if abs(time_delta) > maximum_time_offset_seconds:
            reason[row] = "time_offset_exceeds_limit"
            continue

        lat_index = int(np.argmin(np.abs(mod_lat - obs_lat[row])))
        lon_deltas = cyclic_longitude_delta_degrees(mod_lon, obs_lon[row])
        lon_index = int(np.argmin(np.abs(lon_deltas)))
        surface = (
            phis[lat_index, lon_index]
            if phis.ndim == 2
            else phis[time_index, lat_index, lon_index]
        )
        centres = geometric_layer_centres_m(
            bxheight[time_index, :, lat_index, lon_index], surface
        )
        level_index = int(np.argmin(np.abs(centres - obs_alt[row])))
        altitude_delta = centres[level_index] - obs_alt[row]

        ti[row] = time_index
        yi[row] = lat_index
        xi[row] = lon_index
        ki[row] = level_index
        dlat[row] = mod_lat[lat_index] - obs_lat[row]
        dlon[row] = lon_deltas[lon_index]
        dz[row] = altitude_delta
        centre_alt[row] = centres[level_index]
        if abs(altitude_delta) > maximum_vertical_offset_m:
            reason[row] = "vertical_offset_exceeds_limit"
            continue
        for name, field in fields.items():
            sampled[name][row] = field[
                time_index, level_index, lat_index, lon_index
            ]

    valid = reason == "accepted"
    return MatchResult(
        valid=valid,
        rejection_reason=reason,
        model_time_index=ti,
        model_level_index=ki,
        model_lat_index=yi,
        model_lon_index=xi,
        time_offset_seconds=dt,
        latitude_offset_degrees=dlat,
        longitude_offset_degrees=dlon,
        altitude_offset_m=dz,
        model_layer_centre_altitude_m=centre_alt,
        sampled_fields=sampled,
    )


def convert_matched_absorption_to_aop_reference(
    ambient_absorption_mm1: ArrayLike,
    sampled_pressure_hpa: ArrayLike,
    sampled_temperature_k: ArrayLike,
    *,
    aop_reference_pressure_hpa: float,
    aop_reference_temperature_k: float,
) -> NDArray[np.float64]:
    """Convert matched values only with explicitly supplied AOP constants."""

    return convert_ambient_to_reference_volume(
        ambient_absorption_mm1,
        sampled_pressure_hpa,
        sampled_temperature_k,
        reference_pressure_hpa=aop_reference_pressure_hpa,
        reference_temperature_k=aop_reference_temperature_k,
    )
