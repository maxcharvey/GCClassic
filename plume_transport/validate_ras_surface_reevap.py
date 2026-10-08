#!/usr/bin/env python3
"""Validate the diagnostic-only RAS surface re-evaporation ledger."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ras-surface-reevap-ledger-v1"
TAGS = (
    "PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE",
    "PLUME_SFC_PI", "PLUME_PBL_PI", "PLUME_6535_PI", "PLUME_LEV_PI",
    "PLUME_PROFILE_PI",
)
FIELDS = (
    "schema_version", "run_id", "manifest_id", "model_date", "model_time",
    "elapsed_seconds", "convection_call_index", "omp_thread_count", "tag",
    "model_species_id", "advect_id", "wetdep_id", "i_gc", "j_gc", "k_gc",
    "event_count", "f_scavenging", "area_m2", "gained_kg_m2",
    "gross_wash_kg_m2", "signed_wetloss_kg_m2", "signed_wetloss_kg",
    "realized_signed_loss_kg", "state_gain_kg",
)
INT_FIELDS = {
    "model_date", "model_time", "elapsed_seconds", "convection_call_index",
    "omp_thread_count", "model_species_id", "advect_id", "wetdep_id", "i_gc",
    "j_gc", "k_gc", "event_count",
}
FLOAT_FIELDS = set(FIELDS) - INT_FIELDS - {
    "schema_version", "run_id", "manifest_id", "tag"
}


def _close(a: float, b: float, floor: float = 1e-12) -> bool:
    return abs(a - b) <= max(floor, 32.0 * math.ulp(max(abs(a), abs(b), 1.0)))


def parse_ledger(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"{path}: schema header drift")
        rows: list[dict[str, Any]] = []
        keys: set[tuple[int, str, int, int]] = set()
        previous: tuple[int, int, int, int] | None = None
        tag_order = {tag: i for i, tag in enumerate(TAGS)}
        for line, raw in enumerate(reader, start=2):
            row: dict[str, Any] = dict(raw)
            for name in INT_FIELDS:
                row[name] = int(row[name])
            for name in FLOAT_FIELDS:
                row[name] = float(row[name])
                if not math.isfinite(row[name]):
                    raise ValueError(f"{path}:{line}: non-finite {name}")
            if row["schema_version"] != SCHEMA:
                raise ValueError(f"{path}:{line}: wrong schema version")
            if not row["run_id"] or not row["manifest_id"]:
                raise ValueError(f"{path}:{line}: missing provenance")
            if row["tag"] not in tag_order:
                raise ValueError(f"{path}:{line}: unexpected tag")
            if row["k_gc"] != 1 or row["event_count"] <= 0:
                raise ValueError(f"{path}:{line}: invalid surface event")
            if row["f_scavenging"] != 0.0:
                raise ValueError(f"{path}:{line}: surface F must be exact zero")
            if min(row["model_species_id"], row["advect_id"], row["wetdep_id"],
                   row["i_gc"], row["j_gc"]) <= 0:
                raise ValueError(f"{path}:{line}: invalid one-based identifier")
            key = (row["convection_call_index"], row["tag"], row["j_gc"], row["i_gc"])
            if key in keys:
                raise ValueError(f"{path}:{line}: duplicate row key")
            keys.add(key)
            order = (row["convection_call_index"], tag_order[row["tag"]],
                     row["j_gc"], row["i_gc"])
            if previous is not None and order <= previous:
                raise ValueError(f"{path}:{line}: nondeterministic row order")
            previous = order
            if not _close(row["gross_wash_kg_m2"] - row["gained_kg_m2"],
                          row["signed_wetloss_kg_m2"]):
                raise ValueError(f"{path}:{line}: WETLOSS sign identity failed")
            if not _close(row["signed_wetloss_kg_m2"] * row["area_m2"],
                          row["signed_wetloss_kg"]):
                raise ValueError(f"{path}:{line}: surface mass conversion failed")
            if not _close(-row["realized_signed_loss_kg"], row["state_gain_kg"]):
                raise ValueError(f"{path}:{line}: state-gain identity failed")
            rows.append(row)
    return rows


def normalized_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ignored = {"run_id", "manifest_id", "omp_thread_count"}
    return [{k: v for k, v in row.items() if k not in ignored} for row in rows]


def aggregate(rows: Iterable[dict[str, Any]]) -> dict[tuple[int, str], dict[str, float]]:
    result: dict[tuple[int, str], dict[str, float]] = defaultdict(
        lambda: {"formula_kg": 0.0, "realized_kg": 0.0}
    )
    for row in rows:
        key = (row["elapsed_seconds"], row["tag"])
        result[key]["formula_kg"] += row["signed_wetloss_kg"]
        result[key]["realized_kg"] += row["realized_signed_loss_kg"]
    return dict(result)


def _hms_to_seconds(value: str) -> int:
    n = int(value)
    return (n // 10000) * 3600 + ((n // 100) % 100) * 60 + n % 100


def validate_matrix(run_dirs: dict[tuple[str, int], Path], wet_report: Path) -> dict[str, Any]:
    ledgers: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for key, run_dir in run_dirs.items():
        ledgers[key] = parse_ledger(run_dir / "OutputDir" / "ras_surface_reevap.csv")
    thread = {
        arm: normalized_rows(ledgers[(arm, 1)]) == normalized_rows(ledgers[(arm, 8)])
        for arm in ("off", "on")
    }
    source = json.loads(wet_report.read_text(encoding="utf-8"))
    closures: list[dict[str, Any]] = []
    failures = 0
    for heartbeat, arms in source["convective_wet_loss"].items():
        elapsed = _hms_to_seconds(heartbeat)
        for arm, tags in arms.items():
            sums = aggregate(ledgers[(arm, 1)])
            for tag, native in tags.items():
                residual = native["checkpoint_minus_native_kg"]
                ledger = sums.get((elapsed, tag), {"formula_kg": 0.0, "realized_kg": 0.0})
                tol = max(1e-9, native["float32_ulp_tolerance_kg"])
                passed = (abs(residual - ledger["realized_kg"]) <= tol and
                          abs(ledger["formula_kg"] - ledger["realized_kg"]) <= tol)
                failures += int(not passed)
                closures.append({"heartbeat": heartbeat, "arm": arm, "tag": tag,
                                 "checkpoint_minus_wetlossconv_kg": residual,
                                 **ledger, "tolerance_kg": tol, "passed": passed})
    status = "pass" if failures == 0 and all(thread.values()) else "fail"
    return {"schema_version": SCHEMA, "status": status,
            "scientific_acceptance": False, "thread_determinism": thread,
            "closure_failure_count": failures, "closures": closures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("off_one", type=Path)
    parser.add_argument("off_eight", type=Path)
    parser.add_argument("on_one", type=Path)
    parser.add_argument("on_eight", type=Path)
    parser.add_argument("--wetdep-report", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = validate_matrix({("off", 1): args.off_one, ("off", 8): args.off_eight,
                              ("on", 1): args.on_one, ("on", 8): args.on_eight},
                             args.wetdep_report)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
