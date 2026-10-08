#!/usr/bin/env python3
"""Reaggregate sealed FIREX-AQ Tier-F sources onto accepted Tier-E bounds."""

from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np

from firex_tier_f_phase2_join import (
    IcarttSource,
    JoinError,
    SourceRecord,
    exact_decimal,
    load_icartt_source,
    sha256_file,
    source_paths_and_hashes,
    verify_contract_and_roots,
)


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_CONTRACT = SCRIPT_PATH.with_name(
    "tier_f_resolution_reconciliation_contract_20190806_v1.json"
)
SOURCE_ACCOUNTING_NAME = "source_to_60s_bins.csv"
REAGGREGATED_NAME = "reaggregated_60s.csv"
RECONCILIATION_NAME = "reconciliation.json"
RUN_MANIFEST_NAME = "run_manifest.json"
ARTIFACT_MANIFEST_NAME = "ARTIFACT_MANIFEST.json"
SEAL_NAME = "RESOLUTION_RECONCILIATION_SEAL.json"
DETERMINISTIC_NAMES = (
    SOURCE_ACCOUNTING_NAME,
    REAGGREGATED_NAME,
    RECONCILIATION_NAME,
)
AOP_FIELDS = ("abs_dry_405", "abs_dry_532", "abs_dry_664")
TIER_E_FIELDS = (
    *AOP_FIELDS,
    *(f"{field}_n_1Hz" for field in AOP_FIELDS),
    "BC_mass_90_550_nm",
    "BC_mass_90_550_nm_n_1Hz",
    "BC_Dilution_Flag",
    "BC_Dilution_Fraction",
    "BC_Dilution_Mixed_Flag",
    "BC_Dilution_Flag_n_1Hz",
)


