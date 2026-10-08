#!/usr/bin/env python3
"""Summarize corrected FIREX-AQ absorption as a function of plume age.

The command-line reader deliberately uses NCO's JSON output so that the
analysis can run on Argon without adding a Python NetCDF dependency.  The
numerical functions are independent of NCO and are covered by focused tests.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from plume_transport.dry_absorption_operator import (
    absorption_angstrom_exponent,
)


VARIABLES = (
    "time",
    "lat",
    "lon",
    "alt",
    "Smoke_flag",
    "smoke_age",
    "smoke_age_corr",
    "smoke_agemethod",
    "abs_dry_405",
    "abs_dry_532",
    "abs_dry_664",
    "BC_mass_90_550_nm",
    "BC_Dilution_Fraction",
    "BC_Dilution_Mixed_Flag",
    "OA_PM1_AMS_60s_JIMENEZ",
    "CO_DACOM",
)

# Fixed before looking at model skill.  The last interval is [8 h, infinity).
AGE_BIN_EDGES_HOURS = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, math.inf)
FLIGHT_PATTERN = re.compile(
    r"_(2019\d{4})_R3_with_AMS_SP2rebin-v1"
    r"(?:_AOPrebin-v1)?\.nc$"
)


class FirexPlumeAgeError(ValueError):
    """Raised when a FIREX plume-age input violates the analysis contract."""


def _array(values: ArrayLike) -> NDArray[np.float64]:
    """Convert JSON nulls and numeric values to a one-dimensional float array."""

    result = np.asarray(
        [np.nan if value is None else value for value in values],
        dtype=np.float64,
    )
    if result.ndim != 1:
        raise FirexPlumeAgeError("all plume-age variables must be one-dimensional")
    return result


def arrays_from_nco_json(payload: Mapping[str, Any]) -> dict[str, NDArray[np.float64]]:
    """Extract one-dimensional variable arrays from ``ncks --jsn`` output."""

    variables = payload.get("variables")
    if not isinstance(variables, Mapping):
        raise FirexPlumeAgeError("NCO JSON payload has no variables mapping")
    arrays: dict[str, NDArray[np.float64]] = {}
    for name in VARIABLES:
        entry = variables.get(name)
        if not isinstance(entry, Mapping) or "data" not in entry:
            raise FirexPlumeAgeError(f"NCO JSON payload is missing {name}")
        arrays[name] = _array(entry["data"])
    lengths = {array.size for array in arrays.values()}
    if len(lengths) != 1:
        raise FirexPlumeAgeError(
            f"FIREX variables do not share one time dimension: {sorted(lengths)}"
        )
    return arrays


def read_netcdf_with_nco(path: Path) -> dict[str, NDArray[np.float64]]:
    """Read the frozen variables from one corrected carrier using NCO JSON."""

    command = [
        "ncks",
        "--jsn",
        "--jsn_fmt",
        "2",
        "-C",
        "-v",
        ",".join(VARIABLES),
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise FirexPlumeAgeError("ncks is required to read FIREX NetCDF files") from exc
    except subprocess.CalledProcessError as exc:
        raise FirexPlumeAgeError(
            f"ncks failed for {path.name}: {exc.stderr.strip()}"
        ) from exc
    return arrays_from_nco_json(json.loads(completed.stdout))


def _finite_stats(values: NDArray[np.float64]) -> dict[str, float | int | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "min": None,
            "max": None,
        }
    return {
        "n": int(finite.size),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "p25": float(np.quantile(finite, 0.25)),
        "p75": float(np.quantile(finite, 0.75)),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
    }


def _bin_label(lower: float, upper: float) -> str:
    return f"{lower:g}-{upper:g}h" if math.isfinite(upper) else f"{lower:g}h+"


def summarize_arrays(
    arrays: Mapping[str, ArrayLike],
    *,
    flight_date: str,
) -> dict[str, Any]:
    """Return per-flight corrected-age summaries without dropping negatives.

    ``smoke_age_corr`` is the primary age coordinate.  Rows with only the
    general ``smoke_age`` field are counted but are not silently substituted
    into corrected-age bins.  Finite negative absorption is retained in band
    summaries; AAE is defined only where both endpoint absorptions are
    strictly positive.
    """

    values = {name: _array(arrays[name]) for name in VARIABLES}
    lengths = {value.size for value in values.values()}
    if len(lengths) != 1:
        raise FirexPlumeAgeError("FIREX variables must have equal lengths")

    general_age = values["smoke_age"]
    corrected_age = values["smoke_age_corr"]
    in_smoke = values["Smoke_flag"] == 1.0
    valid_general = in_smoke & np.isfinite(general_age) & (general_age >= 0.0)
    valid_corrected = in_smoke & np.isfinite(corrected_age) & (corrected_age >= 0.0)
    collocated = in_smoke.copy()
    for name in (
        "lat",
        "lon",
        "alt",
        "abs_dry_405",
        "abs_dry_532",
        "abs_dry_664",
        "BC_mass_90_550_nm",
    ):
        collocated &= np.isfinite(values[name])
    eligible_general = valid_general & collocated
    eligible_corrected = valid_corrected & collocated

    aae = np.full(corrected_age.shape, np.nan, dtype=np.float64)
    a405 = values["abs_dry_405"]
    a664 = values["abs_dry_664"]
    positive = np.isfinite(a405) & np.isfinite(a664) & (a405 > 0.0) & (a664 > 0.0)
    if np.any(positive):
        aae[positive] = absorption_angstrom_exponent(
            a405[positive],
            a664[positive],
            short_wavelength_nm=405.0,
            long_wavelength_nm=664.0,
        )

    metrics = {
        "abs_dry_405_Mm-1": a405,
        "abs_dry_532_Mm-1": values["abs_dry_532"],
        "abs_dry_664_Mm-1": a664,
        "AAE_405_664": aae,
        "BC_mass_90_550_nm": values["BC_mass_90_550_nm"],
        "OA_PM1_AMS_60s_JIMENEZ": values["OA_PM1_AMS_60s_JIMENEZ"],
        "CO_DACOM": values["CO_DACOM"],
    }

    bins: list[dict[str, Any]] = []
    for lower, upper in zip(AGE_BIN_EDGES_HOURS[:-1], AGE_BIN_EDGES_HOURS[1:]):
        lower_s = lower * 3600.0
        upper_s = upper * 3600.0
        mask = eligible_corrected & (corrected_age >= lower_s)
        if math.isfinite(upper):
            mask &= corrected_age < upper_s
        bins.append(
            {
                "label": _bin_label(lower, upper),
                "lower_hours": lower,
                "upper_hours": upper if math.isfinite(upper) else None,
                "rows": int(np.count_nonzero(mask)),
                "age_hours": _finite_stats(corrected_age[mask] / 3600.0),
                "metrics": {
                    name: _finite_stats(metric[mask])
                    for name, metric in metrics.items()
                },
            }
        )

    return {
        "flight_date": flight_date,
        "rows": int(corrected_age.size),
        "in_smoke_rows": int(np.count_nonzero(in_smoke)),
        "general_age_rows": int(np.count_nonzero(valid_general)),
        "corrected_age_rows": int(np.count_nonzero(valid_corrected)),
        "general_only_age_rows": int(np.count_nonzero(valid_general & ~valid_corrected)),
        "fully_collocated_general_age_rows": int(
            np.count_nonzero(eligible_general)
        ),
        "fully_collocated_corrected_age_rows": int(
            np.count_nonzero(eligible_corrected)
        ),
        "finite_negative_absorption_rows": {
            name: int(np.count_nonzero(np.isfinite(metric) & (metric < 0.0)))
            for name, metric in metrics.items()
            if name.startswith("abs_dry_")
        },
        "aae_qualified_rows": int(
            np.count_nonzero(np.isfinite(aae) & eligible_corrected)
        ),
        "age_bins": bins,
    }


def summarize_directory(
    data_dir: Path,
    *,
    allow_legacy_optical: bool = False,
) -> dict[str, Any]:
    files = sorted(data_dir.glob("*_R3_with_AMS_SP2rebin-v1*.nc"))
    if len(files) != 23:
        raise FirexPlumeAgeError(
            f"expected 23 corrected FIREX carriers, found {len(files)}"
        )
    legacy = [path.name for path in files if "_AOPrebin-v1.nc" not in path.name]
    if legacy and not allow_legacy_optical:
        raise FirexPlumeAgeError(
            "refusing legacy R3 optical columns; use the direct AOP-rebinned "
            f"carrier ({len(legacy)} legacy files found)"
        )
    flights = []
    campaign_arrays: dict[str, list[NDArray[np.float64]]] = {
        name: [] for name in VARIABLES
    }
    for path in files:
        match = FLIGHT_PATTERN.search(path.name)
        if match is None:
            raise FirexPlumeAgeError(f"unexpected corrected filename: {path.name}")
        arrays = read_netcdf_with_nco(path)
        for name, values in arrays.items():
            campaign_arrays[name].append(values)
        flights.append(summarize_arrays(arrays, flight_date=match.group(1)))
    campaign_summary = summarize_arrays(
        {
            name: np.concatenate(chunks)
            for name, chunks in campaign_arrays.items()
        },
        flight_date="campaign",
    )
    return {
        "schema": "firex-aq-plume-age-summary-v1",
        "input_directory": str(data_dir.resolve()),
        "age_coordinate": "smoke_age_corr",
        "general_age_fallback": False,
        "negative_absorption_policy": "retain",
        "aae_policy": "strictly_positive_405_and_664_only",
        "collocation_contract": [
            "Smoke_flag == 1",
            "finite nonnegative selected age",
            "finite latitude, longitude, and altitude",
            "finite absorption at 405, 532, and 664 nm",
            "finite interval-corrected BC_mass_90_550_nm",
        ],
        "age_bin_edges_hours": [
            edge if math.isfinite(edge) else None for edge in AGE_BIN_EDGES_HOURS
        ],
        "flights": flights,
        "campaign_summary": campaign_summary,
        "campaign_counts": {
            "rows": sum(flight["rows"] for flight in flights),
            "in_smoke_rows": sum(flight["in_smoke_rows"] for flight in flights),
            "general_age_rows": sum(flight["general_age_rows"] for flight in flights),
            "corrected_age_rows": sum(
                flight["corrected_age_rows"] for flight in flights
            ),
            "general_only_age_rows": sum(
                flight["general_only_age_rows"] for flight in flights
            ),
            "fully_collocated_general_age_rows": sum(
                flight["fully_collocated_general_age_rows"] for flight in flights
            ),
            "fully_collocated_corrected_age_rows": sum(
                flight["fully_collocated_corrected_age_rows"] for flight in flights
            ),
            "aae_qualified_rows": sum(
                flight["aae_qualified_rows"] for flight in flights
            ),
        },
    }


def write_csv(summary: Mapping[str, Any], path: Path) -> None:
    metric_names = (
        "abs_dry_405_Mm-1",
        "abs_dry_532_Mm-1",
        "abs_dry_664_Mm-1",
        "AAE_405_664",
        "BC_mass_90_550_nm",
        "OA_PM1_AMS_60s_JIMENEZ",
        "CO_DACOM",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["flight_date", "age_bin", "rows"]
        for name in metric_names:
            fieldnames.extend((f"{name}_n", f"{name}_median", f"{name}_p25", f"{name}_p75"))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for flight in [summary["campaign_summary"], *summary["flights"]]:
            for age_bin in flight["age_bins"]:
                row: dict[str, Any] = {
                    "flight_date": flight["flight_date"],
                    "age_bin": age_bin["label"],
                    "rows": age_bin["rows"],
                }
                for name in metric_names:
                    stats = age_bin["metrics"][name]
                    for statistic in ("n", "median", "p25", "p75"):
                        row[f"{name}_{statistic}"] = stats[statistic]
                writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument(
        "--allow-legacy-optical",
        action="store_true",
        help="diagnostic only: permit known-bad original R3 optical columns",
    )
    args = parser.parse_args()

    summary = summarize_directory(
        args.data_dir,
        allow_legacy_optical=args.allow_legacy_optical,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(summary, args.output_csv)


if __name__ == "__main__":
    main()
