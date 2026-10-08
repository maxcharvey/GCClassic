#!/usr/bin/env python3
"""Focused tests for the Tier-F 60-second resolution gate."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import tempfile

import numpy as np
import pytest

from firex_tier_f_phase2_join import IcarttSource, SourceRecord
from firex_tier_f_resolution_reconciliation import (
    ReconciliationError,
    aggregate_aop,
    aggregate_sp2,
    bin_index,
    classify_sources,
    compare,
    decode_bounds,
    float32_equal,
    float32_ulp_distance,
)


def record(
    product: str,
    ordinal: int,
    time_start: str,
    values: dict[str, str],
) -> SourceRecord:
    return SourceRecord(
        product=product,
        source_id=f"{product.lower()[0] * 64}:{ordinal}",
        ordinal=ordinal,
        start=Decimal(time_start),
        stop=Decimal(time_start) + 1,
        raw_line=b"raw",
        values={"Time_Start": time_start, **values},
    )


def source(
    product: str,
    records: tuple[SourceRecord, ...],
    missing: dict[str, str],
) -> IcarttSource:
    fields = ("Time_Start", *missing)
    return IcarttSource(
        product=product,
        path=Path(f"{product}.ict"),
        payload_sha256=product.lower()[0] * 64,
        header_lines=13,
        fields=fields,
        missing_values=missing,
        records=records,
    )


def test_decode_bounds_requires_contiguous_60_second_intervals() -> None:
    raw = np.array([[0, 1], [1, 2]], dtype=np.int32)
    bounds = decode_bounds(raw, "minutes since 2019-08-06 18:03:30")
    np.testing.assert_array_equal(
        bounds, [[65010, 65070], [65070, 65130]]
    )
    with pytest.raises(ReconciliationError, match="not contiguous"):
        decode_bounds(
            np.array([[0, 1], [2, 3]], dtype=np.int32),
            "minutes since 2019-08-06 18:03:30",
        )


def test_bin_membership_is_half_open() -> None:
    bounds = np.array([[0, 60], [60, 120]], dtype=np.int64)
    assert bin_index(Decimal("0"), bounds) == 0
    assert bin_index(Decimal("59"), bounds) == 0
    assert bin_index(Decimal("60"), bounds) == 1
    assert bin_index(Decimal("120"), bounds) is None


def test_aop_bands_use_independent_valid_masks_and_retain_negatives() -> None:
    missing = {field: "-9999" for field in (
        "abs_dry_405",
        "abs_dry_532",
        "abs_dry_664",
    )}
    records = (
        record(
            "AOP",
            0,
            "0",
            {
                "abs_dry_405": "-1",
                "abs_dry_532": "-9999.000",
                "abs_dry_664": "2",
            },
        ),
        record(
            "AOP",
            1,
            "1",
            {
                "abs_dry_405": "3",
                "abs_dry_532": "4",
                "abs_dry_664": "-8888",
            },
        ),
    )
    result = aggregate_aop(
        source("AOP", records, missing), [list(records)]
    )[0]
    assert result["abs_dry_405"]["valid_count"] == 2
    assert result["abs_dry_405"]["mean64"] == 1
    assert result["abs_dry_532"]["valid_count"] == 1
    assert result["abs_dry_664"]["valid_count"] == 1


def test_sp2_uses_joint_mass_and_binary_flag_validity() -> None:
    missing = {
        "BC_mass_90_550_nm": "-9999.99",
        "BC_Dilution_Flag": "-9999.99",
    }
    records = (
        record(
            "SP2",
            0,
            "0",
            {"BC_mass_90_550_nm": "2", "BC_Dilution_Flag": "0"},
        ),
        record(
            "SP2",
            1,
            "1",
            {"BC_mass_90_550_nm": "4", "BC_Dilution_Flag": "1"},
        ),
        record(
            "SP2",
            2,
            "2",
            {"BC_mass_90_550_nm": "6", "BC_Dilution_Flag": "-9999.99"},
        ),
        record(
            "SP2",
            3,
            "3",
            {"BC_mass_90_550_nm": "-9999.99", "BC_Dilution_Flag": "1"},
        ),
    )
    result = aggregate_sp2(
        source("SP2", records, missing), [list(records)]
    )[0]
    assert result["valid_mass_count"] == 3
    assert result["valid_flag_count"] == 2
    assert result["n_undiluted"] == 1
    assert result["n_diluted"] == 1
    assert result["dilution_state"] == "mixed"
    assert result["dilution_binary"] == -127
    assert result["dilution_mixed"] == 1


def test_terminal_inside_unlinked_record_is_retained() -> None:
    item = record(
        "SP2",
        0,
        "120",
        {"BC_mass_90_550_nm": "37.68", "BC_Dilution_Flag": "0"},
    )
    data = source(
        "SP2",
        (item,),
        {
            "BC_mass_90_550_nm": "-9999.99",
            "BC_Dilution_Flag": "-9999.99",
        },
    )
    rows, grouped, counts = classify_sources(
        {"SP2": data}, {"SP2": set()}, np.array([[60, 180]])
    )
    assert rows[0]["coverage_class"] == "tier_e_inside_unlinked"
    assert grouped["SP2"][0][0].source_id == item.source_id
    assert counts["SP2"]["tier_e_inside_unlinked"] == 1


def test_float32_gate_uses_bits_and_semantic_nan() -> None:
    assert float32_equal(np.float32(1), np.float32(1))
    assert float32_equal(np.float32(np.nan), np.float32(np.nan))
    assert not float32_equal(np.float32(0), np.float32(-0.0))
    assert float32_ulp_distance(np.float32(1), np.float32(1)) == 0


def test_reproduction_comparison_is_byte_strict() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        left, right = root / "left", root / "right"
        left.mkdir()
        right.mkdir()
        for name in (
            "source_to_60s_bins.csv",
            "reaggregated_60s.csv",
            "reconciliation.json",
        ):
            (left / name).write_text(name, encoding="utf-8")
            (right / name).write_text(name, encoding="utf-8")
        assert compare(left, right)["status"] == "PASS"
        (right / "reconciliation.json").write_text(
            "different", encoding="utf-8"
        )
        with pytest.raises(ReconciliationError, match="differ"):
            compare(left, right)
