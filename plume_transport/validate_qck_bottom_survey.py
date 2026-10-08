#!/usr/bin/env python3
"""Validate and summarize a runtime-gated QCK_BOTTOM survey ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "qck-bottom-survey-v1"
STATUSES = {"exact", "roundoff_feasible", "materially_unfillable", "invalid_donor"}
COLUMNS = (
    "schema_version",
    "run_id",
    "model_date",
    "model_time",
    "elapsed_seconds",
    "omp_thread_count",
    "species_index",
    "i_tpcore",
    "j_tpcore",
    "k_tpcore",
    "feasibility_status",
    "deficit_hpa",
    "full_column_available_hpa",
    "shortfall_hpa",
    "event_tolerance_hpa",
    "immediate_donor_hpa",
    "native_withdrawn_hpa",
    "native_mass_created_hpa",
    "deficit_kg",
    "full_column_available_kg",
    "shortfall_kg",
    "native_mass_created_kg",
    "area_m2",
    "behavior",
)
INTEGER_COLUMNS = {
    "model_date",
    "model_time",
    "elapsed_seconds",
    "omp_thread_count",
    "species_index",
    "i_tpcore",
    "j_tpcore",
    "k_tpcore",
}
FLOAT_COLUMNS = {
    "deficit_hpa",
    "full_column_available_hpa",
    "shortfall_hpa",
    "event_tolerance_hpa",
    "immediate_donor_hpa",
    "native_withdrawn_hpa",
    "native_mass_created_hpa",
    "deficit_kg",
    "full_column_available_kg",
    "shortfall_kg",
    "native_mass_created_kg",
    "area_m2",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def close(left: float, right: float, relative: float = 1.0e-10, absolute: float = 1.0e-30) -> bool:
    return abs(left - right) <= max(absolute, relative * max(abs(left), abs(right)))


def transported_species(config: Path) -> list[str]:
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    species = loaded["operations"]["transport"]["transported_species"]
    if not isinstance(species, list) or not species:
        raise ValueError("transported_species must be a non-empty list")
    return [str(value) for value in species]


def read_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: unexpected survey header")
        records: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, 2):
            parsed: dict[str, Any] = {}
            for key in COLUMNS:
                value = row[key]
                if value is None or value == "":
                    raise ValueError(f"row {row_number}: {key} is empty")
                if key in INTEGER_COLUMNS:
                    parsed[key] = int(value)
                elif key in FLOAT_COLUMNS:
                    parsed[key] = float(value)
                    if not math.isfinite(parsed[key]):
                        raise ValueError(f"row {row_number}: {key} is non-finite")
                else:
                    parsed[key] = value
            records.append(parsed)
    return records


def event_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["model_date"],
        record["model_time"],
        record["elapsed_seconds"],
        record["species_index"],
        record["i_tpcore"],
        record["j_tpcore"],
        record["k_tpcore"],
    )


def validate_records(records: list[dict[str, Any]], species: list[str]) -> dict[str, Any]:
    keys: set[tuple[Any, ...]] = set()
    by_species: dict[str, Counter[str]] = defaultdict(Counter)
    unfillable_by_species: dict[str, dict[str, float | int]] = {}
    unfillable_by_call: dict[tuple[int, int, int, int], float] = defaultdict(float)
    status_counts: Counter[str] = Counter()
    total_shortfall = 0.0
    maximum_shortfall = 0.0
    total_native_creation = 0.0
    maximum_native_creation = 0.0
    run_ids: set[str] = set()
    thread_counts: set[int] = set()

    for number, record in enumerate(records, 2):
        if record["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"row {number}: unexpected schema")
        if record["behavior"] != "native_immediate_donor_v1":
            raise ValueError(f"row {number}: unexpected behavior")
        status = record["feasibility_status"]
        if status not in STATUSES:
            raise ValueError(f"row {number}: unexpected status {status}")
        index = record["species_index"]
        if index < 1 or index > len(species):
            raise ValueError(f"row {number}: species index {index} is outside config")
        key = event_key(record)
        if key in keys:
            raise ValueError(f"row {number}: duplicate event key {key}")
        keys.add(key)

        deficit = record["deficit_hpa"]
        available = record["full_column_available_hpa"]
        tolerance = record["event_tolerance_hpa"]
        arithmetic_shortfall = max(deficit - available, 0.0)
        shortfall = record["shortfall_hpa"]
        if deficit <= 0.0 or available < 0.0 or tolerance < 0.0 or record["area_m2"] <= 0.0:
            raise ValueError(f"row {number}: invalid physical operand")
        expected_withdrawal = min(deficit, record["immediate_donor_hpa"])
        if not close(record["native_withdrawn_hpa"], expected_withdrawal):
            raise ValueError(f"row {number}: native withdrawal does not reconcile")
        if not close(record["native_mass_created_hpa"], deficit - expected_withdrawal):
            raise ValueError(f"row {number}: native creation does not reconcile")
        # The helper's donor traversal is authoritative for ``exact``.  The
        # separately accumulated full-column diagnostic can round a few ulps
        # below the deficit even when that traversal reaches zero exactly.
        if status == "exact" and shortfall > tolerance:
            raise ValueError(f"row {number}: exact event exceeds tolerance")
        if status == "exact" and not close(shortfall, arithmetic_shortfall):
            raise ValueError(f"row {number}: exact-event diagnostic does not reconcile")
        if status == "roundoff_feasible" and not (0.0 < shortfall <= tolerance):
            raise ValueError(f"row {number}: roundoff event is outside tolerance")
        if status == "materially_unfillable" and shortfall <= tolerance:
            raise ValueError(f"row {number}: unfillable event is within tolerance")
        if status == "materially_unfillable" and not close(shortfall, arithmetic_shortfall):
            raise ValueError(f"row {number}: unfillable shortfall does not reconcile")

        name = species[index - 1]
        status_counts[status] += 1
        by_species[name][status] += 1
        by_species[name]["event_count"] += 1
        if status == "materially_unfillable":
            summary = unfillable_by_species.setdefault(
                name,
                {
                    "event_count": 0,
                    "total_shortfall_kg": 0.0,
                    "maximum_event_shortfall_kg": 0.0,
                },
            )
            summary["event_count"] += 1
            summary["total_shortfall_kg"] += record["shortfall_kg"]
            summary["maximum_event_shortfall_kg"] = max(
                summary["maximum_event_shortfall_kg"],
                record["shortfall_kg"],
            )
            call_key = (
                record["model_date"],
                record["model_time"],
                record["elapsed_seconds"],
                record["species_index"],
            )
            unfillable_by_call[call_key] += record["shortfall_kg"]
        total_shortfall += record["shortfall_kg"]
        maximum_shortfall = max(maximum_shortfall, record["shortfall_kg"])
        total_native_creation += record["native_mass_created_kg"]
        maximum_native_creation = max(maximum_native_creation, record["native_mass_created_kg"])
        run_ids.add(record["run_id"])
        thread_counts.add(record["omp_thread_count"])

    return {
        "status": "pass",
        "schema_version": SCHEMA_VERSION,
        "event_count": len(records),
        "status_counts": {status: status_counts.get(status, 0) for status in sorted(STATUSES)},
        "materially_unfillable_event_count": status_counts["materially_unfillable"],
        "invalid_donor_event_count": status_counts["invalid_donor"],
        "total_shortfall_kg": total_shortfall,
        "maximum_shortfall_kg": maximum_shortfall,
        "maximum_species_call_shortfall_kg": max(
            unfillable_by_call.values(), default=0.0
        ),
        "total_native_mass_created_kg": total_native_creation,
        "maximum_native_mass_created_kg": maximum_native_creation,
        "run_ids": sorted(run_ids),
        "omp_thread_counts": sorted(thread_counts),
        "affected_species": {
            name: dict(sorted(counts.items())) for name, counts in sorted(by_species.items())
        },
        "materially_unfillable_by_species": {
            name: values for name, values in sorted(unfillable_by_species.items())
        },
    }


def normalized_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ignored = {"run_id", "omp_thread_count"}
    return sorted(
        ({key: value for key, value in record.items() if key not in ignored} for record in records),
        key=event_key,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("geoschem_config", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--compare-ledger", type=Path)
    args = parser.parse_args()

    species = transported_species(args.geoschem_config)
    records = read_records(args.ledger)
    result = validate_records(records, species)
    result["ledger"] = {"path": str(args.ledger.resolve()), "sha256": sha256(args.ledger)}
    result["geoschem_config"] = {
        "path": str(args.geoschem_config.resolve()),
        "sha256": sha256(args.geoschem_config),
    }
    if args.compare_ledger:
        peer = read_records(args.compare_ledger)
        peer_result = validate_records(peer, species)
        if normalized_records(records) != normalized_records(peer):
            raise ValueError("survey ledgers differ after provenance normalization")
        result["thread_comparison"] = {
            "status": "pass",
            "peer_path": str(args.compare_ledger.resolve()),
            "peer_sha256": sha256(args.compare_ledger),
            "peer_summary": peer_result,
            "normalized_records_exactly_equal": True,
        }

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
