from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from plume_transport.validate_firex_tier_f_mechanical_match import build_report


def _write_csv(path: Path, row: dict[str, object]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _case(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    carrier = tmp_path / "carrier.csv"
    source = {
        "carrier_source_record_id": "source:0",
        "carrier_ordinal": 0,
        "carrier_raw_record_sha256": "a" * 64,
        "Time_Start": 86400,
        "Time_Stop": 86401,
    }
    _write_csv(carrier, source)
    digest = hashlib.sha256(carrier.read_bytes()).hexdigest()
    row: dict[str, object] = {
        "carrier_source_record_id": "source:0",
        "carrier_ordinal": 0,
        "carrier_raw_record_sha256": "a" * 64,
        "carrier_time_start_seconds": 86400,
        "carrier_time_stop_seconds": 86401,
        "match_valid": True,
        "match_rejection_reason": "accepted",
        "model_time_offset_seconds": 0,
        "model_latitude_offset_degrees": 0.5,
        "model_longitude_offset_degrees": -0.75,
        "model_altitude_offset_m": 10,
        "model_pressure_hpa": 800,
        "model_temperature_k": 280,
    }
    for state in ("ambient", "aop_reference"):
        for wavelength in (405, 532, 664):
            for component, value in {
                "tot": 5,
                "bc": 1,
                "brc": 1,
                "oa": 1,
                "dust": 1,
                "other": 1,
            }.items():
                row[f"model_abs_{wavelength}_{component}_{state}_mm1"] = value
    rows = tmp_path / "rows.csv"
    _write_csv(rows, row)
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "firex-tier-f-mechanical-match-v1",
                "result": "completed",
                "model_history": {"files": [{"sha256": "model"}]},
                "matching": {
                    "rows": 1,
                    "accepted_rows": 1,
                    "rejection_counts": {"accepted": 1},
                },
            }
        )
    )
    return summary, rows, carrier, digest


def test_validator_passes_complete_mechanical_row(tmp_path: Path) -> None:
    summary, rows, carrier, digest = _case(tmp_path)
    report = build_report(
        summary,
        rows,
        carrier,
        expected_carrier_sha256=digest,
        expected_model_sha256=["model"],
        expected_rows=1,
        maximum_time_offset_seconds=600,
        maximum_latitude_offset_degrees=1,
        maximum_longitude_offset_degrees=1.25,
        maximum_vertical_offset_m=1000,
        component_rtol=1e-6,
        component_atol_mm1=1e-8,
    )
    assert report["result"] == "pass"


def test_validator_fails_half_grid_and_closure(tmp_path: Path) -> None:
    summary, rows, carrier, digest = _case(tmp_path)
    records = list(csv.DictReader(rows.open(newline="", encoding="utf-8")))
    records[0]["model_latitude_offset_degrees"] = "1.1"
    records[0]["model_abs_405_tot_ambient_mm1"] = "7"
    _write_csv(rows, records[0])
    report = build_report(
        summary,
        rows,
        carrier,
        expected_carrier_sha256=digest,
        expected_model_sha256=["model"],
        expected_rows=1,
        maximum_time_offset_seconds=600,
        maximum_latitude_offset_degrees=1,
        maximum_longitude_offset_degrees=1.25,
        maximum_vertical_offset_m=1000,
        component_rtol=1e-6,
        component_atol_mm1=1e-8,
    )
    assert report["result"] == "fail"
    assert any("latitude" in value for value in report["errors"])
    assert any("closure" in value for value in report["errors"])
