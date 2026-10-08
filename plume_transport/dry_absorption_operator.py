#!/usr/bin/env python3
"""Pure numerical oracle for the Stage-1 dry absorption diagnostic.

This module does not read model or observation files and does not choose
optical properties.  It only defines the reviewed arithmetic that a future
GEOS-Chem diagnostic must reproduce:

* derive dry absorption optical depth from dry extinction and dry SSA;
* convert layer optical depth to an ambient-volume coefficient in Mm-1;
* interpolate absorption itself as a power law in wavelength; and
* optionally convert ambient-volume coefficients to an explicitly supplied
  reference temperature and pressure.

No standard temperature or pressure defaults are provided deliberately.  The
FIREX-AQ AOP R2 headers label fields as STP but do not define the numeric
reference state.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray


class DryAbsorptionContractError(ValueError):
    """Raised when input cannot satisfy the frozen output-only contract."""


def _finite_array(value: ArrayLike, name: str) -> NDArray[np.float64]:
    array = np.asarray(value, dtype=np.float64)
    if not np.all(np.isfinite(array)):
        raise DryAbsorptionContractError(f"{name} must be finite")
    return array


def dry_absorption_optical_depth(
    dry_extinction_optical_depth: ArrayLike,
    dry_single_scattering_albedo: ArrayLike,
) -> NDArray[np.float64]:
    """Return dry layer absorption optical depth.

    ``AAOD = AOD * (1 - SSA)`` is evaluated only for nonnegative extinction
    optical depth and SSA within [0, 1].
    """

    extinction = _finite_array(
        dry_extinction_optical_depth, "dry extinction optical depth"
    )
    ssa = _finite_array(
        dry_single_scattering_albedo, "dry single-scattering albedo"
    )
    extinction, ssa = np.broadcast_arrays(extinction, ssa)
    if np.any(extinction < 0.0):
        raise DryAbsorptionContractError(
            "dry extinction optical depth must be nonnegative"
        )
    if np.any((ssa < 0.0) | (ssa > 1.0)):
        raise DryAbsorptionContractError(
            "dry single-scattering albedo must be within [0, 1]"
        )
    return extinction * (1.0 - ssa)


def layer_absorption_coefficient_mm1(
    absorption_optical_depth: ArrayLike,
    box_height_m: ArrayLike,
) -> NDArray[np.float64]:
    """Convert dry layer absorption optical depth to ambient-volume Mm-1."""

    aaod = _finite_array(absorption_optical_depth, "absorption optical depth")
    height = _finite_array(box_height_m, "box height")
    aaod, height = np.broadcast_arrays(aaod, height)
    if np.any(aaod < 0.0):
        raise DryAbsorptionContractError(
            "absorption optical depth must be nonnegative"
        )
    if np.any(height <= 0.0):
        raise DryAbsorptionContractError("box height must be positive")
    return aaod / height * 1.0e6


def log_log_interpolate_absorption(
    target_wavelength_nm: float,
    lower_wavelength_nm: float,
    upper_wavelength_nm: float,
    lower_absorption: ArrayLike,
    upper_absorption: ArrayLike,
) -> NDArray[np.float64]:
    """Interpolate absorption with log(absorption) linear in log(wavelength).

    Exact LUT nodes are returned directly.  Two zero endpoints represent an
    absent component and return zero.  A mixed zero/positive bracket cannot
    define a logarithmic spectral slope and therefore fails closed.
    """

    wavelengths = _finite_array(
        [target_wavelength_nm, lower_wavelength_nm, upper_wavelength_nm],
        "wavelengths",
    )
    target, lower, upper = wavelengths
    if lower <= 0.0 or upper <= lower:
        raise DryAbsorptionContractError(
            "wavelength bracket must satisfy 0 < lower < upper"
        )
    if target < lower or target > upper:
        raise DryAbsorptionContractError(
            "target wavelength must lie within the LUT bracket"
        )

    lower_value = _finite_array(lower_absorption, "lower absorption")
    upper_value = _finite_array(upper_absorption, "upper absorption")
    lower_value, upper_value = np.broadcast_arrays(lower_value, upper_value)
    if np.any(lower_value < 0.0) or np.any(upper_value < 0.0):
        raise DryAbsorptionContractError(
            "absorption interpolation endpoints must be nonnegative"
        )
    if target == lower:
        return lower_value.copy()
    if target == upper:
        return upper_value.copy()

    both_zero = (lower_value == 0.0) & (upper_value == 0.0)
    mixed_zero = (lower_value == 0.0) ^ (upper_value == 0.0)
    if np.any(mixed_zero):
        raise DryAbsorptionContractError(
            "mixed zero/positive absorption endpoints cannot be log-interpolated"
        )

    result = np.zeros(lower_value.shape, dtype=np.float64)
    positive = ~both_zero
    weight = np.log(target / lower) / np.log(upper / lower)
    result[positive] = np.exp(
        np.log(lower_value[positive])
        + weight
        * (np.log(upper_value[positive]) - np.log(lower_value[positive]))
    )
    return result


def exact_band_dry_absorption_mm1(
    target_wavelength_nm: float,
    lower_wavelength_nm: float,
    upper_wavelength_nm: float,
    lower_dry_extinction_optical_depth: ArrayLike,
    upper_dry_extinction_optical_depth: ArrayLike,
    lower_dry_single_scattering_albedo: ArrayLike,
    upper_dry_single_scattering_albedo: ArrayLike,
    box_height_m: ArrayLike,
) -> NDArray[np.float64]:
    """Return exact-band dry ambient-volume absorption in Mm-1."""

    lower_aaod = dry_absorption_optical_depth(
        lower_dry_extinction_optical_depth,
        lower_dry_single_scattering_albedo,
    )
    upper_aaod = dry_absorption_optical_depth(
        upper_dry_extinction_optical_depth,
        upper_dry_single_scattering_albedo,
    )
    interpolated_aaod = log_log_interpolate_absorption(
        target_wavelength_nm,
        lower_wavelength_nm,
        upper_wavelength_nm,
        lower_aaod,
        upper_aaod,
    )
    return layer_absorption_coefficient_mm1(interpolated_aaod, box_height_m)


def convert_ambient_to_reference_volume(
    ambient_absorption_mm1: ArrayLike,
    ambient_pressure_hpa: ArrayLike,
    ambient_temperature_k: ArrayLike,
    reference_pressure_hpa: float,
    reference_temperature_k: float,
) -> NDArray[np.float64]:
    """Convert an ambient-volume coefficient to an explicit reference volume.

    For a fixed aerosol-to-air mixing ratio, the ideal-gas volume factor is
    ``(P_ref / T_ref) / (P_amb / T_amb)``.  This function is intentionally
    unusable without numeric reference pressure and temperature.
    """

    absorption = _finite_array(
        ambient_absorption_mm1, "ambient absorption coefficient"
    )
    pressure = _finite_array(ambient_pressure_hpa, "ambient pressure")
    temperature = _finite_array(ambient_temperature_k, "ambient temperature")
    reference = _finite_array(
        [reference_pressure_hpa, reference_temperature_k], "reference state"
    )
    reference_pressure, reference_temperature = reference
    absorption, pressure, temperature = np.broadcast_arrays(
        absorption, pressure, temperature
    )
    if np.any(absorption < 0.0):
        raise DryAbsorptionContractError(
            "model absorption coefficient must be nonnegative"
        )
    if np.any(pressure <= 0.0) or reference_pressure <= 0.0:
        raise DryAbsorptionContractError("pressure must be positive")
    if np.any(temperature <= 0.0) or reference_temperature <= 0.0:
        raise DryAbsorptionContractError("temperature must be positive")
    factor = (
        reference_pressure * temperature
        / (pressure * reference_temperature)
    )
    return absorption * factor


def component_total_mm1(
    components: Mapping[str, ArrayLike],
) -> NDArray[np.float64]:
    """Return the sum of finite, nonnegative labelled component fields."""

    if not components:
        raise DryAbsorptionContractError(
            "at least one labelled absorption component is required"
        )
    arrays: list[NDArray[np.float64]] = []
    for label, value in components.items():
        array = _finite_array(value, f"component {label}")
        if np.any(array < 0.0):
            raise DryAbsorptionContractError(
                f"component {label} must be nonnegative"
            )
        arrays.append(array)
    broadcast = np.broadcast_arrays(*arrays)
    return np.sum(np.stack(broadcast, axis=0), axis=0)


def assert_component_closure(
    total_absorption_mm1: ArrayLike,
    components: Mapping[str, ArrayLike],
    *,
    relative_tolerance: float = 1.0e-12,
    absolute_tolerance_mm1: float = 1.0e-12,
) -> None:
    """Raise unless a labelled total closes to its component sum."""

    total = _finite_array(total_absorption_mm1, "total absorption")
    component_sum = component_total_mm1(components)
    total, component_sum = np.broadcast_arrays(total, component_sum)
    if not np.allclose(
        total,
        component_sum,
        rtol=relative_tolerance,
        atol=absolute_tolerance_mm1,
    ):
        max_error = float(np.max(np.abs(total - component_sum)))
        raise DryAbsorptionContractError(
            "total/component absorption closure failed; "
            f"maximum absolute error is {max_error:.17g} Mm-1"
        )


def absorption_angstrom_exponent(
    short_absorption_mm1: ArrayLike,
    long_absorption_mm1: ArrayLike,
    *,
    short_wavelength_nm: float = 405.0,
    long_wavelength_nm: float = 664.0,
) -> NDArray[np.float64]:
    """Return AAE for already-QC-qualified positive absorption endpoints."""

    short = _finite_array(short_absorption_mm1, "shortwave absorption")
    long = _finite_array(long_absorption_mm1, "longwave absorption")
    wavelengths = _finite_array(
        [short_wavelength_nm, long_wavelength_nm], "AAE wavelengths"
    )
    short_wavelength, long_wavelength = wavelengths
    short, long = np.broadcast_arrays(short, long)
    if np.any(short <= 0.0) or np.any(long <= 0.0):
        raise DryAbsorptionContractError(
            "AAE requires strictly positive QC-qualified endpoints"
        )
    if short_wavelength <= 0.0 or long_wavelength <= short_wavelength:
        raise DryAbsorptionContractError(
            "AAE wavelengths must satisfy 0 < short < long"
        )
    return -np.log(short / long) / np.log(short_wavelength / long_wavelength)
