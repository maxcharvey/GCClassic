from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from plume_transport.firex_tier_f_mechanical_match import (
    TierFMechanicalMatchError,
    read_carrier,
)


FIELDS = [
    "carrier_source_record_id",
    "carrier_ordinal",
    "carrier_raw_record_sha256",
    "Time_Start",
    "Time_Stop",
    "Latitude",
    "Longitude",
    "MSL_GPS_Altitude",
]


def _write(path: Path, rows: list[dict[str, object]]) -> str:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict[str, object]]:
    return [
        {
            "carrier_source_record_id": "source:0",
            "carrier_ordinal": 0,
            "carrier_raw_record_sha256": "a" * 64,
            "Time_Start": 86399,
            "Time_Stop": 86400,
            "Latitude": 45,
            "Longitude": -115,
            "MSL_GPS_Altitude": 1000,
        },
        {
            "carrier_source_record_id": "source:1",
            "carrier_ordinal": 1,
            "carrier_raw_record_sha256": "b" * 64,
            "Time_Start": 86400,
            "Time_Stop": 86401,
            "Latitude": 46,
            "Longitude": -114,
            "MSL_GPS_Altitude": 1100,
        },
    ]


def test_read_carrier_preserves_midnight_rollover(tmp_path: Path) -> None:
    path = tmp_path / "carrier.csv"
    digest = _write(path, _rows())
    arrays, report = read_carrier(path, expected_sha256=digest, expected_rows=2)
    assert str(arrays["time"][0]) == "2019-08-06T23:59:59.000000000"
    assert str(arrays["time"][1]) == "2019-08-07T00:00:00.000000000"
    assert report["post_midnight_rows"] == 1


def test_read_carrier_rejects_non_unit_interval(tmp_path: Path) -> None:
    path = tmp_path / "carrier.csv"
    rows = _rows()
    rows[1]["Time_Stop"] = 86402
    digest = _write(path, rows)
    with pytest.raises(TierFMechanicalMatchError, match="Time_Stop"):
        read_carrier(path, expected_sha256=digest, expected_rows=2)


def test_read_carrier_rejects_nonintegral_start(tmp_path: Path) -> None:
    path = tmp_path / "carrier.csv"
    rows = _rows()
    rows[1]["Time_Start"] = 86400.5
    rows[1]["Time_Stop"] = 86401.5
    digest = _write(path, rows)
    with pytest.raises(TierFMechanicalMatchError, match="integral"):
        read_carrier(path, expected_sha256=digest, expected_rows=2)