class ReconciliationError(RuntimeError):
    """Raised when the frozen resolution contract cannot be proved."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def checked_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise ReconciliationError(f"{label} is absent: {path}")
    observed = sha256_file(path)
    if observed != expected:
        raise ReconciliationError(
            f"{label} hash changed: expected {expected}, got {observed}"
        )


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected_scope = (
        "complete-direct-source-to-accepted-tier-e-60-second-"
        "reconciliation-only"
    )
    if value.get("scope") != expected_scope:
        raise ReconciliationError("resolution contract has the wrong scope")
    return value


def verify_phase2(contract: Mapping[str, Any]) -> tuple[Path, dict[str, Path]]:
    root = Path(str(contract["phase2_root"]))
    frozen = contract["frozen_hashes"]
    required = {
        "phase2 seal": (root / SEAL_NAME.replace(
            "RESOLUTION_RECONCILIATION", "PHASE2_JOIN"
        ), frozen["phase2_seal"]),
        "phase2 artifact manifest": (
            root / ARTIFACT_MANIFEST_NAME,
            frozen["phase2_artifact_manifest"],
        ),
        "phase2 source inventory": (
            root / "source_record_inventory.csv",
            frozen["phase2_source_inventory"],
        ),
        "phase2 links": (
            root / "carrier_source_links.csv",
            frozen["phase2_links"],
        ),
        "phase2 carrier join": (
            root / "carrier_join.csv",
            frozen["phase2_carrier_join"],
        ),
    }
    for label, (path, expected) in required.items():
        checked_hash(path, str(expected), label)
    seal = json.loads((root / "PHASE2_JOIN_SEAL.json").read_text())
    if (
        seal.get("status") != "SEALED-PASS"
        or seal.get("input_payloads_modified") is not False
        or seal.get("later_phases_released") is not False
    ):
        raise ReconciliationError("accepted Phase-2 seal is not valid")
    return root, {label: path for label, (path, _) in required.items()}


def load_direct_sources(
    contract: Mapping[str, Any],
) -> tuple[dict[str, IcarttSource], dict[str, Path]]:
    phase2_contract = Path(str(contract["phase2_contract"]))
    phase2_value = verify_contract_and_roots(phase2_contract)
    paths, hashes, _ = source_paths_and_hashes(phase2_value)
    frozen = contract["frozen_hashes"]
    if hashes["AOP"] != frozen["aop_payload"]:
        raise ReconciliationError("AOP hash differs between frozen contracts")
    if hashes["SP2"] != frozen["sp2_payload"]:
        raise ReconciliationError("SP2 hash differs between frozen contracts")
    sources = {
        "AOP": load_icartt_source(
            "AOP",
            paths["AOP"],
            expected_sha256=str(frozen["aop_payload"]),
            explicit_stop=False,
        ),
        "SP2": load_icartt_source(
            "SP2",
            paths["SP2"],
            expected_sha256=str(frozen["sp2_payload"]),
            explicit_stop=False,
        ),
    }
    return sources, paths


def load_linked_ids(path: Path) -> dict[str, set[str]]:
    result = {"AOP": set(), "SP2": set()}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            product = row["product"]
            if product in result:
                source_id = row["source_record_id"]
                if source_id in result[product]:
                    raise ReconciliationError(
                        f"{product} source record links more than once: {source_id}"
                    )
                result[product].add(source_id)
    return result


def verify_source_inventory(
    path: Path, sources: Mapping[str, IcarttSource]
) -> None:
    observed: dict[str, dict[str, Mapping[str, str]]] = {
        product: {} for product in sources
    }
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            product = row["product"]
            if product in observed:
                source_id = row["source_record_id"]
                if source_id in observed[product]:
                    raise ReconciliationError(
                        f"duplicate {product} source inventory ID {source_id}"
                    )
                observed[product][source_id] = row
    for product, source in sources.items():
        if len(observed[product]) != len(source.records):
            raise ReconciliationError(
                f"{product} source inventory count differs from payload"
            )
        for record in source.records:
            row = observed[product].get(record.source_id)
            if row is None:
                raise ReconciliationError(
                    f"{product} source inventory lacks {record.source_id}"
                )
            if (
                row["payload_sha256"] != source.payload_sha256
                or int(row["data_record_ordinal"]) != record.ordinal
                or row["time_start_raw"] != format(record.start, "f")
                or row["raw_record_sha256"] != record.raw_sha256
            ):
                raise ReconciliationError(
                    f"{product} source inventory mismatch for {record.source_id}"
                )


def _decode_attr(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def decode_bounds(raw: np.ndarray, units: str) -> np.ndarray:
    match = re.fullmatch(
        r"minutes since 2019-08-06 (\d{2}):(\d{2}):(\d{2})", units
    )
    if match is None:
        raise ReconciliationError(f"unsupported Tier-E bounds units {units!r}")
    if raw.ndim != 2 or raw.shape[1] != 2:
        raise ReconciliationError("Tier-E time_bnds must have shape (time, 2)")
    if not np.issubdtype(raw.dtype, np.integer):
        raise ReconciliationError("Tier-E time_bnds must be integral minutes")
    base = (
        int(match.group(1)) * 3600
        + int(match.group(2)) * 60
        + int(match.group(3))
    )
    bounds = base + raw.astype(np.int64) * 60
    if np.any(bounds[:, 1] - bounds[:, 0] != 60):
        raise ReconciliationError("Tier-E contains a non-60-second interval")
    if np.any(bounds[1:, 0] != bounds[:-1, 1]):
        raise ReconciliationError("Tier-E intervals are not contiguous")
    return bounds


def load_tier_e(
    contract: Mapping[str, Any],
) -> tuple[Path, np.ndarray, dict[str, np.ndarray]]:
    path = Path(str(contract["tier_e_netcdf"]))
    checked_hash(
        path, str(contract["frozen_hashes"]["tier_e_netcdf"]), "Tier-E NetCDF"
    )
    with h5py.File(path, "r") as handle:
        if "time_bnds" not in handle:
            raise ReconciliationError("Tier-E NetCDF lacks time_bnds")
        bound_data = np.asarray(handle["time_bnds"][:])
        units = _decode_attr(handle["time_bnds"].attrs.get("units", ""))
        bounds = decode_bounds(bound_data, units)
        fields = {}
        for name in TIER_E_FIELDS:
            if name not in handle:
                raise ReconciliationError(f"Tier-E NetCDF lacks {name}")
            values = np.asarray(handle[name][:])
            if values.shape != (len(bounds),):
                raise ReconciliationError(
                    f"Tier-E {name} shape is {values.shape}, not {(len(bounds),)}"
                )
            fields[name] = values
        aop_hash = _decode_attr(
            handle["abs_dry_405"].attrs.get("direct_source_sha256", "")
        )
        sp2_hash = _decode_attr(
            handle["BC_mass_90_550_nm"].attrs.get(
                "direct_source_sha256", ""
            )
        )
    if aop_hash != contract["frozen_hashes"]["aop_payload"]:
        raise ReconciliationError("Tier-E AOP source hash attribute changed")
    if sp2_hash != contract["frozen_hashes"]["sp2_payload"]:
        raise ReconciliationError("Tier-E SP2 source hash attribute changed")
    return path, bounds, fields


def bin_index(start: Decimal, bounds: np.ndarray) -> int | None:
    if start != start.to_integral_value():
        raise ReconciliationError(f"source Time_Start is fractional: {start}")
    value = int(start)
    starts = bounds[:, 0].tolist()
    index = bisect_right(starts, value) - 1
    if index < 0 or index >= len(bounds):
        return None
    if value >= int(bounds[index, 1]):
        return None
    return index


def classify_sources(
    sources: Mapping[str, IcarttSource],
    linked: Mapping[str, set[str]],
    bounds: np.ndarray,
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[list[SourceRecord]]],
    dict[str, dict[str, int]],
]:
    rows: list[dict[str, Any]] = []
    grouped = {
        product: [[] for _ in range(len(bounds))] for product in sources
    }
    counts = {
        product: {
            "tier_e_inside_linked": 0,
            "tier_e_inside_unlinked": 0,
            "tier_e_outside_linked": 0,
            "tier_e_outside_unlinked": 0,
        }
        for product in sources
    }
    for product, source in sorted(sources.items()):
        for record in source.records:
            index = bin_index(record.start, bounds)
            is_linked = record.source_id in linked[product]
            classification = (
                f"tier_e_{'inside' if index is not None else 'outside'}_"
                f"{'linked' if is_linked else 'unlinked'}"
            )
            counts[product][classification] += 1
            if index is not None:
                grouped[product][index].append(record)
            rows.append(
                {
                    "product": product,
                    "source_record_id": record.source_id,
                    "source_ordinal": record.ordinal,
                    "source_time_start": format(record.start, "f"),
                    "linked_to_mrg01": is_linked,
                    "coverage_class": classification,
                    "tier_e_bin_index": "" if index is None else index,
                    "tier_e_bin_start": (
                        "" if index is None else int(bounds[index, 0])
                    ),
                    "tier_e_bin_stop": (
                        "" if index is None else int(bounds[index, 1])
                    ),
                }
            )
    return rows, grouped, counts


def is_valid_value(
    source: IcarttSource, record: SourceRecord, field: str
) -> bool:
    value = exact_decimal(record.values[field], f"{source.product} {field}")
    declared = source.missing_values.get(field)
    if declared is None:
        raise ReconciliationError(
            f"{source.product} lacks missing declaration for {field}"
        )
    missing = exact_decimal(
        declared, f"{source.product} declared missing {field}"
    )
    return value not in (missing, Decimal("-8888"), Decimal("-7777"))


def ordered_float32_mean(values: Sequence[float]) -> tuple[float, np.float32]:
    if not values:
        return math.nan, np.float32(np.nan)
    mean64 = float(np.mean(np.asarray(values, dtype=np.float64)))
    return mean64, np.float32(mean64)


def aggregate_aop(
    source: IcarttSource, grouped: Sequence[Sequence[SourceRecord]]
) -> list[dict[str, Any]]:
    result = []
    for records in grouped:
        item: dict[str, Any] = {"source_records": len(records)}
        for field in AOP_FIELDS:
            values = [
                float(record.values[field])
                for record in records
                if is_valid_value(source, record, field)
            ]
            mean64, mean32 = ordered_float32_mean(values)
            item[field] = {
                "valid_count": len(values),
                "mean64": mean64,
                "mean32": mean32,
            }
        result.append(item)
    return result


def aggregate_sp2(
    source: IcarttSource, grouped: Sequence[Sequence[SourceRecord]]
) -> list[dict[str, Any]]:
    result = []
    for records in grouped:
        mass_records = [
            record
            for record in records
            if is_valid_value(source, record, "BC_mass_90_550_nm")
        ]
        flagged = [
            record
            for record in mass_records
            if is_valid_value(source, record, "BC_Dilution_Flag")
            and exact_decimal(
                record.values["BC_Dilution_Flag"], "SP2 dilution flag"
            )
            in (Decimal(0), Decimal(1))
        ]
        mass64, mass32 = ordered_float32_mean(
            [float(record.values["BC_mass_90_550_nm"]) for record in mass_records]
        )
        undiluted = sum(
            exact_decimal(record.values["BC_Dilution_Flag"], "SP2 flag")
            == Decimal(0)
            for record in flagged
        )
        diluted = len(flagged) - undiluted
        if flagged:
            fraction64 = diluted / len(flagged)
            fraction32 = np.float32(fraction64)
            if diluted == 0:
                state, binary, mixed = "undiluted", 0, 0
            elif undiluted == 0:
                state, binary, mixed = "diluted", 1, 0
            else:
                state, binary, mixed = "mixed", -127, 1
        else:
            fraction64 = math.nan
            fraction32 = np.float32(np.nan)
            state, binary, mixed = "missing", -127, 0
        result.append(
            {
                "source_records": len(records),
                "valid_mass_count": len(mass_records),
                "valid_flag_count": len(flagged),
                "n_undiluted": undiluted,
                "n_diluted": diluted,
                "mass_mean64": mass64,
                "mass_mean32": mass32,
                "dilution_fraction64": fraction64,
                "dilution_fraction32": fraction32,
                "dilution_state": state,
                "dilution_binary": binary,
                "dilution_mixed": mixed,
            }
        )
    return result


def float32_bits(value: Any) -> int:
    return int(np.asarray(np.float32(value)).view(np.uint32))


def float32_equal(left: Any, right: Any) -> bool:
    left32 = np.float32(left)
    right32 = np.float32(right)
    if np.isnan(left32) or np.isnan(right32):
        return bool(np.isnan(left32) and np.isnan(right32))
    return float32_bits(left32) == float32_bits(right32)


def float32_ulp_distance(left: Any, right: Any) -> int | None:
    left32 = np.float32(left)
    right32 = np.float32(right)
    if np.isnan(left32) or np.isnan(right32):
        return 0 if np.isnan(left32) and np.isnan(right32) else None

    def ordered(value: np.float32) -> int:
        bits = float32_bits(value)
        return (0xFFFFFFFF - bits) if bits & 0x80000000 else (bits + 0x80000000)

    return abs(ordered(left32) - ordered(right32))


def target_sp2_state(
    valid_flag_count: int, binary: int, mixed: int
) -> str:
    if valid_flag_count == 0:
        return "missing"
    if mixed == 1 and binary == -127:
        return "mixed"
    if mixed == 0 and binary == 0:
        return "undiluted"
    if mixed == 0 and binary == 1:
        return "diluted"
    return "invalid"


def _render_number(value: Any) -> str:
    number = float(value)
    if math.isnan(number):
        return "NaN"
    return format(number, ".17g")


def build_bin_rows(
    bounds: np.ndarray,
    tier_e: Mapping[str, np.ndarray],
    aop: Sequence[Mapping[str, Any]],
    sp2: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    aop_summary = {
        field: {
            "bins": len(bounds),
            "count_mismatches": 0,
            "value_mismatches": 0,
            "valid_records": 0,
            "valid_bins": 0,
            "max_abs_float64_residual": 0.0,
            "max_float32_ulp_distance": 0,
        }
        for field in AOP_FIELDS
    }
    sp2_summary = {
        "bins": len(bounds),
        "mass_count_mismatches": 0,
        "flag_count_mismatches": 0,
        "mass_value_mismatches": 0,
        "fraction_value_mismatches": 0,
        "state_mismatches": 0,
        "binary_mismatches": 0,
        "mixed_mismatches": 0,
        "valid_mass_records": 0,
        "valid_mass_bins": 0,
        "n_undiluted": 0,
        "n_diluted": 0,
        "mixed_bins": 0,
        "max_abs_mass_float64_residual": 0.0,
        "max_mass_float32_ulp_distance": 0,
        "max_abs_fraction_float64_residual": 0.0,
        "max_fraction_float32_ulp_distance": 0,
    }
    for index, (start, stop) in enumerate(bounds):
        row: dict[str, Any] = {
            "tier_e_bin_index": index,
            "tier_e_bin_start": int(start),
            "tier_e_bin_stop": int(stop),
            "aop_source_records": aop[index]["source_records"],
            "sp2_source_records": sp2[index]["source_records"],
        }
        for field in AOP_FIELDS:
            calculated = aop[index][field]
            target_value = np.float32(tier_e[field][index])
            target_count = int(tier_e[f"{field}_n_1Hz"][index])
            count_equal = calculated["valid_count"] == target_count
            value_equal = float32_equal(calculated["mean32"], target_value)
            residual = (
                calculated["mean64"] - float(target_value)
                if math.isfinite(calculated["mean64"])
                and math.isfinite(float(target_value))
                else math.nan
            )
            ulp = float32_ulp_distance(calculated["mean32"], target_value)
            prefix = field
            row.update(
                {
                    f"{prefix}_valid_count": calculated["valid_count"],
                    f"{prefix}_tier_e_count": target_count,
                    f"{prefix}_count_equal": count_equal,
                    f"{prefix}_mean64": _render_number(calculated["mean64"]),
                    f"{prefix}_reaggregated_float32": _render_number(
                        calculated["mean32"]
                    ),
                    f"{prefix}_tier_e_float32": _render_number(target_value),
                    f"{prefix}_float32_equal": value_equal,
                    f"{prefix}_float64_residual": _render_number(residual),
                    f"{prefix}_float32_ulp_distance": (
                        "" if ulp is None else ulp
                    ),
                }
            )
            summary = aop_summary[field]
            summary["valid_records"] += calculated["valid_count"]
            summary["valid_bins"] += int(calculated["valid_count"] > 0)
            summary["count_mismatches"] += int(not count_equal)
            summary["value_mismatches"] += int(not value_equal)
            if math.isfinite(residual):
                summary["max_abs_float64_residual"] = max(
                    summary["max_abs_float64_residual"], abs(residual)
                )
            if ulp is not None:
                summary["max_float32_ulp_distance"] = max(
                    summary["max_float32_ulp_distance"], ulp
                )

        calculated_sp2 = sp2[index]
        target_mass = np.float32(tier_e["BC_mass_90_550_nm"][index])
        target_mass_count = int(
            tier_e["BC_mass_90_550_nm_n_1Hz"][index]
        )
        target_flag_count = int(
            tier_e["BC_Dilution_Flag_n_1Hz"][index]
        )
        target_binary = int(tier_e["BC_Dilution_Flag"][index])
        target_fraction = np.float32(
            tier_e["BC_Dilution_Fraction"][index]
        )
        target_mixed = int(tier_e["BC_Dilution_Mixed_Flag"][index])
        target_state = target_sp2_state(
            target_flag_count, target_binary, target_mixed
        )
        mass_count_equal = (
            calculated_sp2["valid_mass_count"] == target_mass_count
        )
        flag_count_equal = (
            calculated_sp2["valid_flag_count"] == target_flag_count
        )
        mass_equal = float32_equal(
            calculated_sp2["mass_mean32"], target_mass
        )
        fraction_equal = float32_equal(
            calculated_sp2["dilution_fraction32"], target_fraction
        )
        state_equal = calculated_sp2["dilution_state"] == target_state
        binary_equal = calculated_sp2["dilution_binary"] == target_binary
        mixed_equal = calculated_sp2["dilution_mixed"] == target_mixed
        mass_residual = (
            calculated_sp2["mass_mean64"] - float(target_mass)
            if math.isfinite(calculated_sp2["mass_mean64"])
            and math.isfinite(float(target_mass))
            else math.nan
        )
        fraction_residual = (
            calculated_sp2["dilution_fraction64"] - float(target_fraction)
            if math.isfinite(calculated_sp2["dilution_fraction64"])
            and math.isfinite(float(target_fraction))
            else math.nan
        )
        mass_ulp = float32_ulp_distance(
            calculated_sp2["mass_mean32"], target_mass
        )
        fraction_ulp = float32_ulp_distance(
            calculated_sp2["dilution_fraction32"], target_fraction
        )
        row.update(
            {
                "sp2_valid_mass_count": calculated_sp2["valid_mass_count"],
                "sp2_tier_e_mass_count": target_mass_count,
                "sp2_mass_count_equal": mass_count_equal,
                "sp2_valid_flag_count": calculated_sp2["valid_flag_count"],
                "sp2_tier_e_flag_count": target_flag_count,
                "sp2_flag_count_equal": flag_count_equal,
                "sp2_n_undiluted": calculated_sp2["n_undiluted"],
                "sp2_n_diluted": calculated_sp2["n_diluted"],
                "sp2_mass_mean64": _render_number(
                    calculated_sp2["mass_mean64"]
                ),
                "sp2_reaggregated_mass_float32": _render_number(
                    calculated_sp2["mass_mean32"]
                ),
                "sp2_tier_e_mass_float32": _render_number(target_mass),
                "sp2_mass_float32_equal": mass_equal,
                "sp2_mass_float64_residual": _render_number(mass_residual),
                "sp2_mass_float32_ulp_distance": (
                    "" if mass_ulp is None else mass_ulp
                ),
                "sp2_dilution_fraction64": _render_number(
                    calculated_sp2["dilution_fraction64"]
                ),
                "sp2_reaggregated_fraction_float32": _render_number(
                    calculated_sp2["dilution_fraction32"]
                ),
                "sp2_tier_e_fraction_float32": _render_number(target_fraction),
                "sp2_fraction_float32_equal": fraction_equal,
                "sp2_fraction_float64_residual": _render_number(
                    fraction_residual
                ),
                "sp2_fraction_float32_ulp_distance": (
                    "" if fraction_ulp is None else fraction_ulp
                ),
                "sp2_dilution_state": calculated_sp2["dilution_state"],
                "sp2_tier_e_dilution_state": target_state,
                "sp2_state_equal": state_equal,
                "sp2_dilution_binary": calculated_sp2["dilution_binary"],
                "sp2_tier_e_dilution_binary": target_binary,
                "sp2_binary_equal": binary_equal,
                "sp2_dilution_mixed": calculated_sp2["dilution_mixed"],
                "sp2_tier_e_dilution_mixed": target_mixed,
                "sp2_mixed_equal": mixed_equal,
            }
        )
        rows.append(row)
        sp2_summary["valid_mass_records"] += calculated_sp2["valid_mass_count"]
        sp2_summary["valid_mass_bins"] += int(
            calculated_sp2["valid_mass_count"] > 0
        )
        sp2_summary["n_undiluted"] += calculated_sp2["n_undiluted"]
        sp2_summary["n_diluted"] += calculated_sp2["n_diluted"]
        sp2_summary["mixed_bins"] += int(
            calculated_sp2["dilution_state"] == "mixed"
        )
        sp2_summary["mass_count_mismatches"] += int(not mass_count_equal)
        sp2_summary["flag_count_mismatches"] += int(not flag_count_equal)
        sp2_summary["mass_value_mismatches"] += int(not mass_equal)
        sp2_summary["fraction_value_mismatches"] += int(not fraction_equal)
        sp2_summary["state_mismatches"] += int(not state_equal)
        sp2_summary["binary_mismatches"] += int(not binary_equal)
        sp2_summary["mixed_mismatches"] += int(not mixed_equal)
        if math.isfinite(mass_residual):
            sp2_summary["max_abs_mass_float64_residual"] = max(
                sp2_summary["max_abs_mass_float64_residual"],
                abs(mass_residual),
            )
        if mass_ulp is not None:
            sp2_summary["max_mass_float32_ulp_distance"] = max(
                sp2_summary["max_mass_float32_ulp_distance"], mass_ulp
            )
        if math.isfinite(fraction_residual):
            sp2_summary["max_abs_fraction_float64_residual"] = max(
                sp2_summary["max_abs_fraction_float64_residual"],
                abs(fraction_residual),
            )
        if fraction_ulp is not None:
            sp2_summary["max_fraction_float32_ulp_distance"] = max(
                sp2_summary["max_fraction_float32_ulp_distance"],
                fraction_ulp,
            )
    return rows, {"AOP": aop_summary, "SP2": sp2_summary}


def validate_expected(
    contract: Mapping[str, Any],
    sources: Mapping[str, IcarttSource],
    bounds: np.ndarray,
    coverage: Mapping[str, Mapping[str, int]],
    summary: Mapping[str, Any],
) -> None:
    expected = contract["expected"]
    if len(bounds) != expected["tier_e_bins"]:
        raise ReconciliationError("Tier-E bin count differs from contract")
    for product in ("AOP", "SP2"):
        if len(sources[product].records) != expected["direct_records"][product]:
            raise ReconciliationError(f"{product} record count changed")
        if coverage[product] != expected["coverage_per_product"]:
            raise ReconciliationError(f"{product} coverage classes changed")
    for field, values in expected["aop"].items():
        observed = summary["AOP"][field]
        if (
            observed["valid_records"] != values["valid_records"]
            or observed["valid_bins"] != values["valid_bins"]
        ):
            raise ReconciliationError(f"{field} support count changed")
    sp2_expected = expected["sp2"]
    sp2_observed = summary["SP2"]
    for expected_key, observed_key in (
        ("valid_mass_records", "valid_mass_records"),
        ("valid_mass_bins", "valid_mass_bins"),
        ("n_undiluted", "n_undiluted"),
        ("n_diluted", "n_diluted"),
        ("mixed_bins", "mixed_bins"),
    ):
        if sp2_observed[observed_key] != sp2_expected[expected_key]:
            raise ReconciliationError(f"SP2 {observed_key} changed")


def comparison_pass(summary: Mapping[str, Any]) -> bool:
    for result in summary["AOP"].values():
        if result["count_mismatches"] or result["value_mismatches"]:
            return False
    return not any(
        summary["SP2"][name]
        for name in (
            "mass_count_mismatches",
            "flag_count_mismatches",
            "mass_value_mismatches",
            "fraction_value_mismatches",
            "state_mismatches",
            "binary_mismatches",
            "mixed_mismatches",
        )
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ReconciliationError(f"refusing to write empty CSV {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def artifact_inventory(output: Path, names: Iterable[str]) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": name,
            "bytes": (output / name).stat().st_size,
            "sha256": sha256_file(output / name),
        }
        for name in sorted(names)
    ]


def build(
    contract_path: Path, output_dir: Path, command: Sequence[str]
) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise ReconciliationError(f"refusing to overwrite {output_dir}")
    contract = load_contract(contract_path)
    phase2_root, phase2_files = verify_phase2(contract)
    sources, source_paths = load_direct_sources(contract)
    linked = load_linked_ids(phase2_root / "carrier_source_links.csv")
    verify_source_inventory(
        phase2_root / "source_record_inventory.csv", sources
    )
    tier_e_path, bounds, tier_e = load_tier_e(contract)
    accounting, grouped, coverage = classify_sources(
        sources, linked, bounds
    )
    aop = aggregate_aop(sources["AOP"], grouped["AOP"])
    sp2 = aggregate_sp2(sources["SP2"], grouped["SP2"])
    bin_rows, summary = build_bin_rows(bounds, tier_e, aop, sp2)
    validate_expected(contract, sources, bounds, coverage, summary)
    if not comparison_pass(summary):
        raise ReconciliationError(
            "complete-source reaggregation differs from accepted Tier E"
        )
    reconciliation = {
        "schema_version": 1,
        "id": contract["id"],
        "status": "PASS",
        "scope": contract["scope"],
        "tier_e_bins": len(bounds),
        "tier_e_domain_seconds": [
            int(bounds[0, 0]),
            int(bounds[-1, 1]),
        ],
        "mapping": contract["mapping"],
        "source_coverage": coverage,
        "comparison": contract["comparison"],
        "field_results": summary,
        "terminal_boundary_evidence": {
            "source_time_start": 92090,
            "tier_e_final_bin": [
                int(bounds[-1, 0]),
                int(bounds[-1, 1]),
            ],
            "mrg01_half_open_stop": 92090,
            "AOP_source_record_id": sources["AOP"].records[-1].source_id,
            "SP2_source_record_id": sources["SP2"].records[-1].source_id,
            "SP2_mass": sources["SP2"].records[-1].values[
                "BC_mass_90_550_nm"
            ],
            "SP2_dilution_flag": sources["SP2"].records[-1].values[
                "BC_Dilution_Flag"
            ],
            "classification": "tier_e_inside_unlinked",
            "used_in_complete_source_reaggregation": True,
            "carrier_domain_extended": False,
        },
        "input_payloads_modified": False,
        "tier_e_promoted": False,
        "stopped_before": contract["stops_before"],
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-", dir=output_dir.parent
        )
    )
    try:
        write_csv(staging / SOURCE_ACCOUNTING_NAME, accounting)
        write_csv(staging / REAGGREGATED_NAME, bin_rows)
        write_json(staging / RECONCILIATION_NAME, reconciliation)
        run_manifest = {
            "schema_version": 1,
            "id": contract["id"],
            "status": "PASS",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "command": list(command),
            "working_directory": str(Path.cwd()),
            "output_root": str(output_dir),
            "python": {
                "executable": sys.executable,
                "version": platform.python_version(),
                "numpy": np.__version__,
                "h5py": h5py.__version__,
                "required_argon_path_present": Path(
                    contract["python"]["required_argon_path"]
                ).exists(),
                "euler_exception": contract["python"]["exception_reason"],
            },
            "contract": {
                "path": str(contract_path),
                "sha256": sha256_file(contract_path),
            },
            "inputs": {
                "phase2_root": str(phase2_root),
                "phase2_files": {
                    label: {
                        "path": str(path),
                        "sha256": sha256_file(path),
                    }
                    for label, path in sorted(phase2_files.items())
                },
                "AOP": {
                    "path": str(source_paths["AOP"]),
                    "sha256": sources["AOP"].payload_sha256,
                },
                "SP2": {
                    "path": str(source_paths["SP2"]),
                    "sha256": sources["SP2"].payload_sha256,
                },
                "tier_e": {
                    "path": str(tier_e_path),
                    "sha256": sha256_file(tier_e_path),
                },
            },
            "stopped_before": contract["stops_before"],
        }
        write_json(staging / RUN_MANIFEST_NAME, run_manifest)
        artifacts = artifact_inventory(
            staging,
            (*DETERMINISTIC_NAMES, RUN_MANIFEST_NAME),
        )
        write_json(
            staging / ARTIFACT_MANIFEST_NAME,
            {
                "schema_version": 1,
                "status": "PASS",
                "artifacts": artifacts,
            },
        )
        manifest_hash = sha256_file(staging / ARTIFACT_MANIFEST_NAME)
        seal = {
            "schema_version": 1,
            "id": contract["id"],
            "status": "SEALED-PASS",
            "sealed_utc": datetime.now(timezone.utc).isoformat(),
            "artifact_manifest_sha256": manifest_hash,
            "reconciliation_sha256": sha256_file(
                staging / RECONCILIATION_NAME
            ),
            "input_payloads_modified": False,
            "tier_e_promoted": False,
            "later_phases_released": False,
        }
        write_json(staging / SEAL_NAME, seal)
        for label, expected, path in (
            ("AOP", contract["frozen_hashes"]["aop_payload"], source_paths["AOP"]),
            ("SP2", contract["frozen_hashes"]["sp2_payload"], source_paths["SP2"]),
            (
                "Tier-E NetCDF",
                contract["frozen_hashes"]["tier_e_netcdf"],
                tier_e_path,
            ),
            (
                "Phase-2 seal",
                contract["frozen_hashes"]["phase2_seal"],
                phase2_root / "PHASE2_JOIN_SEAL.json",
            ),
        ):
            checked_hash(path, str(expected), label)
        os.replace(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "SEALED-PASS",
        "output_root": str(output_dir),
        "bins": len(bounds),
        "source_records": len(accounting),
        "artifact_manifest_sha256": sha256_file(
            output_dir / ARTIFACT_MANIFEST_NAME
        ),
        "seal_sha256": sha256_file(output_dir / SEAL_NAME),
    }


def compare(primary: Path, reproduction: Path) -> dict[str, Any]:
    comparisons = []
    for name in DETERMINISTIC_NAMES:
        left = primary / name
        right = reproduction / name
        if not left.is_file() or not right.is_file():
            raise ReconciliationError(f"comparison artifact is absent: {name}")
        left_hash = sha256_file(left)
        right_hash = sha256_file(right)
        comparisons.append(
            {
                "relative_path": name,
                "primary_sha256": left_hash,
                "reproduction_sha256": right_hash,
                "identical": left_hash == right_hash,
            }
        )
    if not all(item["identical"] for item in comparisons):
        raise ReconciliationError("primary and reproduction differ")
    return {"status": "PASS", "comparisons": comparisons}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compare-primary", type=Path)
    parser.add_argument("--compare-reproduction", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    args = parser.parse_args(argv)
    comparison_mode = any(
        value is not None
        for value in (
            args.compare_primary,
            args.compare_reproduction,
            args.comparison_output,
        )
    )
    if comparison_mode:
        if not all(
            value is not None
            for value in (
                args.compare_primary,
                args.compare_reproduction,
                args.comparison_output,
            )
        ) or args.output_dir is not None:
            parser.error("comparison mode requires all three comparison options")
        report = compare(args.compare_primary, args.compare_reproduction)
        if args.comparison_output.exists():
            raise ReconciliationError(
                f"refusing to overwrite {args.comparison_output}"
            )
        write_json(args.comparison_output, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.output_dir is None:
        parser.error("--output-dir is required")
    result = build(args.contract, args.output_dir, sys.argv)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (JoinError, ReconciliationError, KeyError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
