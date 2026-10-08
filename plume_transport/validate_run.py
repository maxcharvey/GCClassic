#!/usr/bin/env python3
"""Validate V0 source ledgers and secondary end-restart plume diagnostics."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path

import h5py
import numpy as np
import yaml
from scipy.io import netcdf_file

from generate_source import TAGS, sha256


AIR_MW_G_MOL = 28.9644
G0_M_S2 = 9.80665
CONTRACT_VERSION = "stage1-v0-ledger-v2"


def read_array(dataset: h5py.File, name: str) -> np.ndarray:
    if name not in dataset:
        raise KeyError(f"dataset is missing {name}")
    return np.asarray(dataset[name][:], dtype=np.float64)


def text_attribute(variable: h5py.Dataset, name: str) -> str:
    if name not in variable.attrs:
        raise KeyError(f"{variable.name} is missing the {name} attribute")
    value = variable.attrs[name]
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def finite_scalar(value: object, label: str, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if positive and result <= 0.0:
        raise ValueError(f"{label} must be positive")
    if not positive and result < 0.0:
        raise ValueError(f"{label} must be non-negative")
    return result


def dimension_names(variable: h5py.Dataset) -> tuple[str, ...]:
    names: list[str] = []
    for dimension in variable.dims:
        scales = list(dimension.keys())
        if len(scales) != 1:
            raise ValueError(
                f"{variable.name}: expected one named scale per dimension, got {scales}"
            )
        names.append(scales[0])
    return tuple(names)


def require_dimensions(variable: h5py.Dataset, expected: tuple[str, ...]) -> None:
    actual = dimension_names(variable)
    if actual != expected:
        raise ValueError(f"{variable.name}: dimensions {actual} != {expected}")


def require_time_reference(
    dataset: h5py.File,
    expected: datetime,
    units: str,
    label: str,
) -> None:
    time = read_array(dataset, "time")
    if time.shape != (1,) or float(time[0]) != 0.0:
        raise ValueError(f"{label}: expected one time record at coordinate zero")
    expected_units = f"{units} since {expected.strftime('%Y-%m-%d %H:%M:%S')}"
    actual_units = text_attribute(dataset["time"], "units")
    if actual_units not in {expected_units, f"{expected_units} GMT"}:
        raise ValueError(f"{label}: time units {actual_units!r} != {expected_units!r}")


def require_coordinates(
    dataset: h5py.File,
    reference: dict[str, np.ndarray],
    label: str,
    *,
    include_lev: bool,
) -> None:
    names = ("lat", "lon", "lev") if include_lev else ("lat", "lon")
    for name in names:
        values = read_array(dataset, name)
        expected = reference[name]
        if values.shape != expected.shape or not np.allclose(
            values, expected, rtol=0.0, atol=1.0e-12
        ):
            raise ValueError(f"{label}: {name} coordinate differs from checked source grid")


def validate_checked_inputs(run_directory: Path, manifest: dict) -> dict[str, str]:
    declared_initial_restart = Path(manifest["paths"]["generated_restart"]).resolve()
    if declared_initial_restart.parent != run_directory / "Restarts":
        raise ValueError("checked initial restart is not in the declared run directory")
    checks = {
        "generated_restart_sha256": declared_initial_restart,
        "geoschem_config_sha256": run_directory / "geoschem_config.yml",
        "hemco_config_sha256": run_directory / "HEMCO_Config.rc",
        "hemco_diagn_sha256": run_directory / "HEMCO_Diagn.rc",
        "history_rc_sha256": run_directory / "HISTORY.rc",
        "species_database_sha256": run_directory / "species_database.yml",
        "source_validation_report_sha256": run_directory / "plume_source_validation.json",
        "run_validator_sha256": Path(__file__).resolve(),
    }
    expected_hashes = manifest["artifact_hashes"]
    actual: dict[str, str] = {}
    for key, path in checks.items():
        digest = sha256(path)
        if digest != expected_hashes[key]:
            raise ValueError(f"{path}: SHA-256 {digest} != checked {expected_hashes[key]}")
        actual[key] = digest

    executable = Path(manifest["build"]["executable"]["path"]).resolve()
    if executable != run_directory / "gcclassic":
        raise ValueError("checked executable is not the one installed in the run directory")
    executable_hash = sha256(executable)
    if executable_hash != manifest["build"]["executable"]["sha256"]:
        raise ValueError("run-directory executable SHA-256 differs from manifest")
    actual["executable_sha256"] = executable_hash

    hemco_config = (run_directory / "HEMCO_Config.rc").read_text(encoding="utf-8")
    expected_frequency = str(manifest["outputs"]["history_frequency"])
    diagnostic_lines = [
        line.split(":", 1)[1].strip()
        for line in hemco_config.splitlines()
        if line.startswith("DiagnFreq:")
    ]
    if diagnostic_lines != [expected_frequency]:
        raise ValueError(
            f"HEMCO DiagnFreq {diagnostic_lines} != checked {expected_frequency!r}"
        )

    with (run_directory / "plume_source_validation.json").open(encoding="utf-8") as handle:
        source_validation = json.load(handle)
    if source_validation.get("status") != "pass":
        raise ValueError("checked source validation report does not have pass status")
    if source_validation.get("source_sha256") != expected_hashes["generated_source_sha256"]:
        raise ValueError("checked source validation report refers to a different source")
    return actual


def validate_source_contract(
    source_path: Path,
    summary_path: Path,
    manifest: dict,
    expected_mass: float,
    duration_s: float,
    profile_tolerance: float,
    mass_tolerance: float,
) -> tuple[dict[str, list[float]], dict[str, np.ndarray], dict]:
    checked_hash = manifest["artifact_hashes"]["generated_source_sha256"]
    actual_hash = sha256(source_path)
    if actual_hash != checked_hash:
        raise ValueError(f"source SHA-256 {actual_hash} != checked {checked_hash}")
    with summary_path.open(encoding="utf-8") as handle:
        summary = json.load(handle)
    if summary.get("case_id") != manifest["case_id"]:
        raise ValueError("source summary case_id does not match manifest")
    if Path(summary["source_file"]).resolve() != source_path:
        raise ValueError("source summary path does not match checked source path")
    if summary.get("source_file_sha256") != actual_hash:
        raise ValueError("source summary SHA-256 does not match checked source")
    if not math.isclose(float(summary["duration_s"]), duration_s, rel_tol=0.0, abs_tol=0.0):
        raise ValueError("source summary duration does not match manifest")

    source = manifest["source"]
    source_j = int(source["cell_index_zero_based"]["j"])
    source_i = int(source["cell_index_zero_based"]["i"])
    if summary["source_cell_zero_based"] != {"j": source_j, "i": source_i}:
        raise ValueError("source summary cell indices do not match manifest")
    expected_center = source["cell_center"]
    for key in ("latitude_degrees_north", "longitude_degrees_east"):
        if not math.isclose(
            float(summary["source_cell_center"][key]),
            float(expected_center[key]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError(f"source summary {key} does not match manifest")
    if not math.isclose(
        float(summary["source_cell_area_m2"]),
        float(source["cell_area_m2"]),
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise ValueError("source summary area does not match manifest")

    with netcdf_file(source_path, "r", mmap=False) as dataset:
        reference = {
            name: np.asarray(dataset.variables[name].data, dtype=np.float64).copy()
            for name in ("lat", "lon", "lev")
        }
        if len(reference["lev"]) != int(manifest["grid"]["levels"]):
            raise ValueError("source level count does not match manifest")
        if not math.isclose(
            float(reference["lat"][source_j]),
            float(expected_center["latitude_degrees_north"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ) or not math.isclose(
            float(reference["lon"][source_i]),
            float(expected_center["longitude_degrees_east"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("source coordinate grid does not contain the manifest source cell")
        expected_profiles: dict[str, list[float]] = {}
        for tag in TAGS:
            variable = dataset.variables[f"weight_{tag}"]
            if tuple(variable.dimensions) != ("lev", "lat", "lon"):
                raise ValueError(f"weight_{tag}: unexpected dimensions {variable.dimensions}")
            field = np.asarray(variable.data, dtype=np.float64)
            require_source_cell_only(field, source_j, source_i, f"weight_{tag}")
            weights = field[:, source_j, source_i]
            if np.any(~np.isfinite(weights)) or np.any(weights < 0.0):
                raise ValueError(f"weight_{tag}: invalid profile weights")
            if abs(float(weights.sum(dtype=np.float64)) - 1.0) > profile_tolerance:
                raise ValueError(f"weight_{tag}: profile does not sum to one")
            expected_profiles[tag] = weights.tolist()

    expected_keys = set(TAGS)
    for key in ("profile_sums", "profile_weights", "integrated_mass_kg"):
        if set(summary[key]) != expected_keys:
            raise ValueError(f"source summary {key} does not contain exactly the checked tags")
    for tag in TAGS:
        summary_weights = np.asarray(summary["profile_weights"][tag], dtype=np.float64)
        source_weights = np.asarray(expected_profiles[tag], dtype=np.float64)
        if summary_weights.shape != source_weights.shape or np.any(~np.isfinite(summary_weights)):
            raise ValueError(f"source summary {tag} profile is invalid")
        if float(np.max(np.abs(summary_weights - source_weights))) > profile_tolerance:
            raise ValueError(f"source summary {tag} profile differs from checked source")
        summary_profile_sum = finite_scalar(
            summary["profile_sums"][tag], f"source summary {tag} profile sum"
        )
        if abs(summary_profile_sum - 1.0) > profile_tolerance:
            raise ValueError(f"source summary {tag} profile sum is invalid")
        summary_mass = finite_scalar(
            summary["integrated_mass_kg"][tag],
            f"source summary {tag} integrated mass",
            positive=True,
        )
        if relative_error(summary_mass, expected_mass) > mass_tolerance:
            raise ValueError(f"source summary {tag} integrated mass is invalid")
    return expected_profiles, reference, {
        "path": str(source_path),
        "sha256": actual_hash,
        "summary": str(summary_path),
        "summary_sha256": sha256(summary_path),
    }


def unique_default(run_directory: Path, pattern: str, label: str) -> Path:
    matches = sorted(run_directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {label} matching {pattern} in {run_directory}, "
            f"found {len(matches)}"
        )
    return matches[0]


def relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / abs(expected)


def require_source_cell_only(
    values: np.ndarray,
    source_j: int,
    source_i: int,
    label: str,
) -> float:
    """Require exact zero outside one horizontal cell and return the max."""
    outside = values.copy()
    outside[..., source_j, source_i] = 0.0
    outside_max = float(np.max(np.abs(outside)))
    if outside_max != 0.0:
        raise ValueError(f"{label}: nonzero value outside the source cell ({outside_max})")
    return outside_max


def validate_budget(
    path: Path,
    expected_mass: float,
    duration_s: float,
    tolerance: float,
    source_j: int,
    source_i: int,
    reference: dict[str, np.ndarray],
    run_start: datetime,
    run_end: datetime,
) -> dict[str, dict]:
    checks: dict[str, dict] = {}
    with h5py.File(path, "r") as dataset:
        require_time_reference(dataset, run_start, "minutes", "Budget diagnostic")
        require_coordinates(dataset, reference, "Budget diagnostic", include_lev=False)
        require_dimensions(dataset["AREA"], ("lat", "lon"))
        if text_attribute(dataset["AREA"], "units") != "m2":
            raise ValueError("Budget diagnostic AREA units are not m2")
        area = read_array(dataset, "AREA")
        if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
            raise ValueError("Budget diagnostic contains invalid grid-box areas")
        expected_start = run_start.strftime("%Y-%m-%d %H:%M:%Sz")
        expected_end = run_end.strftime("%Y-%m-%d %H:%M:%Sz")
        if text_attribute(dataset, "simulation_start_date_and_time") != expected_start:
            raise ValueError("Budget diagnostic start time does not match manifest")
        if text_attribute(dataset, "simulation_end_date_and_time") != expected_end:
            raise ValueError("Budget diagnostic end time does not match manifest")
        for tag in TAGS:
            name = f"BudgetEmisDryDepFull_{tag}"
            rate = read_array(dataset, name)
            variable = dataset[name]
            require_dimensions(variable, ("time", "lat", "lon"))
            units = text_attribute(variable, "units")
            if units != "kg s-1":
                raise ValueError(f"{name}: expected units 'kg s-1', got {units!r}")
            if text_attribute(variable, "averaging_method") != "time-averaged":
                raise ValueError(f"{name}: Budget field is not a time average")
            if rate.shape[0] != 1 or np.any(~np.isfinite(rate)) or np.any(rate < 0.0):
                raise ValueError(f"{name}: invalid source-only budget values")
            outside_max = require_source_cell_only(
                rate[0], source_j, source_i, f"{name} budget"
            )
            integrated_mass = float(rate[0].sum(dtype=np.float64) * duration_s)
            error = relative_error(integrated_mass, expected_mass)
            if error > tolerance:
                raise ValueError(
                    f"{name}: integrated budget {integrated_mass:.12g} kg differs from "
                    f"{expected_mass} kg by {error:.3e}"
                )
            checks[tag] = {
                "mean_rate_kg_s": float(rate[0].sum(dtype=np.float64)),
                "integrated_mass_kg": integrated_mass,
                "relative_mass_error": error,
                "outside_source_cell_max_kg_s": outside_max,
            }
    return checks


def validate_hemco(
    path: Path,
    expected_mass: float,
    duration_s: float,
    mass_tolerance: float,
    profile_tolerance: float,
    source_j: int,
    source_i: int,
    expected_profiles: dict[str, list[float]],
    reference: dict[str, np.ndarray],
    run_start: datetime,
    expected_area: float,
) -> dict[str, dict]:
    checks: dict[str, dict] = {}
    with h5py.File(path, "r") as dataset:
        require_time_reference(dataset, run_start, "hours", "HEMCO diagnostic")
        require_coordinates(dataset, reference, "HEMCO diagnostic", include_lev=True)
        require_dimensions(dataset["AREA"], ("lat", "lon"))
        if text_attribute(dataset["AREA"], "units") != "m2":
            raise ValueError("HEMCO diagnostic AREA units are not m2")
        area = read_array(dataset, "AREA")
        if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
            raise ValueError("HEMCO diagnostic contains invalid grid-box areas")
        if relative_error(float(area[source_j, source_i]), expected_area) > 1.0e-7:
            raise ValueError("HEMCO source-cell area differs from the checked source area")
        for tag in TAGS:
            name = f"Emis{tag}"
            rate = read_array(dataset, name)
            variable = dataset[name]
            require_dimensions(variable, ("time", "lev", "lat", "lon"))
            units = text_attribute(variable, "units")
            if units not in {"kg/m2/s", "kg m-2 s-1"}:
                raise ValueError(f"{name}: unexpected units {units!r}")
            if text_attribute(variable, "averaging_method") != "mean":
                raise ValueError(f"{name}: HEMCO field is not a time mean")
            if rate.shape[0] != 1 or np.any(~np.isfinite(rate)) or np.any(rate < 0.0):
                raise ValueError(f"{name}: invalid HEMCO diagnostic values")
            outside_max = require_source_cell_only(
                rate[0], source_j, source_i, f"{name} HEMCO diagnostic"
            )
            layer_mass = rate[0, :, source_j, source_i] * area[source_j, source_i] * duration_s
            integrated_mass = float(layer_mass.sum(dtype=np.float64))
            error = relative_error(integrated_mass, expected_mass)
            if error > mass_tolerance:
                raise ValueError(
                    f"{name}: integrated HEMCO source {integrated_mass:.12g} kg differs "
                    f"from {expected_mass} kg by {error:.3e}"
                )
            profile = layer_mass / integrated_mass
            expected = np.asarray(expected_profiles[tag], dtype=np.float64)
            profile_error = float(np.max(np.abs(profile - expected)))
            if profile_error > profile_tolerance:
                raise ValueError(f"{name}: HEMCO layer profile mismatch {profile_error:.3e}")
            checks[tag] = {
                "integrated_mass_kg": integrated_mass,
                "relative_mass_error": error,
                "profile_max_abs_error": profile_error,
                "outside_source_cell_max_kg_m2_s": outside_max,
            }
    return checks


def validate_endpoint_restart(
    path: Path,
    expected_mass: float,
    burden_tolerance: float,
    profile_tolerance: float,
    nonnegative_floor_kg: float,
    source_j: int,
    source_i: int,
    mw_species: float,
    expected_profiles: dict[str, list[float]],
    reference: dict[str, np.ndarray],
    run_end: datetime,
    expected_area: float,
) -> dict[str, dict]:
    checks: dict[str, dict] = {}
    with h5py.File(path, "r") as dataset:
        require_time_reference(dataset, run_end, "minutes", "end restart")
        require_coordinates(dataset, reference, "end restart", include_lev=True)
        require_dimensions(dataset["AREA"], ("lat", "lon"))
        require_dimensions(dataset["Met_DELPDRY"], ("time", "lev", "lat", "lon"))
        if text_attribute(dataset["AREA"], "units") != "m2":
            raise ValueError("end-restart AREA units are not m2")
        if text_attribute(dataset["Met_DELPDRY"], "units") != "hPa":
            raise ValueError("end-restart Met_DELPDRY units are not hPa")
        area = read_array(dataset, "AREA")
        if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
            raise ValueError("end restart contains invalid grid-box areas")
        if not math.isclose(
            float(area[source_j, source_i]), expected_area, rel_tol=0.0, abs_tol=0.0
        ):
            raise ValueError("end-restart source-cell area differs from manifest")
        delp = read_array(dataset, "Met_DELPDRY")[0]
        if np.any(~np.isfinite(delp)) or np.any(delp <= 0.0):
            raise ValueError("end restart contains invalid Met_DELPDRY")
        dry_air_mass = delp * 100.0 * area[np.newaxis, :, :] / G0_M_S2

        for tag in TAGS:
            name = f"SpeciesRst_{tag}"
            variable = dataset[name]
            require_dimensions(variable, ("time", "lev", "lat", "lon"))
            if text_attribute(variable, "units") != "mol mol-1 dry":
                raise ValueError(f"{name}: unexpected units")
            if text_attribute(variable, "averaging_method") != "instantaneous":
                raise ValueError(f"{name}: restart field is not instantaneous")
            mixing_ratio = read_array(dataset, name)[0]
            if np.any(~np.isfinite(mixing_ratio)):
                raise ValueError(f"{tag}: restart contains non-finite mixing ratios")
            mass = mixing_ratio * dry_air_mass * (mw_species / AIR_MW_G_MOL)
            if float(mass.min()) < -nonnegative_floor_kg:
                raise ValueError(f"{tag}: restart contains mass below the nonnegative floor")
            outside_max = require_source_cell_only(
                mass, source_j, source_i, f"{tag} end-restart mass"
            )
            burden = float(mass.sum(dtype=np.float64))
            burden_error = relative_error(burden, expected_mass)
            if burden_error > burden_tolerance:
                raise ValueError(
                    f"{tag}: endpoint burden {burden:.12g} kg differs from "
                    f"{expected_mass} kg by {burden_error:.3e}"
                )

            layer_mass = mass[:, source_j, source_i]
            layer_weights = layer_mass / layer_mass.sum(dtype=np.float64)
            expected = np.asarray(expected_profiles[tag], dtype=np.float64)
            profile_error = float(np.max(np.abs(layer_weights - expected)))
            if profile_error > profile_tolerance:
                raise ValueError(f"{tag}: endpoint layer-profile mismatch {profile_error:.3e}")

            checks[tag] = {
                "burden_kg": burden,
                "relative_burden_error": burden_error,
                "source_column_mass_kg": float(layer_mass.sum(dtype=np.float64)),
                "outside_source_cell_max_kg": outside_max,
                "profile_max_abs_error": profile_error,
            }
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("restart", type=Path)
    parser.add_argument("--source-summary", type=Path)
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--hemco-diagnostics", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    with args.manifest.open(encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    if tuple(manifest["source"]["tags"]) != TAGS:
        raise ValueError(f"manifest tags must be exactly {TAGS}")
    run_directory = Path(manifest["paths"]["run_directory"]).resolve()
    restart_path = args.restart.resolve()
    if restart_path.parent != run_directory / "Restarts":
        raise ValueError("end restart is not in the manifest-declared run directory")
    summary_path = (
        args.source_summary or run_directory / str(manifest["outputs"]["source_summary"])
    ).resolve()
    expected_summary = (run_directory / str(manifest["outputs"]["source_summary"])).resolve()
    if summary_path != expected_summary:
        raise ValueError("source summary is not the manifest-declared run artifact")
    source_path = Path(manifest["paths"]["generated_source"]).resolve()
    if source_path.parent != run_directory:
        raise ValueError("generated source is not in the manifest-declared run directory")
    budget_path = args.budget or unique_default(
        run_directory / "OutputDir", "GEOSChem.Budget.*.nc4", "Budget diagnostic"
    )
    hemco_path = args.hemco_diagnostics or unique_default(
        run_directory / "OutputDir", "HEMCO_diagnostics.*.nc", "HEMCO diagnostic"
    )
    budget_path = budget_path.resolve()
    hemco_path = hemco_path.resolve()
    if budget_path.parent != run_directory / "OutputDir":
        raise ValueError("Budget diagnostic is not in the declared run OutputDir")
    if hemco_path.parent != run_directory / "OutputDir":
        raise ValueError("HEMCO diagnostic is not in the declared run OutputDir")

    acceptance = manifest["acceptance"]
    contract_version = str(acceptance["contract_version"])
    if contract_version != CONTRACT_VERSION:
        raise ValueError(
            f"validator requires acceptance contract {CONTRACT_VERSION}, got {contract_version}"
        )
    expected_mass = finite_scalar(
        manifest["source"]["total_mass_per_tag_kg"], "source mass", positive=True
    )
    duration_s = finite_scalar(manifest["source"]["duration_s"], "source duration", positive=True)
    run_start = parse_utc(manifest["run"]["start"])
    run_end = parse_utc(manifest["run"]["end"])
    run_duration_s = (run_end - run_start).total_seconds()
    if not math.isfinite(run_duration_s) or run_duration_s <= 0.0:
        raise ValueError("manifest run interval must be finite and positive")
    expected_restart_name = f"GEOSChem.Restart.{run_end.strftime('%Y%m%d_%H%M')}z.nc4"
    if restart_path.name != expected_restart_name:
        raise ValueError(
            f"end restart name {restart_path.name!r} != manifest end {expected_restart_name!r}"
        )
    if not math.isclose(duration_s, run_duration_s, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError(
            "V0 full-run mean Budget integration requires source duration to equal run duration"
        )
    analytic_profile_tolerance = finite_scalar(
        acceptance["profile_sum_absolute"], "analytic profile tolerance"
    )
    analytic_mass_tolerance = finite_scalar(
        acceptance["source_flux_to_mass_relative"], "analytic source-mass tolerance"
    )
    ledger_tolerance = finite_scalar(
        acceptance["model_source_ledger_relative"], "model source-ledger tolerance"
    )
    model_profile_tolerance = finite_scalar(
        acceptance["model_source_profile_absolute"], "model source-profile tolerance"
    )
    burden_tolerance = finite_scalar(
        acceptance["endpoint_restart_burden_relative"], "endpoint burden tolerance"
    )
    profile_tolerance = finite_scalar(
        acceptance["endpoint_restart_profile_absolute"], "endpoint profile tolerance"
    )
    nonnegative_floor_kg = finite_scalar(
        acceptance["nonnegative_floor_kg"], "nonnegative floor"
    )
    source_j = int(manifest["source"]["cell_index_zero_based"]["j"])
    source_i = int(manifest["source"]["cell_index_zero_based"]["i"])
    if source_j < 0 or source_i < 0:
        raise ValueError("source indices must be non-negative")
    mw_species = finite_scalar(
        manifest["species"]["molecular_weight_g_mol"], "species molecular weight", positive=True
    )
    expected_area = finite_scalar(
        manifest["source"]["cell_area_m2"], "source-cell area", positive=True
    )

    checked_inputs = validate_checked_inputs(run_directory, manifest)
    expected_profiles, reference, source_evidence = validate_source_contract(
        source_path,
        summary_path,
        manifest,
        expected_mass,
        duration_s,
        analytic_profile_tolerance,
        analytic_mass_tolerance,
    )
    if source_j >= len(reference["lat"]) or source_i >= len(reference["lon"]):
        raise ValueError("source indices lie outside the checked source grid")

    budget_checks = validate_budget(
        budget_path,
        expected_mass,
        duration_s,
        ledger_tolerance,
        source_j,
        source_i,
        reference,
        run_start,
        run_end,
    )
    hemco_checks = validate_hemco(
        hemco_path,
        expected_mass,
        duration_s,
        ledger_tolerance,
        model_profile_tolerance,
        source_j,
        source_i,
        expected_profiles,
        reference,
        run_start,
        expected_area,
    )
    endpoint_checks = validate_endpoint_restart(
        restart_path,
        expected_mass,
        burden_tolerance,
        profile_tolerance,
        nonnegative_floor_kg,
        source_j,
        source_i,
        mw_species,
        expected_profiles,
        reference,
        run_end,
        expected_area,
    )

    for label, checks, tolerance in (
        ("Budget", budget_checks, ledger_tolerance),
        ("HEMCO", hemco_checks, ledger_tolerance),
        ("endpoint restart", endpoint_checks, burden_tolerance),
    ):
        masses = np.asarray(
            [
                checks[tag]["integrated_mass_kg"]
                if "integrated_mass_kg" in checks[tag]
                else checks[tag]["burden_kg"]
                for tag in TAGS
            ]
        )
        spread = float((masses.max() - masses.min()) / expected_mass)
        if spread > tolerance:
            raise ValueError(f"{label} tag masses disagree by {spread:.3e}")

    budget_masses = np.asarray([budget_checks[tag]["integrated_mass_kg"] for tag in TAGS])
    hemco_masses = np.asarray([hemco_checks[tag]["integrated_mass_kg"] for tag in TAGS])
    endpoint_masses = np.asarray([endpoint_checks[tag]["burden_kg"] for tag in TAGS])
    report = {
        "status": "pass",
        "case_id": manifest["case_id"],
        "acceptance_contract": contract_version,
        "manifest": str(args.manifest.resolve()),
        "validation_input_manifest_sha256": sha256(args.manifest),
        "run_directory": str(run_directory),
        "run_interval": {
            "start": run_start.isoformat(),
            "end": run_end.isoformat(),
            "duration_s": run_duration_s,
        },
        "expected_mass_per_tag_kg": expected_mass,
        "source_cell_zero_based": {"j": source_j, "i": source_i},
        "source_cell_center": manifest["source"]["cell_center"],
        "source": source_evidence,
        "checked_input_hashes": checked_inputs,
        "interpretation": {
            "authoritative_conservation_ledgers": ["HEMCO", "Budget"],
            "endpoint_restart": (
                "secondary proxy using endpoint Met_DELPDRY; transport and pressure reset "
                "are disabled in V0, so emitted mixing ratios are not endpoint-pressure-rescaled"
            ),
        },
        "restart": str(restart_path),
        "restart_sha256": sha256(restart_path),
        "budget": str(budget_path.resolve()),
        "budget_sha256": sha256(budget_path),
        "hemco_diagnostics": str(hemco_path.resolve()),
        "hemco_diagnostics_sha256": sha256(hemco_path),
        "source_duration_s": duration_s,
        "tolerances": {
            "model_source_ledger_relative": ledger_tolerance,
            "model_source_profile_absolute": model_profile_tolerance,
            "endpoint_restart_burden_relative": burden_tolerance,
            "endpoint_restart_profile_absolute": profile_tolerance,
            "nonnegative_floor_kg": nonnegative_floor_kg,
        },
        "budget_equal_tag_relative_spread": float(
            (budget_masses.max() - budget_masses.min()) / expected_mass
        ),
        "hemco_equal_tag_relative_spread": float(
            (hemco_masses.max() - hemco_masses.min()) / expected_mass
        ),
        "endpoint_equal_tag_relative_spread": float(
            (endpoint_masses.max() - endpoint_masses.min()) / expected_mass
        ),
        "max_budget_relative_mass_error": max(
            budget_checks[tag]["relative_mass_error"] for tag in TAGS
        ),
        "max_hemco_relative_mass_error": max(
            hemco_checks[tag]["relative_mass_error"] for tag in TAGS
        ),
        "max_hemco_profile_abs_error": max(
            hemco_checks[tag]["profile_max_abs_error"] for tag in TAGS
        ),
        "max_endpoint_relative_burden_error": max(
            endpoint_checks[tag]["relative_burden_error"] for tag in TAGS
        ),
        "max_endpoint_profile_abs_error": max(
            endpoint_checks[tag]["profile_max_abs_error"] for tag in TAGS
        ),
        "budget_checks": budget_checks,
        "hemco_checks": hemco_checks,
        "endpoint_restart_checks": endpoint_checks,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
