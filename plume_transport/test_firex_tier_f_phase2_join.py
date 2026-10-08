#!/usr/bin/env python3
"""Focused tests for the FIREX-AQ Tier-F Phase-2 join."""

from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from firex_tier_f_phase2_join import (
    IcarttSource,
    JoinError,
    SourceRecord,
    compare_reproductions,
    exact_decimal,
    format_decimal,
    integral_time,
    iter_icartt_rows,
    overlap_bounds,
    overlaps,
    record_id,
    sentinel_counts,
    temporal_links,
    write_json,
)


def source(
    product: str,
    ordinal: int,
    start: str,
    stop: str,
) -> SourceRecord:
    raw = f"{start},{stop}".encode()
    return SourceRecord(
        product=product,
        source_id=f"{'a' * 64}:{ordinal}",
        ordinal=ordinal,
        start=Decimal(start),
        stop=Decimal(stop),
        raw_line=raw,
        values={"Time_Start": start, "Time_Stop": stop},
    )


def test_exact_decimal_preserves_lexical_precision() -> None:
    assert exact_decimal("10.199999999999999", "identifier") == Decimal(
        "10.199999999999999"
    )


def test_exact_decimal_rejects_nan() -> None:
    with pytest.raises(JoinError, match="non-finite"):
        exact_decimal("NaN", "test")


def test_integral_time_rejects_fraction() -> None:
    with pytest.raises(JoinError, match="not integral"):
        integral_time("1.5", "time")


def test_record_identity_is_payload_hash_plus_ordinal() -> None:
    assert record_id("b" * 64, 12) == f"{'b' * 64}:12"


def test_half_open_touching_intervals_do_not_overlap() -> None:
    assert not overlaps(source("carrier", 0, "0", "1"), source("AOP", 0, "1", "2"))


def test_positive_fractional_overlap_is_retained() -> None:
    carrier = source("carrier", 0, "0", "1")
    ams = source("AMS", 0, "0.22", "1.22")
    assert overlaps(carrier, ams)
    assert overlap_bounds(carrier, ams) == (
        Decimal("0.22"),
        Decimal("1"),
        Decimal("0.78"),
    )


def test_one_source_record_can_link_two_carriers() -> None:
    carriers = [source("carrier", 0, "0", "1"), source("carrier", 1, "1", "2")]
    ams = [source("AMS", 0, "0.22", "1.22")]
    links = temporal_links(carriers, ams)
    assert [len(links[item.source_id]) for item in carriers] == [1, 1]
    assert links[carriers[0].source_id][0].source_id == links[
        carriers[1].source_id
    ][0].source_id


def test_multiple_source_records_for_one_carrier_are_not_collapsed() -> None:
    carriers = [source("carrier", 0, "0", "1")]
    direct = [
        source("AMS", 0, "0.1", "0.4"),
        source("AMS", 1, "0.5", "0.9"),
    ]
    links = temporal_links(carriers, direct)
    assert [item.ordinal for item in links[carriers[0].source_id]] == [0, 1]


def test_temporal_links_do_not_nearest_fill_a_gap() -> None:
    carriers = [source("carrier", 0, "0", "1"), source("carrier", 1, "1", "2")]
    direct = [source("AMS", 0, "0.1", "0.9")]
    links = temporal_links(carriers, direct)
    assert len(links[carriers[0].source_id]) == 1
    assert links[carriers[1].source_id] == []


def test_decimal_format_is_deterministic() -> None:
    assert format_decimal(Decimal("1.2300")) == "1.23"
    assert format_decimal(Decimal("1.000")) == "1"
    assert format_decimal(Decimal("0")) == "0"


def test_icartt_reader_preserves_raw_line_hash_and_tokens() -> None:
    payload = (
        b"3,1001\r\n"
        b"metadata\r\n"
        b"Time_Start, Time_Stop, value\r\n"
        b"0,1, -9999\r\n"
    )
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "test.ict"
        path.write_bytes(payload)
        header_count, fields, missing_values, rows = iter_icartt_rows(path)
        observed = list(rows)
    assert header_count == 3
    assert fields == ("Time_Start", "Time_Stop", "value")
    assert missing_values == {}
    assert observed[0][1] == b"0,1, -9999"
    assert observed[0][2] == ("0", "1", "-9999")


def test_icartt_reader_rejects_wrong_row_width() -> None:
    payload = b"2,1001\nTime_Start, Time_Stop\n0,1,2\n"
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "bad.ict"
        path.write_bytes(payload)
        _, _, _, rows = iter_icartt_rows(path)
        with pytest.raises(JoinError, match="row 0 width"):
            list(rows)


