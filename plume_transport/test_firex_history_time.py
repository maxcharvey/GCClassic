"""Focused tests for read-only FIREX GEOS-Chem HISTORY time ingestion."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from plume_transport.firex_history_time import (
    FirexHistoryTimeError,
    decode_cf_minutes_since,
    load_history_time_series,
    read_history_time_file,
    validate_regular_time_series,
)
from plume_transport.validate_firex_history_time import build_report


def _history_file(
    directory: Path,
    name: str,
    values: list[float],
    units: str,
    calendar: str = "gregorian",
) -> Path:
    path = directory / name
    with h5py.File(path, "w") as dataset:
        coordinate = dataset.create_dataset("time", data=np.asarray(values))
        coordinate.attrs["units"] = units.encode("ascii")
        coordinate.attrs["calendar"] = calendar.encode("ascii")
    return path


def test_decoder_uses_cf_reference_and_not_the_timestamped_filename() -> None:
    decoded = decode_cf_minutes_since(
        [10.0, 30.0],
        "minutes since 2019-08-01 00:10:00",
        "gregorian",
    )
    np.testing.assert_array_equal(
        decoded,
        np.array(
            ["2019-08-01T00:20:00", "2019-08-01T00:40:00"],
            dtype="datetime64[ns]",
        ),
    )


def test_reads_bytes_attributes_from_a_history_file(tmp_path: Path) -> None:
    path = _history_file(
        tmp_path,
        "GEOSChem.FirexExact.20190801_0010z.nc4",
        [10.0, 30.0],
        "minutes since 2019-08-01 00:10:00",
    )

    record = read_history_time_file(path)

    assert record.path == path.resolve()
    assert record.units == "minutes since 2019-08-01 00:10:00"
    assert record.calendar == "gregorian"
    np.testing.assert_array_equal(
        record.timestamps,
        np.array(
            ["2019-08-01T00:20:00", "2019-08-01T00:40:00"],
            dtype="datetime64[ns]",
        ),
    )


def test_regular_rollover_timeline_passes_with_explicit_contract(tmp_path: Path) -> None:
    first = _history_file(
        tmp_path,
        "GEOSChem.FirexExact.20190801_0010z.nc4",
        [float(value) for value in range(10, 1411, 20)],
        "minutes since 2019-08-01 00:10:00",
    )
    rollover = _history_file(
        tmp_path,
        "GEOSChem.FirexExact.20190802_0000z.nc4",
        [0.0],
        "minutes since 2019-08-02 00:00:00",
    )

    series = load_history_time_series([first, rollover])
    summary = validate_regular_time_series(
        series,
        expected_records=72,
        cadence_minutes=20,
        expected_first="2019-08-01T00:20:00Z",
        expected_last="2019-08-02T00:00:00Z",
    )

    assert summary == {
        "decoded_records": 72,
        "decoded_first": "2019-08-01T00:20:00Z",
        "decoded_last": "2019-08-02T00:00:00Z",
        "cadence_minutes": 20,
    }
    report = build_report(
        [first, rollover],
        expected_records=72,
        cadence_minutes=20,
        expected_first="2019-08-01T00:20:00Z",
        expected_last="2019-08-02T00:00:00Z",
    )
    assert report["result"] == "pass"
    assert report["time_contract"]["filename_timestamp_used_for_record_time"] is False


def test_out_of_order_or_duplicate_decoded_records_fail_closed(tmp_path: Path) -> None:
    first = _history_file(
        tmp_path,
        "first.nc4",
        [0.0],
        "minutes since 2019-08-01 00:20:00",
    )
    duplicate = _history_file(
        tmp_path,
        "duplicate.nc4",
        [0.0],
        "minutes since 2019-08-01 00:20:00",
    )

    with pytest.raises(FirexHistoryTimeError, match="strictly increasing"):
        load_history_time_series([first, duplicate])


@pytest.mark.parametrize(
    ("units", "calendar", "message"),
    [
        ("hours since 2019-08-01 00:00:00", "gregorian", "unsupported time units"),
        ("minutes since 2019-08-01 00:00:00", "360_day", "unsupported CF calendar"),
    ],
)
def test_unsupported_cf_metadata_fails_closed(
    units: str, calendar: str, message: str
) -> None:
    with pytest.raises(FirexHistoryTimeError, match=message):
        decode_cf_minutes_since([0.0], units, calendar)


def test_non_numeric_time_coordinate_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "nonnumeric.nc4"
    with h5py.File(path, "w") as dataset:
        coordinate = dataset.create_dataset("time", data=np.array([b"not-a-time"]))
        coordinate.attrs["units"] = b"minutes since 2019-08-01 00:00:00"
        coordinate.attrs["calendar"] = b"gregorian"

    with pytest.raises(FirexHistoryTimeError, match="not a readable numeric array"):
        read_history_time_file(path)


def test_report_captures_a_contract_failure_without_rewriting_input(tmp_path: Path) -> None:
    path = _history_file(
        tmp_path,
        "GEOSChem.FirexExact.20190801_0010z.nc4",
        [10.0],
        "minutes since 2019-08-01 00:10:00",
    )
    before = path.read_bytes()

    report = build_report(
        [path],
        expected_records=1,
        cadence_minutes=20,
        expected_first="2019-08-01T00:10:00Z",
        expected_last="2019-08-01T00:10:00Z",
    )

    assert report["result"] == "fail"
    assert "decoded first timestamp" in report["errors"][0]
    assert path.read_bytes() == before
