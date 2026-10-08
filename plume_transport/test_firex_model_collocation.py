"""Focused tests for the file-backed strict FIREX collocation adapter."""

from __future__ import annotations

import csv
from pathlib import Path

import h5py
import numpy as np

from plume_transport.firex_model_collocation import (
    ABSORPTION_COMPONENTS,
    WAVELENGTHS_NM,
    build_collocation,
    decode_observation_cf_minutes,
    sha256,
    write_results,
)


def _write_observation(path: Path) -> None:
    with h5py.File(path, "w") as dataset:
        time = dataset.create_dataset("time", data=np.array([8, 9], dtype=np.int32))
        time.attrs["units"] = "minutes since 2019-08-06 19:40:00"
        time.attrs["calendar"] = "proleptic_gregorian"
        dataset.create_dataset("lat", data=np.array([0.0, 0.0]))
        dataset.create_dataset("lon", data=np.array([0.0, 0.0]))
        dataset.create_dataset("alt", data=np.array([150.0, 150.0]))
        dataset.create_dataset("Smoke_flag", data=np.array([1.0, 1.0]))
        dataset.create_dataset("smoke_age_corr", data=np.array([60.0, -1.0]))
        dataset.create_dataset("BC_mass_90_550_nm", data=np.array([1.0, 1.0]))
        # Negative optical values are finite and deliberately retained by the
        # frozen collocation contract; only age, navigation, and BC are gated.
        dataset.create_dataset("abs_dry_405", data=np.array([-1.0, 2.0]))
        dataset.create_dataset("abs_dry_532", data=np.array([3.0, 3.0]))
        dataset.create_dataset("abs_dry_664", data=np.array([4.0, 4.0]))


def _write_model(path: Path) -> None:
    with h5py.File(path, "w") as dataset:
        time = dataset.create_dataset("time", data=np.array([0.0, 20.0]))
        time.attrs["units"] = "minutes since 2019-08-06 19:40:00"
        time.attrs["calendar"] = "gregorian"
        lat = dataset.create_dataset("lat", data=np.array([0.0]))
        lat.attrs["units"] = "degrees_north"
        lon = dataset.create_dataset("lon", data=np.array([0.0]))
        lon.attrs["units"] = "degrees_east"
        shape = (2, 2, 1, 1)
        fields = {
            "Met_BXHEIGHT": (np.full(shape, 100.0), "m"),
            "Met_PMID": (np.full(shape, 1013.0), "hPa"),
            "Met_T": (np.full(shape, 273.0), "K"),
        }
        for name, (values, units) in fields.items():
            variable = dataset.create_dataset(name, data=values)
            variable.attrs["units"] = units
        phis = dataset.create_dataset("Met_PHIS", data=np.full((2, 1, 1), 100.0))
        phis.attrs["units"] = "m"
        component_value = {"BC": 1.0, "BrC": 2.0, "OA": 3.0, "Dust": 0.0, "Other": 0.0}
        for wavelength in WAVELENGTHS_NM:
            for component in ABSORPTION_COMPONENTS:
                name = f"AerosolDryAbs{wavelength}.0nm_{component}"
                value = 6.0 if component == "Tot" else component_value[component]
                variable = dataset.create_dataset(name, data=np.full(shape, value))
                variable.attrs["units"] = "Mm-1"


def test_observation_proleptic_gregorian_minutes_decode() -> None:
    decoded = decode_observation_cf_minutes(
        np.array([0.0, 1.5]),
        b"minutes since 2019-08-06 18:04:00",
        b"proleptic_gregorian",
    )
    assert decoded.astype("datetime64[m]").astype(str).tolist() == [
        "2019-08-06T18:04",
        "2019-08-06T18:05",
    ]


def test_file_backed_collocation_preserves_strict_selection_and_height_units(
    tmp_path: Path,
) -> None:
    observation = tmp_path / "observation.nc"
    model = tmp_path / "model.nc"
    _write_observation(observation)
    _write_model(model)

    summary, rows = build_collocation(
        observation_path=observation,
        expected_observation_sha256=sha256(observation),
        model_history_paths=[model],
        maximum_time_offset_seconds=1800.0,
        maximum_vertical_offset_m=1000.0,
        aop_reference_pressure_hpa=1013.0,
        aop_reference_temperature_k=273.0,
    )

    assert summary["matching"]["strict_observation_rows"] == 1
    assert summary["matching"]["accepted_rows"] == 1
    assert rows[0]["observation_row_index"] == 0
    assert rows[0]["match_valid"] is True
    assert rows[0]["observation_abs_405_mm1"] == -1.0
    assert rows[0]["model_layer_centre_altitude_m"] == 150.0
    assert rows[0]["model_abs_405_tot_aop_reference_mm1"] == 6.0

    output_json = tmp_path / "collocation.json"
    output_csv = tmp_path / "collocation.csv"
    write_results(
        summary,
        rows,
        output_json=output_json,
        output_csv=output_csv,
    )
    with output_csv.open(newline="", encoding="utf-8") as handle:
        written_rows = list(csv.DictReader(handle))
    assert written_rows[0]["match_valid"] == "True"