def test_raw_record_hash_uses_unmodified_bytes() -> None:
    item = source("AOP", 0, "0", "1")
    assert item.raw_sha256 == hashlib.sha256(b"0,1").hexdigest()


def test_variable_declared_missing_lexeme_drives_sentinel_count() -> None:
    item = SourceRecord(
        product="SP2",
        source_id=f"{'c' * 64}:0",
        ordinal=0,
        start=Decimal("0"),
        stop=Decimal("1"),
        raw_line=b"0,-9999.99,1",
        values={
            "Time_Start": "0",
            "BC_mass_90_550_nm": "-9999.99",
            "BC_Dilution_Flag": "1",
        },
    )
    source_data = IcarttSource(
        product="SP2",
        path=Path("SP2.ict"),
        payload_sha256="c" * 64,
        header_lines=13,
        fields=("Time_Start", "BC_mass_90_550_nm", "BC_Dilution_Flag"),
        missing_values={
            "BC_mass_90_550_nm": "-9999.99",
            "BC_Dilution_Flag": "-9999.99",
        },
        records=(item,),
    )
    assert sentinel_counts(source_data) == {
        "missing": 1,
        "ULOD": 0,
        "LLOD": 0,
    }


def test_missing_classification_accepts_decimal_equivalent_source_token() -> None:
    item = SourceRecord(
        product="AOP",
        source_id=f"{'d' * 64}:0",
        ordinal=0,
        start=Decimal("0"),
        stop=Decimal("1"),
        raw_line=b"0,-9999.000",
        values={"Time_Start": "0", "abs_dry_405": "-9999.000"},
    )
    source_data = IcarttSource(
        product="AOP",
        path=Path("AOP.ict"),
        payload_sha256="d" * 64,
        header_lines=13,
        fields=("Time_Start", "abs_dry_405"),
        missing_values={"abs_dry_405": "-9999"},
        records=(item,),
    )
    assert sentinel_counts(source_data)["missing"] == 1


def test_icartt_reader_derives_variable_specific_missing_values() -> None:
    payload = (
        b"13,1001\nPI\nORG\nDESCRIPTION\nMISSION\n1,1\n"
        b"2019,08,06,2020,01,01\n1\n"
        b"Time_Start, seconds\n2\n1,1\n-9999.99,-8888\n"
        b"Time_Start, BC_mass_90_550_nm, BC_Dilution_Flag\n"
        b"0,-9999.99,1\n"
    )
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "sp2.ict"
        path.write_bytes(payload)
        _, fields, missing_values, rows = iter_icartt_rows(path)
        observed = list(rows)
    assert fields == (
        "Time_Start",
        "BC_mass_90_550_nm",
        "BC_Dilution_Flag",
    )
    assert missing_values == {
        "BC_mass_90_550_nm": "-9999.99",
        "BC_Dilution_Flag": "-8888",
    }
    assert observed[0][2][1] == "-9999.99"


def test_reproduction_comparison_accepts_identical_deterministic_artifacts() -> None:
    names = (
        "source_record_inventory.csv",
        "carrier_source_links.csv",
        "carrier_join.csv",
        "validation.json",
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        left = root / "left"
        right = root / "right"
        left.mkdir()
        right.mkdir()
        for name in names:
            (left / name).write_text(f"{name}\n", encoding="utf-8")
            (right / name).write_text(f"{name}\n", encoding="utf-8")
        report = compare_reproductions(left, right)
    assert report["status"] == "PASS"
    assert all(item["identical"] for item in report["comparisons"])


def test_reproduction_comparison_fails_closed_on_difference() -> None:
    names = (
        "source_record_inventory.csv",
        "carrier_source_links.csv",
        "carrier_join.csv",
        "validation.json",
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        left = root / "left"
        right = root / "right"
        left.mkdir()
        right.mkdir()
        for name in names:
            (left / name).write_text("same\n", encoding="utf-8")
            (right / name).write_text("same\n", encoding="utf-8")
        (right / "carrier_join.csv").write_text("different\n", encoding="utf-8")
        with pytest.raises(JoinError, match="differ"):
            compare_reproductions(left, right)


def test_json_writer_is_sorted_and_rejects_nan() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "value.json"
        write_json(path, {"b": 2, "a": 1})
        assert list(json.loads(path.read_text()).keys()) == ["a", "b"]
        with pytest.raises(ValueError):
            write_json(path, {"bad": float("nan")})
