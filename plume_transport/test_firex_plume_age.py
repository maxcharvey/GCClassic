"""Focused tests for the corrected FIREX-AQ plume-age summaries."""

from __future__ import annotations

import numpy as np
import pytest

from plume_transport.firex_plume_age import (
    FirexPlumeAgeError,
    VARIABLES,
    arrays_from_nco_json,
    summarize_arrays,
    summarize_directory,
)


def _arrays(length: int = 5) -> dict[str, np.ndarray]:
    arrays = {name: np.full(length, np.nan) for name in VARIABLES}
    arrays["time"] = np.arange(length)
    arrays["lat"] = np.arange(length)
    arrays["lon"] = np.arange(length)
    arrays["alt"] = np.arange(length)
    arrays["Smoke_flag"] = np.ones(length)
    arrays["smoke_age"] = np.array([0.0, 1800.0, 3600.0, 7200.0, 9000.0])
    arrays["smoke_age_corr"] = np.array([0.0, 1799.0, 1800.0, 7199.0, np.nan])
    arrays["abs_dry_405"] = np.array([4.0, -1.0, 8.0, 16.0, 2.0])
    arrays["abs_dry_532"] = np.array([2.0, 0.0, 4.0, 8.0, 1.0])
    arrays["abs_dry_664"] = np.array([1.0, 1.0, 2.0, 4.0, 1.0])
    arrays["BC_mass_90_550_nm"] = np.arange(length, dtype=float)
    arrays["BC_Dilution_Fraction"] = np.zeros(length)
    arrays["BC_Dilution_Mixed_Flag"] = np.zeros(length)
    arrays["OA_PM1_AMS_60s_JIMENEZ"] = np.arange(length, dtype=float)
    arrays["CO_DACOM"] = np.arange(length, dtype=float)
    arrays["smoke_agemethod"] = np.ones(length)
    return arrays


def test_bins_corrected_age_without_general_fallback() -> None:
    summary = summarize_arrays(_arrays(), flight_date="20190806")
    assert summary["general_age_rows"] == 5
    assert summary["corrected_age_rows"] == 4
    assert summary["general_only_age_rows"] == 1
    assert summary["fully_collocated_corrected_age_rows"] == 4
    assert [entry["rows"] for entry in summary["age_bins"]] == [2, 1, 1, 0, 0, 0]


def test_negative_absorption_is_retained_but_does_not_define_aae() -> None:
    summary = summarize_arrays(_arrays(), flight_date="20190806")
    assert summary["finite_negative_absorption_rows"]["abs_dry_405_Mm-1"] == 1
    first_bin = summary["age_bins"][0]
    assert first_bin["metrics"]["abs_dry_405_Mm-1"]["n"] == 2
    assert first_bin["metrics"]["AAE_405_664"]["n"] == 1
    assert summary["aae_qualified_rows"] == 3


def test_outside_smoke_rows_are_not_binned() -> None:
    arrays = _arrays()
    arrays["Smoke_flag"][0] = np.nan
    summary = summarize_arrays(arrays, flight_date="20190806")
    assert summary["in_smoke_rows"] == 4
    assert summary["corrected_age_rows"] == 3
    assert summary["age_bins"][0]["rows"] == 1


def test_missing_corrected_bc_excludes_fully_collocated_row() -> None:
    arrays = _arrays()
    arrays["BC_mass_90_550_nm"][0] = np.nan
    summary = summarize_arrays(arrays, flight_date="20190806")
    assert summary["corrected_age_rows"] == 4
    assert summary["fully_collocated_corrected_age_rows"] == 3
    assert summary["age_bins"][0]["rows"] == 1


def test_missing_ancillary_oa_does_not_drop_optical_bc_pair() -> None:
    arrays = _arrays()
    arrays["OA_PM1_AMS_60s_JIMENEZ"][0] = np.nan
    summary = summarize_arrays(arrays, flight_date="20190806")
    assert summary["fully_collocated_corrected_age_rows"] == 4
    assert summary["age_bins"][0]["metrics"]["OA_PM1_AMS_60s_JIMENEZ"]["n"] == 1


def test_nco_json_null_becomes_nan() -> None:
    payload = {
        "variables": {
            name: {"data": [1, None]} for name in VARIABLES
        }
    }
    arrays = arrays_from_nco_json(payload)
    assert arrays["abs_dry_405"][0] == 1.0
    assert np.isnan(arrays["abs_dry_405"][1])


def test_nco_json_missing_required_variable_fails_closed() -> None:
    payload = {"variables": {name: {"data": [1]} for name in VARIABLES[:-1]}}
    with pytest.raises(FirexPlumeAgeError, match="CO_DACOM"):
        arrays_from_nco_json(payload)


def test_legacy_r3_optical_carrier_fails_before_read(tmp_path) -> None:
    dates = [
        "20190722", "20190724", "20190725", "20190729", "20190730",
        "20190802", "20190803", "20190806", "20190807", "20190808",
        "20190812", "20190813", "20190815", "20190816", "20190819",
        "20190821", "20190823", "20190826", "20190829", "20190830",
        "20190831", "20190903", "20190905",
    ]
    for date in dates:
        (tmp_path / (
            f"FIREXAQ-mrg60-DC8-NC_merge_{date}_R3_with_AMS_"
            "SP2rebin-v1.nc"
        )).touch()
    with pytest.raises(FirexPlumeAgeError, match="legacy R3 optical"):
        summarize_directory(tmp_path)
