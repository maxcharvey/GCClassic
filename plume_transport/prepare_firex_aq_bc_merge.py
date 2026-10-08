#!/usr/bin/env python3
"""Rebuild FIREX-AQ 60 s SP2 BC fields on the declared R3 intervals.

The input carrier is the pre-2026-04-27 ``withAMS`` backup, which preserves
the official R3 merge values and adds only the custom 60 s AMS field. The BC
mass and dilution metadata are rebuilt from the authoritative 1 Hz SP2 files
using each carrier row's explicit ``time_bnds``. No row-position joining is
permitted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import numpy as np

from fetch_firex_aq_sp2 import EXPECTED_FLIGHT_DATES


BASELINE_PATTERN = "FIREXAQ-mrg60-DC8-NC_merge_{date}_R3_with_AMS.nc"
OUTPUT_PATTERN = (
    "FIREXAQ-mrg60-DC8-NC_merge_{date}_R3_with_AMS_SP2rebin-v1.nc"
)
SP2_PATTERN = re.compile(
    r"FIREXAQ-SP2-BC-1HZ_DC8_(\d{8})_R\d+(?:_L\d+)?\.ict",
    flags=re.IGNORECASE,
)
INVALID_SENTINELS = (-9999.99, -8888.0, -7777.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_icartt(path: Path) -> tuple[list[str], dict[str, np.ndarray]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        first = handle.readline()
        try:
            header_count = int(first.split(",", 1)[0].strip())
        except (IndexError, ValueError) as exc:
            raise ValueError(f"{path.name}: invalid ICARTT header count") from exc
        header = [first.rstrip("\n")]
        for _ in range(header_count - 1):
            line = handle.readline()
            if not line:
                raise ValueError(f"{path.name}: truncated ICARTT header")
            header.append(line.rstrip("\n"))
        columns = [item.strip() for item in header[-1].split(",")]
        rows = np.genfromtxt(
            handle,
            delimiter=",",
            dtype=np.float64,
            ndmin=2,
            autostrip=True,
        )
    if rows.shape[1] != len(columns):
        raise ValueError(
            f"{path.name}: {rows.shape[1]} data columns != {len(columns)} names"
        )
    return header, {name: rows[:, index] for index, name in enumerate(columns)}


def valid_measurement(values: np.ndarray) -> np.ndarray:
    valid = np.isfinite(values)
    for sentinel in INVALID_SENTINELS:
        valid &= ~np.isclose(values, sentinel, rtol=0.0, atol=1.0e-6)
    return valid


def aggregate_sp2(
    sample_time: np.ndarray,
    bc_mass: np.ndarray,
    dilution_flag: np.ndarray,
    interval_bounds: np.ndarray,
) -> dict[str, np.ndarray]:
    """Aggregate 1 Hz SP2 samples into half-open target intervals."""

    if interval_bounds.ndim != 2 or interval_bounds.shape[1] != 2:
        raise ValueError("interval_bounds must have shape (time, 2)")
    count = np.zeros(interval_bounds.shape[0], dtype=np.int16)
    flag_count = np.zeros(interval_bounds.shape[0], dtype=np.int16)
    mass_mean = np.full(interval_bounds.shape[0], np.nan, dtype=np.float32)
    dilution_fraction = np.full(
        interval_bounds.shape[0], np.nan, dtype=np.float32
    )
    dilution_binary = np.full(interval_bounds.shape[0], -127, dtype=np.int8)
    dilution_mixed = np.zeros(interval_bounds.shape[0], dtype=np.int8)

    mass_valid = valid_measurement(bc_mass)
    flag_valid = (
        valid_measurement(dilution_flag)
        & np.isin(dilution_flag, [0.0, 1.0])
    )

    for index, (start, stop) in enumerate(interval_bounds):
        inside = (sample_time >= start) & (sample_time < stop)
        use_mass = inside & mass_valid
        use_flag = inside & mass_valid & flag_valid
        count[index] = int(use_mass.sum())
        flag_count[index] = int(use_flag.sum())
        if count[index]:
            mass_mean[index] = np.float32(np.mean(bc_mass[use_mass]))
        if flag_count[index]:
            fraction = float(np.mean(dilution_flag[use_flag]))
            dilution_fraction[index] = np.float32(fraction)
            if fraction == 0.0:
                dilution_binary[index] = 0
            elif fraction == 1.0:
                dilution_binary[index] = 1
            else:
                dilution_mixed[index] = 1

    return {
        "mass_mean": mass_mean,
        "sample_count": count,
        "dilution_flag_count": flag_count,
        "dilution_fraction": dilution_fraction,
        "dilution_binary": dilution_binary,
        "dilution_mixed": dilution_mixed,
    }


def sp2_path_by_date(sp2_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(sp2_dir.glob("FIREXAQ-SP2-BC-1HZ_DC8_*.ict")):
        match = SP2_PATTERN.fullmatch(path.name)
        if not match:
            continue
        date = match.group(1)
        if date in result:
            raise ValueError(f"{date}: multiple direct SP2 files in {sp2_dir}")
        result[date] = path
    missing = sorted(set(EXPECTED_FLIGHT_DATES) - set(result))
    if missing:
        raise FileNotFoundError(f"missing direct SP2 files for {missing}")
    return result


def source_times(date: str, seconds: np.ndarray) -> np.ndarray:
    base = np.datetime64(
        f"{date[:4]}-{date[4:6]}-{date[6:8]}T00:00:00", "ns"
    )
    offsets = np.rint(seconds * 1.0e9).astype("timedelta64[ns]")
    return base + offsets


def arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    left = np.asarray(left)
    right = np.asarray(right)
    if left.shape != right.shape:
        return False
    if left.dtype.kind in "fci" and right.dtype.kind in "fci":
        return np.array_equal(left, right, equal_nan=True)
    return np.array_equal(left, right)


def add_corrected_fields(
    dataset: xr.Dataset,
    aggregate: dict[str, np.ndarray],
    source_path: Path,
    source_hash: str,
) -> xr.Dataset:
    import xarray as xr

    corrected = dataset.copy(deep=True)
    dimension = corrected["BC_mass_90_550_nm"].dims
    if dimension != ("time",):
        raise ValueError(f"unexpected BC dimensions: {dimension}")

    corrected["BC_mass_90_550_nm"] = xr.DataArray(
        aggregate["mass_mean"],
        dims=dimension,
        attrs={
            "SourceVarName": "BC_mass_90_550_nm",
            "units": "ng.m-3",
            "VariableType": "dataproduct1D",
            "ancillary_variables": (
                "BC_Dilution_Flag BC_Dilution_Fraction "
                "BC_Dilution_Mixed_Flag BC_mass_90_550_nm_n_1Hz"
            ),
            "DataSource": "FIREXAQ-SP2-BC-1HZ direct PI product",
            "ACVSNC_standard_name": "AerComp_BC_InSitu_LII_Accu_MassSTP",
            "comment": (
                "Reported at 1013 mb and 273 K. Arithmetic mean of valid "
                "1 Hz samples whose Time_Start falls within the half-open "
                "R3 time_bnds interval."
            ),
            "long_name": "Accumulation-mode refractory black carbon mass",
            "direct_source_filename": source_path.name,
            "direct_source_sha256": source_hash,
        },
    )
    corrected["BC_Dilution_Flag"] = xr.DataArray(
        aggregate["dilution_binary"],
        dims=dimension,
        attrs={
            "units": "1",
            "VariableType": "InstrumentFlag",
            "DataSource": "FIREXAQ-SP2-BC-1HZ direct PI product",
            "flag_values": np.array([0, 1], dtype=np.int8),
            "flag_meanings": "bypassing_dilution_system dilution_applied",
            "comment": (
                "Defined only when every valid 1 Hz mass sample in the R3 "
                "interval has the same binary dilution state; -127 is fill."
            ),
        },
    )
    corrected["BC_Dilution_Fraction"] = xr.DataArray(
        aggregate["dilution_fraction"],
        dims=dimension,
        attrs={
            "units": "1",
            "long_name": "Fraction of valid 1 Hz BC samples using dilution",
            "valid_min": 0.0,
            "valid_max": 1.0,
        },
    )
    corrected["BC_Dilution_Mixed_Flag"] = xr.DataArray(
        aggregate["dilution_mixed"],
        dims=dimension,
        attrs={
            "units": "1",
            "flag_values": np.array([0, 1], dtype=np.int8),
            "flag_meanings": "single_or_missing_dilution_state mixed_dilution_state",
        },
    )
    corrected["BC_mass_90_550_nm_n_1Hz"] = xr.DataArray(
        aggregate["sample_count"],
        dims=dimension,
        attrs={
            "units": "1",
            "long_name": "Valid 1 Hz SP2 mass samples in the R3 interval",
            "valid_min": 0,
            "valid_max": 60,
        },
    )
    corrected["BC_Dilution_Flag_n_1Hz"] = xr.DataArray(
        aggregate["dilution_flag_count"],
        dims=dimension,
        attrs={
            "units": "1",
            "long_name": (
                "Valid joint SP2 mass and dilution-flag samples in the R3 interval"
            ),
            "valid_min": 0,
            "valid_max": 60,
        },
    )

    stamp = datetime.now(timezone.utc).isoformat()
    prior_history = str(corrected.attrs.get("history", "")).strip()
    correction_history = (
        f"{stamp}: rebuilt SP2 BC from {source_path.name} by explicit overlap "
        "with R3 time_bnds; no row-position join"
    )
    corrected.attrs["history"] = (
        f"{prior_history}\n{correction_history}"
        if prior_history else correction_history
    )
    corrected.attrs["bc_merge_contract"] = "firex-aq-sp2-r3-interval-rebin-v1"
    corrected.attrs["bc_merge_interval_rule"] = (
        "include 1 Hz Time_Start when target_start <= time < target_stop"
    )
    corrected.attrs["bc_merge_missing_rule"] = (
        "exclude -9999.99, -8888, -7777 and nonfinite mass values"
    )
    return corrected


def output_encoding(dataset: xr.Dataset) -> dict[str, dict[str, Any]]:
    encoding: dict[str, dict[str, Any]] = {}
    for name, variable in dataset.variables.items():
        if not variable.dims:
            continue
        item: dict[str, Any] = {"zlib": True, "complevel": 4, "shuffle": True}
        if name == "BC_Dilution_Flag":
            item["_FillValue"] = np.int8(-127)
        elif variable.dtype.kind == "f":
            item["_FillValue"] = np.nan
        encoding[name] = item
    return encoding


def compare_replaced(
    old_mass: np.ndarray,
    new_mass: np.ndarray,
) -> dict[str, Any]:
    old_mass = np.asarray(old_mass, dtype=np.float64)
    new_mass = np.asarray(new_mass, dtype=np.float64)
    common = np.isfinite(old_mass) & np.isfinite(new_mass)
    difference = old_mass[common] - new_mass[common]
    return {
        "old_finite": int(np.isfinite(old_mass).sum()),
        "new_finite": int(np.isfinite(new_mass).sum()),
        "common_finite": int(common.sum()),
        "old_only_finite": int((np.isfinite(old_mass) & ~np.isfinite(new_mass)).sum()),
        "new_only_finite": int((~np.isfinite(old_mass) & np.isfinite(new_mass)).sum()),
        "max_abs_difference_common": (
            float(np.max(np.abs(difference))) if difference.size else None
        ),
        "rmse_common": (
            float(np.sqrt(np.mean(difference ** 2))) if difference.size else None
        ),
    }


def prepare(
    baseline_dir: Path,
    sp2_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    import xarray as xr

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = sp2_path_by_date(sp2_dir)
    records = []

    for date in EXPECTED_FLIGHT_DATES:
        baseline = baseline_dir / BASELINE_PATTERN.format(date=date)
        if not baseline.is_file():
            raise FileNotFoundError(baseline)
        source = sources[date]
        output = output_dir / OUTPUT_PATTERN.format(date=date)
        if output.exists():
            raise FileExistsError(f"refusing to overwrite {output}")

        header, direct = read_icartt(source)
        required = {"Time_Start", "BC_mass_90_550_nm", "BC_Dilution_Flag"}
        missing = sorted(required - set(direct))
        if missing:
            raise ValueError(f"{source.name}: missing variables {missing}")
        source_hash = sha256(source)

        with xr.open_dataset(baseline) as opened:
            original = opened.load()
        bounds = np.asarray(original["time_bnds"].values).astype("datetime64[ns]")
        aggregate = aggregate_sp2(
            source_times(date, direct["Time_Start"]),
            direct["BC_mass_90_550_nm"],
            direct["BC_Dilution_Flag"],
            bounds,
        )
        corrected = add_corrected_fields(
            original, aggregate, source, source_hash
        )

        protected = set(original.variables) - {
            "BC_mass_90_550_nm", "BC_Dilution_Flag"
        }
        changed_protected = [
            name for name in sorted(protected)
            if not arrays_equal(original[name].values, corrected[name].values)
        ]
        if changed_protected:
            raise RuntimeError(
                f"{date}: protected variables changed before write: "
                f"{changed_protected}"
            )

        temporary = output.with_name(f".{output.name}.part")
        if temporary.exists():
            raise FileExistsError(f"stale temporary output exists: {temporary}")
        corrected.to_netcdf(
            temporary,
            engine="netcdf4",
            format="NETCDF4_CLASSIC",
            encoding=output_encoding(corrected),
        )
        os.replace(temporary, output)

        with xr.open_dataset(output) as reopened:
            written = reopened.load()
        changed_after_write = [
            name for name in sorted(protected)
            if not arrays_equal(original[name].values, written[name].values)
        ]
        if changed_after_write:
            raise RuntimeError(
                f"{date}: protected variables changed after write: "
                f"{changed_after_write}"
            )

        comparison = compare_replaced(
            original["BC_mass_90_550_nm"].values,
            written["BC_mass_90_550_nm"].values,
        )
        records.append({
            "date": date,
            "baseline": {
                "path": str(baseline),
                "bytes": baseline.stat().st_size,
                "sha256": sha256(baseline),
            },
            "direct_sp2": {
                "path": str(source),
                "bytes": source.stat().st_size,
                "sha256": source_hash,
                "revision": next(
                    (line for line in header if line.startswith("REVISION:")),
                    None,
                ),
            },
            "output": {
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": sha256(output),
            },
            "row_count": int(written.sizes["time"]),
            "valid_1hz_samples": int(aggregate["sample_count"].sum()),
            "mixed_dilution_intervals": int(
                aggregate["dilution_mixed"].sum()
            ),
            "protected_variables_unchanged": True,
            "bc_comparison_to_pre_correction": comparison,
        })

    return {
        "schema_version": 1,
        "contract": "firex-aq-sp2-r3-interval-rebin-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_dir": str(baseline_dir),
        "sp2_dir": str(sp2_dir),
        "output_dir": str(output_dir),
        "interval_rule": "target_start <= Time_Start < target_stop",
        "mass_rule": "arithmetic mean of valid 1 Hz BC mass",
        "binary_flag_rule": (
            "0 or 1 only for uniform valid intervals; fill for mixed/missing"
        ),
        "non_claims": [
            "No optical, OA, smoke-age, navigation, or meteorological values changed.",
            "No BC optical absorption was inferred from rBC mass.",
            "No model input or state was changed.",
        ],
        "files": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--sp2-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--report-name",
        default="firex_aq_bc_merge_manifest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = prepare(args.baseline_dir, args.sp2_dir, args.output_dir)
    report_path = args.output_dir / args.report_name
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
