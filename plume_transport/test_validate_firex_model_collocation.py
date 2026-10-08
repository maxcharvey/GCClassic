"""Focused tests for the completed FIREX collocation validator."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from plume_transport.validate_firex_model_collocation import build_report


def _inputs(directory: Path, *, time_offset: float = 600.0, total: float = 6.0):
    summary_path = directory / "summary.json"
    csv_path = directory / "rows.csv"
    summary = {
        "schema_version": "firex-model-collocation-v1",
        "result": "completed",
        "observation": {"sha256": "a" * 64, "strict_rows": 1},
        "model_history": {
            "files": [{"path": "/model.nc4", "sha256": "b" * 64}],
            "selected_records": [{"timestamp": "2019-08-06T19:40:00Z"}],
            "selected_first": "2019-08-06T19:40:00Z",
            "selected_last": "2019-08-06T19:40:00Z",
        },
        "matching": {
            "maximum_time_offset_seconds": 600.0,
            "maximum_vertical_offset_m": 1000.0,
            "strict_observation_rows": 1,
            "accepted_rows": 1,
            "rejection_counts": {"accepted": 1},
        },
        "volume_state": {
            "aop_reference_pressure_hpa": 1013.0,
            "aop_reference_temperature_k": 273.0,
        },
        "metrics_model_minus_observation": {
            str(wavelength): {"n": 1} for wavelength in (405, 532, 664)
        },
    }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    row: dict[str, object] = {
        "match_valid": True,
        "match_rejection_reason": "accepted",
        "model_time_offset_seconds": time_offset,
        "model_latitude_offset_degrees": 1.0,
        "model_longitude_offset_degrees": -1.25,
        "model_altitude_offset_m": 1000.0,
        "model_pressure_hpa": 900.0,
        "model_temperature_k": 280.0,
        "observation_abs_405_mm1": 1.0,
        "observation_abs_532_mm1": -1.0,
        "observation_abs_664_mm1": 2.0,
    }
    for wavelength in (405, 532, 664):
        for state in ("ambient", "aop_reference"):
            row[f"model_abs_{wavelength}_tot_{state}_mm1"] = total
            row[f"model_abs_{wavelength}_bc_{state}_mm1"] = 1.0
            row[f"model_abs_{wavelength}_brc_{state}_mm1"] = 2.0
            row[f"model_abs_{wavelength}_oa_{state}_mm1"] = 3.0
            row[f"model_abs_{wavelength}_dust_{state}_mm1"] = 0.0
            row[f"model_abs_{wavelength}_other_{state}_mm1"] = 0.0
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return summary_path, csv_path


def _report(summary_path: Path, csv_path: Path):
    return build_report(
        summary_path,
        csv_path,
        expected_observation_sha256="a" * 64,
        expected_model_sha256=["b" * 64],
        expected_rows=1,
        expected_selected_records=1,
        expected_selected_first="2019-08-06T19:40:00Z",
        expected_selected_last="2019-08-06T19:40:00Z",
        maximum_time_offset_seconds=600.0,
        maximum_latitude_offset_degrees=1.0,
        maximum_longitude_offset_degrees=1.25,
        maximum_vertical_offset_m=1000.0,
        expected_negative_counts=[0, 1, 0],
        expected_positive_aae_rows=1,
        component_rtol=1.0e-6,
        component_atol_mm1=1.0e-8,
    )


def test_exact_contract_passes_and_retains_negative_observation(tmp_path: Path) -> None:
    summary_path, csv_path = _inputs(tmp_path)
    report = _report(summary_path, csv_path)
    assert report["result"] == "pass"
    assert report["checks"]["finite_negative_observation_counts"] == {
        "405": 0,
        "532": 1,
        "664": 0,
    }


def test_time_offset_above_half_cadence_fails(tmp_path: Path) -> None:
    summary_path, csv_path = _inputs(tmp_path, time_offset=600.1)
    report = _report(summary_path, csv_path)
    assert report["result"] == "fail"
    assert "maximum time offset" in " ".join(report["errors"])


def test_component_nonclosure_fails(tmp_path: Path) -> None:
    summary_path, csv_path = _inputs(tmp_path, total=6.1)
    report = _report(summary_path, csv_path)
    assert report["result"] == "fail"
    assert "component closure fails" in " ".join(report["errors"])
