#!/usr/bin/env python3
"""Read-only validation of the corrected FIREX-AQ SP2/R3 merge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from fetch_firex_aq_sp2 import EXPECTED_FLIGHT_DATES
from prepare_firex_aq_bc_merge import (
    aggregate_sp2,
    arrays_equal,
    read_icartt,
    sha256,
    source_times,
)


REQUIRED_CORRECTION_FIELDS = {
    "BC_mass_90_550_nm",
    "BC_Dilution_Flag",
    "BC_Dilution_Fraction",
    "BC_Dilution_Mixed_Flag",
    "BC_mass_90_550_nm_n_1Hz",
    "BC_Dilution_Flag_n_1Hz",
}
REPLACED_FIELDS = {"BC_mass_90_550_nm", "BC_Dilution_Flag"}


def expected_decoded_binary(values: np.ndarray) -> np.ndarray:
    result = values.astype(np.float64)
    result[result == -127] = np.nan
    return result


def validate(
    merge_manifest_path: Path,
    source_manifest_path: Path,
    aq2_dir: Path | None,
) -> dict[str, Any]:
    merge_manifest = json.loads(merge_manifest_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    errors: list[str] = []
    records = []

    source_records = {
        item["date"]: item for item in source_manifest.get("files", [])
    }
    merge_records = {
        item["date"]: item for item in merge_manifest.get("files", [])
    }
    if sorted(source_records) != EXPECTED_FLIGHT_DATES:
        errors.append("source manifest does not contain the frozen 23 dates")
    if sorted(merge_records) != EXPECTED_FLIGHT_DATES:
        errors.append("merge manifest does not contain the frozen 23 dates")

    total_new_finite = 0
    total_mixed = 0
    aq2_differences: list[float] = []
    aq2_common = 0

    for date in EXPECTED_FLIGHT_DATES:
        if date not in source_records or date not in merge_records:
            continue
        source_record = source_records[date]
        merge_record = merge_records[date]
        source = Path(merge_record["direct_sp2"]["path"])
        baseline = Path(merge_record["baseline"]["path"])
        output = Path(merge_record["output"]["path"])
        file_errors: list[str] = []

        for path, expected_hash, label in [
            (source, source_record["sha256"], "direct SP2"),
            (baseline, merge_record["baseline"]["sha256"], "baseline"),
            (output, merge_record["output"]["sha256"], "output"),
        ]:
            if not path.is_file():
                file_errors.append(f"missing {label}: {path}")
            elif sha256(path) != expected_hash:
                file_errors.append(f"{label} SHA-256 mismatch: {path}")
        if file_errors:
            errors.extend(f"{date}: {error}" for error in file_errors)
            records.append({"date": date, "errors": file_errors})
            continue

        _, direct = read_icartt(source)
        with xr.open_dataset(baseline) as opened:
            original = opened.load()
        with xr.open_dataset(output) as opened:
            corrected = opened.load()
        bounds = np.asarray(original.time_bnds.values).astype("datetime64[ns]")
        expected = aggregate_sp2(
            source_times(date, direct["Time_Start"]),
            direct["BC_mass_90_550_nm"],
            direct["BC_Dilution_Flag"],
            bounds,
        )

        missing_fields = sorted(REQUIRED_CORRECTION_FIELDS - set(corrected))
        if missing_fields:
            file_errors.append(f"missing correction fields: {missing_fields}")
        protected = set(original.variables) - REPLACED_FIELDS
        changed = [
            name for name in sorted(protected)
            if not arrays_equal(original[name].values, corrected[name].values)
        ]
        if changed:
            file_errors.append(f"protected variables changed: {changed}")

        expected_fields = {
            "BC_mass_90_550_nm": expected["mass_mean"],
            "BC_Dilution_Flag": expected_decoded_binary(
                expected["dilution_binary"]
            ),
            "BC_Dilution_Fraction": expected["dilution_fraction"],
            "BC_Dilution_Mixed_Flag": expected["dilution_mixed"],
            "BC_mass_90_550_nm_n_1Hz": expected["sample_count"],
            "BC_Dilution_Flag_n_1Hz": expected["dilution_flag_count"],
        }
        for name, expected_values in expected_fields.items():
            if name in corrected and not arrays_equal(
                corrected[name].values, expected_values
            ):
                file_errors.append(f"{name} does not match direct reaggregation")

        if corrected.attrs.get("bc_merge_contract") != (
            "firex-aq-sp2-r3-interval-rebin-v1"
        ):
            file_errors.append("missing or incorrect bc_merge_contract")

        finite = int(np.isfinite(corrected.BC_mass_90_550_nm.values).sum())
        mixed = int(np.nansum(corrected.BC_Dilution_Mixed_Flag.values))
        total_new_finite += finite
        total_mixed += mixed

        if date == "20190722" and finite != 0:
            file_errors.append("20190722 must have no BC after documented laser failure")
        if date == "20190724" and finite == 0:
            file_errors.append("20190724 direct SP2 coverage was not restored")

        aq2_max_abs = None
        if aq2_dir is not None:
            matches = sorted(aq2_dir.glob(f"*{date}*.nc"))
            if len(matches) != 1:
                file_errors.append(
                    f"expected one FIREX-AQ2 crosscheck file, found {len(matches)}"
                )
            else:
                with xr.open_dataset(matches[0]) as opened:
                    aq2 = opened.load()
                aq2_expected = aggregate_sp2(
                    source_times(date, direct["Time_Start"]),
                    direct["BC_mass_90_550_nm"],
                    direct["BC_Dilution_Flag"],
                    np.asarray(aq2.time_bnds.values).astype("datetime64[ns]"),
                )["mass_mean"].astype(np.float64)
                aq2_actual = np.asarray(
                    aq2.BC_mass_90_550_nm_SCHWARZ.values,
                    dtype=np.float64,
                )
                if not np.array_equal(
                    np.isfinite(aq2_expected), np.isfinite(aq2_actual)
                ):
                    file_errors.append("FIREX-AQ2 finite BC mask crosscheck failed")
                common = np.isfinite(aq2_expected) & np.isfinite(aq2_actual)
                differences = np.abs(
                    aq2_expected[common] - aq2_actual[common]
                )
                aq2_common += int(common.sum())
                aq2_differences.extend(differences.tolist())
                if differences.size:
                    aq2_max_abs = float(differences.max())
                    if aq2_max_abs > 0.1:
                        file_errors.append(
                            f"FIREX-AQ2 arithmetic crosscheck max difference "
                            f"{aq2_max_abs} > 0.1 ng m-3"
                        )

        errors.extend(f"{date}: {error}" for error in file_errors)
        records.append({
            "date": date,
            "result": "pass" if not file_errors else "fail",
            "errors": file_errors,
            "rows": int(corrected.sizes["time"]),
            "finite_bc": finite,
            "mixed_dilution_intervals": mixed,
            "protected_variable_count": len(protected),
            "aq2_crosscheck_max_abs_ng_m3": aq2_max_abs,
        })

    aq2_array = np.asarray(aq2_differences, dtype=np.float64)
    return {
        "schema_version": 1,
        "validator": "firex-aq-sp2-r3-interval-rebin-v1",
        "result": "pass" if not errors else "fail",
        "errors": errors,
        "flight_count": len(records),
        "total_finite_bc_intervals": total_new_finite,
        "total_mixed_dilution_intervals": total_mixed,
        "aq2_crosscheck": {
            "common_finite_intervals": aq2_common,
            "max_abs_difference_ng_m3": (
                float(aq2_array.max()) if aq2_array.size else None
            ),
            "rmse_ng_m3": (
                float(np.sqrt(np.mean(aq2_array ** 2)))
                if aq2_array.size else None
            ),
            "note": (
                "Crosscheck uses FIREX-AQ2's shifted intervals only to verify "
                "direct-source averaging; FIREX-AQ2 is not the corrected carrier."
            ),
        },
        "files": records,
        "non_claims": [
            "This validates data integrity and interval aggregation only.",
            "It does not infer BC absorption from rBC mass.",
            "It does not grant optical-model scientific acceptance.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merge-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--aq2-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate(
        args.merge_manifest,
        args.source_manifest,
        args.aq2_dir,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
