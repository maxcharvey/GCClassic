#!/usr/bin/env python3
"""Rebuild FIREX-AQ dry absorption on explicit R3 carrier intervals."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

import numpy as np

from fetch_firex_aq_sp2 import EXPECTED_FLIGHT_DATES
from prepare_firex_aq_bc_merge import (
    arrays_equal,
    output_encoding,
    read_icartt,
    sha256,
    source_times,
)


ABSORPTION_FIELDS = ("abs_dry_405", "abs_dry_532", "abs_dry_664")
BASELINE_PATTERN = (
    "FIREXAQ-mrg60-DC8-NC_merge_{date}_R3_with_AMS_SP2rebin-v1.nc"
)
OUTPUT_PATTERN = (
    "FIREXAQ-mrg60-DC8-NC_merge_{date}_R3_with_AMS_"
    "SP2rebin-v1_AOPrebin-v1.nc"
)
AOP_PATTERN = re.compile(
    r"firexaq-AOP-optical_DC8_(\d{8})_R2\.ict", flags=re.IGNORECASE
)
AOP_INVALID_SENTINELS = (-9999.0, -9999.99, -8888.0, -7777.0)


def valid_aop_measurement(values: np.ndarray) -> np.ndarray:
    valid = np.isfinite(values)
    for sentinel in AOP_INVALID_SENTINELS:
        valid &= ~np.isclose(values, sentinel, rtol=0.0, atol=1.0e-6)
    return valid


def aggregate_absorption(
    sample_time: np.ndarray,
    measurements: dict[str, np.ndarray],
    interval_bounds: np.ndarray,
) -> dict[str, dict[str, np.ndarray]]:
    """Average valid 1 Hz absorption independently in half-open intervals."""

    if interval_bounds.ndim != 2 or interval_bounds.shape[1] != 2:
        raise ValueError("interval_bounds must have shape (time, 2)")
    result = {}
    for name in ABSORPTION_FIELDS:
        values = np.asarray(measurements[name], dtype=np.float64)
        valid = valid_aop_measurement(values)
        means = np.full(interval_bounds.shape[0], np.nan, dtype=np.float32)
        counts = np.zeros(interval_bounds.shape[0], dtype=np.int16)
        for index, (start, stop) in enumerate(interval_bounds):
            use = (sample_time >= start) & (sample_time < stop) & valid
            counts[index] = int(np.count_nonzero(use))
            if counts[index]:
                means[index] = np.float32(np.mean(values[use]))
        result[name] = {"mean": means, "count": counts}
    return result


def aop_path_by_date(directory: Path) -> dict[str, Path]:
    result = {}
    for path in sorted(directory.glob("firexaq-AOP-optical_DC8_*_R2.ict")):
        match = AOP_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        date = match.group(1)
        if date in result:
            raise ValueError(f"{date}: multiple AOP R2 products")
        result[date] = path
    missing = sorted(set(EXPECTED_FLIGHT_DATES) - set(result))
    if missing:
        raise FileNotFoundError(f"missing direct AOP R2 products for {missing}")
    return result


def add_corrected_fields(
    dataset: xr.Dataset,
    aggregate: dict[str, dict[str, np.ndarray]],
    source: Path,
    source_hash: str,
) -> xr.Dataset:
    import xarray as xr

    corrected = dataset.copy(deep=True)
    for name in ABSORPTION_FIELDS:
        if corrected[name].dims != ("time",):
            raise ValueError(f"unexpected {name} dimensions: {corrected[name].dims}")
        wavelength = name.rsplit("_", 1)[1]
        corrected[name] = xr.DataArray(
            aggregate[name]["mean"],
            dims=("time",),
            attrs={
                "SourceVarName": name,
                "units": "Mm-1",
                "VariableType": "dataproduct1D",
                "ancillary_variables": (
                    f"AOP_RH_dry {name}_n_1Hz"
                ),
                "DataSource": "firexaq-AOP-optical direct PI product",
                "ACVSNC_standard_name": (
                    "AerOpt_Absorption_InSitu_"
                    + {"405": "blue", "532": "green", "664": "red"}[wavelength]
                    + "_RHd_PM2.5_STP"
                ),
                "comment": (
                    "Arithmetic mean of valid direct 1 Hz samples whose "
                    "Time_start falls within the half-open R3 time_bnds "
                    "interval. The R2 header labels STP but does not state "
                    "numeric reference temperature or pressure."
                ),
                "direct_source_filename": source.name,
                "direct_source_sha256": source_hash,
            },
        )
        corrected[f"{name}_n_1Hz"] = xr.DataArray(
            aggregate[name]["count"],
            dims=("time",),
            attrs={
                "units": "1",
                "long_name": f"Valid direct 1 Hz {name} samples in R3 interval",
                "valid_min": 0,
                "valid_max": 60,
            },
        )

    stamp = datetime.now(timezone.utc).isoformat()
    history = str(corrected.attrs.get("history", "")).strip()
    addition = (
        f"{stamp}: rebuilt AOP absorption from {source.name} by explicit "
        "overlap with R3 time_bnds"
    )
    corrected.attrs["history"] = f"{history}\n{addition}" if history else addition
    corrected.attrs["aop_merge_contract"] = (
        "firex-aq-aop-r2-r3-interval-rebin-v1"
    )
    corrected.attrs["aop_standard_volume_status"] = (
        "blocked: numeric AOP reference temperature and pressure absent"
    )
    return corrected


def prepare(baseline_dir: Path, aop_dir: Path, output_dir: Path) -> dict:
    import xarray as xr

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = aop_path_by_date(aop_dir)
    records = []
    for date in EXPECTED_FLIGHT_DATES:
        baseline = baseline_dir / BASELINE_PATTERN.format(date=date)
        source = sources[date]
        output = output_dir / OUTPUT_PATTERN.format(date=date)
        if not baseline.is_file():
            raise FileNotFoundError(baseline)
        if output.exists():
            raise FileExistsError(f"refusing to overwrite {output}")

        header, direct = read_icartt(source)
        required = {"Time_start", *ABSORPTION_FIELDS}
        missing = sorted(required - set(direct))
        if missing:
            raise ValueError(f"{source.name}: missing variables {missing}")
        source_hash = sha256(source)
        with xr.open_dataset(baseline) as opened:
            original = opened.load()
        bounds = np.asarray(original["time_bnds"].values).astype("datetime64[ns]")
        aggregate = aggregate_absorption(
            source_times(date, direct["Time_start"]),
            {name: direct[name] for name in ABSORPTION_FIELDS},
            bounds,
        )
        corrected = add_corrected_fields(
            original, aggregate, source, source_hash
        )

        protected = set(original.variables) - set(ABSORPTION_FIELDS)
        changed = [
            name for name in sorted(protected)
            if not arrays_equal(original[name].values, corrected[name].values)
        ]
        if changed:
            raise RuntimeError(f"{date}: protected values changed: {changed}")

        temporary = output.with_name(f".{output.name}.part")
        corrected.to_netcdf(
            temporary,
            engine="netcdf4",
            format="NETCDF4_CLASSIC",
            encoding=output_encoding(corrected),
        )
        os.replace(temporary, output)
        with xr.open_dataset(output) as opened:
            written = opened.load()
        changed_after_write = [
            name for name in sorted(protected)
            if not arrays_equal(original[name].values, written[name].values)
        ]
        if changed_after_write:
            raise RuntimeError(
                f"{date}: protected values changed after write: "
                f"{changed_after_write}"
            )
        records.append(
            {
                "date": date,
                "baseline_sha256": sha256(baseline),
                "direct_aop_sha256": source_hash,
                "output_sha256": sha256(output),
                "valid_intervals": {
                    name: int(np.count_nonzero(np.isfinite(written[name].values)))
                    for name in ABSORPTION_FIELDS
                },
                "valid_1hz_samples": {
                    name: int(aggregate[name]["count"].sum())
                    for name in ABSORPTION_FIELDS
                },
                "protected_variables_unchanged": True,
                "revision": next(
                    (line for line in header if line.startswith("REVISION:")),
                    None,
                ),
            }
        )
    return {
        "schema_version": 1,
        "contract": "firex-aq-aop-r2-r3-interval-rebin-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_dir": str(baseline_dir),
        "aop_dir": str(aop_dir),
        "output_dir": str(output_dir),
        "interval_rule": "target_start <= Time_start < target_stop",
        "measurement_rule": "independent arithmetic mean of valid 1 Hz values",
        "invalid_values": [-9999, -8888, -7777, "nonfinite"],
        "standard_volume_status": (
            "blocked pending authoritative numeric AOP reference temperature "
            "and pressure"
        ),
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--aop-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.baseline_dir, args.aop_dir, args.output_dir)
    path = args.output_dir / "firex_aq_aop_merge_manifest.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
