#!/usr/bin/env python3
"""Validate the frozen Stage-1 source-plus-TPCORE checkpoint contract."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path

import h5py
import numpy as np
import yaml
from scipy.io import netcdf_file

from manifest_utils import load_manifest

TAGS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")
AIR_MW_G_MOL = 28.9644
G0_M_S2 = 9.80665
CONTRACT_VERSION = "stage1-tpcore-ledger-v1"
CHECKPOINT_SCHEMA_VERSION = "plume-checkpoint-v1"
CHECKPOINTS = (
    (0, "C0_PRE_TPCORE", 0),
    (1, "C1_POST_TPCORE", 600),
    (2, "C2_FLUX_READY", 600),
    (3, "C3_POST_MIXING", 600),
    (4, "C4_POST_CONVECTION", 600),
    (5, "C5_POST_CHEMISTRY", 600),
    (6, "C6_POST_WETDEP", 600),
)
INACTIVE_TRANSITIONS = (
    ("C1_POST_TPCORE", "C2_FLUX_READY"),
    ("C3_POST_MIXING", "C4_POST_CONVECTION"),
    ("C4_POST_CONVECTION", "C5_POST_CHEMISTRY"),
    ("C5_POST_CHEMISTRY", "C6_POST_WETDEP"),
)


@dataclass(frozen=True)
class Checkpoint:
    path: Path
    sha256: str
    area: np.ndarray
    dry_air_mass: np.ndarray
    delp_dry: np.ndarray
    mass: dict[str, np.ndarray]
    global_mass: dict[str, float]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_array(dataset: h5py.File, name: str) -> np.ndarray:
    if name not in dataset:
        raise KeyError(f"dataset is missing {name}")
    return np.asarray(dataset[name][:], dtype=np.float64)


def text_attribute(variable: h5py.File | h5py.Dataset, name: str) -> str:
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
        scales = list(dimension.items())
        if len(scales) == 1:
            name, scale = scales[0]
            if name.startswith(
                "This is a netCDF dimension but not a netCDF variable."
            ):
                dim_id = int(scale.attrs.get("_Netcdf4Dimid", -1))
                scale_name = scale.name.rsplit("/", 1)[-1]
                if (
                    dim_id == 3
                    and scale.shape == (len(TAGS),)
                    and scale_name == "tag"
                ):
                    name = "tag"
                else:
                    raise ValueError(
                        f"{variable.name}: unsupported unnamed netCDF dimension "
                        f"name={scale_name!r}, id={dim_id}, shape={scale.shape}"
                    )
            names.append(name)
            continue

        # A netCDF coordinate variable is itself the dimension scale, so h5py
        # exposes no attached scale on its sole axis.  Recover its dimension
        # name from the standard HDF5 dimension-scale metadata.
        class_value = variable.attrs.get("CLASS")
        scale_name = variable.attrs.get("NAME")
        if (
            len(scales) == 0
            and variable.ndim == 1
            and class_value == b"DIMENSION_SCALE"
            and scale_name is not None
        ):
            if isinstance(scale_name, bytes):
                scale_name = scale_name.decode("utf-8")
            names.append(str(scale_name))
            continue

        if len(scales) != 1:
            raise ValueError(
                f"{variable.name}: expected one netCDF dimension scale, "
                f"got {[name for name, _ in scales]}"
            )
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


def relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / abs(expected)


def require_source_cell_only(
    values: np.ndarray,
    source_j: int,
    source_i: int,
    label: str,
) -> float:
    outside = values.copy()
    outside[..., source_j, source_i] = 0.0
    outside_max = float(np.max(np.abs(outside)))
    if outside_max != 0.0:
        raise ValueError(f"{label}: nonzero value outside source cell ({outside_max})")
    return outside_max


def unique_default(run_directory: Path, pattern: str, label: str) -> Path:
    matches = sorted(run_directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {label} matching {pattern} in {run_directory}, "
            f"found {len(matches)}"
        )
    return matches[0]


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
    realization_timestep_s: float,
) -> tuple[dict[str, dict], dict[str, np.ndarray], dict[str, object]]:
    checks: dict[str, dict] = {}
    realized_increment: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as dataset:
        require_time_reference(dataset, run_start, "hours", "HEMCO diagnostic")
        require_coordinates(dataset, reference, "HEMCO diagnostic", include_lev=True)
        require_dimensions(dataset["AREA"], ("lat", "lon"))
        if text_attribute(dataset["AREA"], "units") != "m2":
            raise ValueError("HEMCO diagnostic AREA units are not m2")
        area = read_array(dataset, "AREA")
        area_dtype = str(dataset["AREA"].dtype)
        if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
            raise ValueError("HEMCO diagnostic contains invalid grid-box areas")
        if relative_error(float(area[source_j, source_i]), expected_area) > 1.0e-7:
            raise ValueError("HEMCO source-cell area differs from checked source area")
        for tag in TAGS:
            name = f"Emis{tag}"
            rate = read_array(dataset, name)
            variable = dataset[name]
            rate_dtype = str(variable.dtype)
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
            layer_mass = (
                rate[0, :, source_j, source_i]
                * area[source_j, source_i]
                * duration_s
            )
            integrated_mass = float(layer_mass.sum(dtype=np.float64))
            error = relative_error(integrated_mass, expected_mass)
            if error > mass_tolerance:
                raise ValueError(f"{name}: integrated HEMCO source differs from contract")
            profile = layer_mass / integrated_mass
            expected = np.asarray(expected_profiles[tag], dtype=np.float64)
            profile_error = float(np.max(np.abs(profile - expected)))
            if profile_error > profile_tolerance:
                raise ValueError(f"{name}: HEMCO layer profile mismatch")
            increment = rate[0] * area[np.newaxis, :, :] * realization_timestep_s
            realized_increment[tag] = increment
            checks[tag] = {
                "integrated_mass_kg": integrated_mass,
                "realized_increment_per_heartbeat_kg": float(
                    increment.sum(dtype=np.float64)
                ),
                "relative_mass_error": error,
                "profile_max_abs_error": profile_error,
                "outside_source_cell_max_kg_m2_s": outside_max,
                "stored_rate_dtype": rate_dtype,
            }
    realization_metadata: dict[str, object] = {
        "area_dtype": area_dtype,
        "source_cell_area_m2": float(area[source_j, source_i]),
        "realization_timestep_s": realization_timestep_s,
        "basis": (
            "stored HEMCO diagnostic rate promoted to float64, multiplied by "
            "the diagnostic float64 AREA and the native heartbeat duration"
        ),
    }
    return checks, realized_increment, realization_metadata


def require_float64(variable: h5py.Dataset, label: str) -> None:
    dtype = np.dtype(variable.dtype)
    if dtype.kind != "f" or dtype.itemsize != 8:
        raise ValueError(f"{label}: expected float64, got {dtype}")


def scalar_attribute(container: h5py.File | h5py.Dataset, name: str) -> object:
    if name not in container.attrs:
        raise KeyError(f"{container.name} is missing the {name} attribute")
    value = container.attrs[name]
    if isinstance(value, np.ndarray):
        if value.size != 1:
            raise ValueError(f"{container.name}: {name} is not scalar")
        value = value.reshape(()).item()
    elif isinstance(value, np.generic):
        value = value.item()
    return value


def integer_attribute(container: h5py.File, name: str) -> int:
    value = scalar_attribute(container, name)
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{container.name}: {name} must be an integer")
    result = int(value)
    if float(value) != float(result):
        raise ValueError(f"{container.name}: {name} is not integral")
    return result


def relative_difference(actual: float, reference: float, floor: float) -> float:
    return abs(actual - reference) / max(abs(reference), floor)


def relative_l1(actual: np.ndarray, reference: np.ndarray, floor: float) -> float:
    if actual.shape != reference.shape:
        raise ValueError(f"array shape mismatch: {actual.shape} != {reference.shape}")
    difference = float(np.abs(actual - reference).sum(dtype=np.float64))
    denominator = max(float(np.abs(reference).sum(dtype=np.float64)), floor)
    return difference / denominator


def max_abs_difference(actual: np.ndarray, reference: np.ndarray) -> float:
    if actual.shape != reference.shape:
        raise ValueError(f"array shape mismatch: {actual.shape} != {reference.shape}")
    return float(np.max(np.abs(actual - reference)))


def require_exact_array(actual: np.ndarray, reference: np.ndarray, label: str) -> None:
    if actual.shape != reference.shape or not np.array_equal(actual, reference):
        difference = max_abs_difference(actual, reference)
        raise ValueError(f"{label}: inactive increment is not exactly zero ({difference})")


def checked_path(path: Path, parent: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved.parent != parent:
        raise ValueError(f"{label} is not in {parent}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def validate_operator_and_checkpoint_contract(manifest: dict) -> None:
    run = manifest["run"]
    expected_operators = {
        "chemistry": True,
        "transport": True,
        "native_tpcore": True,
        "native_pjc_pressure_fix_and_airmass_reset": True,
        "transport_fill_negative_values": True,
        "transport_orders_i_j_k": [3, 3, 7],
        "pbl_turbulence": False,
        "convection": False,
        "dry_deposition": False,
        "wet_deposition": False,
        "settling": False,
        "aging": False,
        "native_do_tend": True,
    }
    if run["operators"] != expected_operators:
        raise ValueError("manifest operator switches differ from the frozen TPCORE case")
    if int(run["expected_dynamic_heartbeats"]) != 2:
        raise ValueError("TPCORE contract requires exactly two dynamic heartbeats")

    runtime = manifest["checkpoint_runtime"]
    if runtime["enabled"] is not True:
        raise ValueError("checkpoint runtime must be enabled")
    if str(runtime["schema_version"]) != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("manifest checkpoint schema version is not supported")
    if int(runtime["expected_files"]) != 14:
        raise ValueError("checkpoint contract requires exactly 14 files")
    environment = runtime["environment"]
    expected_environment = {
        "GC_PLUME_CHECKPOINTS": "1",
        "GC_PLUME_CHECKPOINT_DIR": "./OutputDir/PlumeCheckpoints",
        "GC_PLUME_CHECKPOINT_RUN_ID": str(manifest["case_id"]),
    }
    if environment != expected_environment:
        raise ValueError("checkpoint environment differs from the frozen contract")

    declared = runtime["checkpoints_per_heartbeat"]
    if len(declared) != len(CHECKPOINTS):
        raise ValueError("manifest checkpoint schedule must contain C0 through C6")
    for item, (checkpoint_id, label, offset) in zip(declared, CHECKPOINTS, strict=True):
        if (
            int(item["id"]) != checkpoint_id
            or str(item["label"]) != label
            or int(item["state_time_offset_s"]) != offset
        ):
            raise ValueError("manifest checkpoint order, labels, or offsets differ")

    required_variables = {
        "lon",
        "lat",
        "lev",
        "grid_cell_area",
        "dry_air_mass",
        "Met_DELPDRY",
        "tag_id",
        "global_plume_mass",
        *(f"PlumeMass_{tag}" for tag in TAGS),
    }
    if set(runtime["required_variables"]) != required_variables:
        raise ValueError("manifest checkpoint required-variable set differs")
    required_attributes = {
        "schema_version",
        "run_id",
        "checkpoint_label",
        "checkpoint_id",
        "model_date",
        "model_time",
        "heartbeat_index",
        "elapsed_seconds",
        "state_time_offset_seconds",
        "transport_active",
        "transport_timestep_seconds",
        "emissions_timestep_seconds",
        "chemistry_timestep_seconds",
        "tracer_state_units",
        "mass_formula",
    }
    if set(runtime["required_global_attributes"]) != required_attributes:
        raise ValueError("manifest checkpoint required-attribute set differs")


def validate_extdata_inventory(manifest: dict) -> dict[str, dict[str, object]]:
    inventory = manifest["extdata_inventory"]
    if inventory["path_inventory_complete"] is not True:
        raise ValueError("ExtData path inventory is not marked complete")
    if inventory["hashes_complete"] is not True:
        raise ValueError("ExtData hash inventory is not marked complete")
    files = inventory["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("ExtData inventory must be a non-empty role mapping")

    observed_paths: set[Path] = set()
    checked: dict[str, dict[str, object]] = {}
    for key, record in files.items():
        if not isinstance(record, dict):
            raise ValueError(f"ExtData entry {key} is not a mapping")
        role = str(record["role"]).strip()
        raw_path = Path(record["path"])
        if not role:
            raise ValueError(f"ExtData entry {key} has an empty role")
        if not raw_path.is_absolute():
            raise ValueError(f"ExtData entry {key} is not an absolute path")
        path = raw_path.resolve()
        if path in observed_paths:
            raise ValueError(f"ExtData path is duplicated: {path}")
        observed_paths.add(path)
        if not path.is_file():
            raise FileNotFoundError(f"ExtData input is absent: {path}")
        expected_size = int(record["size_bytes_observed"])
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise ValueError(
                f"{path}: size {actual_size} differs from checked {expected_size}"
            )
        digest = sha256(path)
        if digest != str(record["sha256"]):
            raise ValueError(f"{path}: SHA-256 {digest} differs from checked hash")
        checked[str(key)] = {
            "role": role,
            "path": str(path),
            "size_bytes": actual_size,
            "sha256": digest,
        }
    return checked


def validate_checked_inputs(
    run_directory: Path,
    manifest: dict,
    *,
    require_executable: bool = True,
) -> dict:
    artifact_hashes = manifest["artifact_hashes"]
    source = checked_path(
        Path(manifest["paths"]["generated_source"]), run_directory, "generated source"
    )
    initial_restart = checked_path(
        Path(manifest["paths"]["generated_restart"]),
        run_directory / "Restarts",
        "generated initial restart",
    )
    repository = Path(__file__).resolve().parents[1]
    checks = {
        "generated_source_sha256": source,
        "generated_restart_sha256": initial_restart,
        "geoschem_config_sha256": run_directory / "geoschem_config.yml",
        "hemco_config_sha256": run_directory / "HEMCO_Config.rc",
        "hemco_met_config_sha256": run_directory / "HEMCO_Config.rc.gmao_metfields",
        "hemco_diagn_sha256": run_directory / "HEMCO_Diagn.rc",
        "history_rc_sha256": run_directory / "HISTORY.rc",
        "species_database_sha256": run_directory / "species_database.yml",
        "source_validation_report_sha256": run_directory / "plume_source_validation.json",
        "checkpoint_module_sha256": (
            repository
            / "src/GEOS-Chem/Interfaces/GCClassic/plume_checkpoint_mod.F90"
        ),
        "checkpoint_validator_sha256": Path(__file__).resolve(),
    }
    actual_hashes: dict[str, str] = {}
    for key, path in checks.items():
        if not path.is_file():
            raise FileNotFoundError(f"controlled input is absent: {path}")
        digest = sha256(path)
        if digest != str(artifact_hashes[key]):
            raise ValueError(f"{path}: SHA-256 {digest} differs from checked {key}")
        actual_hashes[key] = digest

    expected_source_hash = str(manifest["source"]["expected_sha256"])
    if actual_hashes["generated_source_sha256"] != expected_source_hash:
        raise ValueError("TPCORE source is not byte-identical to the frozen V0 source")
    expected_restart_hash = str(manifest["restart"]["expected_generated_restart_sha256"])
    if actual_hashes["generated_restart_sha256"] != expected_restart_hash:
        raise ValueError("TPCORE initial restart is not byte-identical to the frozen restart")

    with h5py.File(initial_restart, "r") as dataset:
        for tag in TAGS:
            name = f"SpeciesRst_{tag}"
            values = read_array(dataset, name)
            if np.any(~np.isfinite(values)) or np.any(values != 0.0):
                raise ValueError(f"{name}: initial plume field is not exactly zero")

    source_report_path = run_directory / "plume_source_validation.json"
    with source_report_path.open(encoding="utf-8") as handle:
        source_report = json.load(handle)
    if source_report.get("status") != "pass":
        raise ValueError("source validation report does not have pass status")
    if source_report.get("source_sha256") != actual_hashes["generated_source_sha256"]:
        raise ValueError("source validation report refers to a different source")

    hemco_config = (run_directory / "HEMCO_Config.rc").read_text(encoding="utf-8")
    frequencies = [
        line.split(":", 1)[1].strip()
        for line in hemco_config.splitlines()
        if line.startswith("DiagnFreq:")
    ]
    expected_frequency = str(manifest["outputs"]["history_frequency"])
    if frequencies != [expected_frequency]:
        raise ValueError(f"HEMCO diagnostic frequency {frequencies} is not checked")

    if require_executable:
        build = manifest["build"]
        executable = Path(build["executable_path"]).resolve()
        if executable != run_directory / "gcclassic" or not executable.is_file():
            raise ValueError("checked executable is not installed in the run directory")
        executable_hash = sha256(executable)
        if executable_hash != str(build["executable_sha256"]):
            raise ValueError("run-directory executable differs from the manifest")
        actual_hashes["executable_sha256"] = executable_hash

    seed = Path(manifest["restart"]["seed"]).resolve()
    if sha256(seed) != str(manifest["restart"]["seed_sha256"]):
        raise ValueError("seed restart differs from the manifest")
    pblh = Path(manifest["meteorology"]["pblh_file"]).resolve()
    if sha256(pblh) != str(manifest["meteorology"]["pblh_file_sha256"]):
        raise ValueError("profile PBLH input differs from the manifest")

    return {
        "artifact_hashes": actual_hashes,
        "extdata_inventory": validate_extdata_inventory(manifest),
    }


def validate_source(
    source_path: Path,
    manifest: dict,
    transport_timestep_s: float,
    profile_tolerance: float,
    mass_tolerance: float,
    equal_tolerance: float,
) -> tuple[
    dict[str, np.ndarray],
    dict[str, np.ndarray],
    dict,
]:
    expected_mass = float(manifest["source"]["total_mass_per_tag_kg"])
    duration_s = float(manifest["source"]["duration_s"])
    source_j = int(manifest["source"]["cell_index_zero_based"]["j"])
    source_i = int(manifest["source"]["cell_index_zero_based"]["i"])
    source_area = float(manifest["source"]["cell_area_m2"])
    profiles: dict[str, np.ndarray] = {}
    checks: dict[str, dict] = {}

    with netcdf_file(source_path, "r", mmap=False) as dataset:
        reference = {
            name: np.asarray(dataset.variables[name].data, dtype=np.float64).copy()
            for name in ("lat", "lon", "lev")
        }
        if len(reference["lev"]) != int(manifest["grid"]["levels"]):
            raise ValueError("source level count differs from the manifest")
        if source_j >= len(reference["lat"]) or source_i >= len(reference["lon"]):
            raise ValueError("source-cell indices lie outside the source grid")
        center = manifest["source"]["cell_center"]
        if not math.isclose(
            float(reference["lat"][source_j]),
            float(center["latitude_degrees_north"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ) or not math.isclose(
            float(reference["lon"][source_i]),
            float(center["longitude_degrees_east"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("source grid does not contain the declared source cell")
        retained = manifest["source"]["retained_netcdf_metadata"]
        for name in ("case_id", "title"):
            actual = getattr(dataset, name)
            if isinstance(actual, bytes):
                actual = actual.decode("utf-8")
            if str(actual) != str(retained[name]):
                raise ValueError(f"source retained metadata {name} differs")

        integrated_masses: list[float] = []
        for tag in TAGS:
            rate_variable = dataset.variables[tag]
            weight_variable = dataset.variables[f"weight_{tag}"]
            if tuple(rate_variable.dimensions) != ("time", "lev", "lat", "lon"):
                raise ValueError(f"{tag}: unexpected source dimensions")
            if tuple(weight_variable.dimensions) != ("lev", "lat", "lon"):
                raise ValueError(f"weight_{tag}: unexpected source dimensions")
            if np.dtype(rate_variable.data.dtype).itemsize != 8:
                raise ValueError(f"{tag}: source field is not float64")
            if np.dtype(weight_variable.data.dtype).itemsize != 8:
                raise ValueError(f"weight_{tag}: source field is not float64")

            rate = np.asarray(rate_variable.data, dtype=np.float64)
            weights = np.asarray(weight_variable.data, dtype=np.float64)
            if rate.shape != (1, len(reference["lev"]), len(reference["lat"]), len(reference["lon"])):
                raise ValueError(f"{tag}: unexpected source shape {rate.shape}")
            if np.any(~np.isfinite(rate)) or np.any(rate < 0.0):
                raise ValueError(f"{tag}: source rate is non-finite or negative")
            if np.any(~np.isfinite(weights)) or np.any(weights < 0.0):
                raise ValueError(f"weight_{tag}: weights are non-finite or negative")
            require_source_cell_only(rate[0], source_j, source_i, f"{tag} source")
            require_source_cell_only(weights, source_j, source_i, f"weight_{tag}")

            profile = weights[:, source_j, source_i]
            if abs(float(profile.sum(dtype=np.float64)) - 1.0) > profile_tolerance:
                raise ValueError(f"weight_{tag}: profile does not sum to one")

            layer_mass = rate[0, :, source_j, source_i] * source_area * duration_s
            integrated_mass = float(layer_mass.sum(dtype=np.float64))
            mass_error = relative_error(integrated_mass, expected_mass)
            if mass_error > mass_tolerance:
                raise ValueError(f"{tag}: integrated source mass differs from the contract")
            rate_profile = layer_mass / integrated_mass
            rate_profile_error = float(np.max(np.abs(rate_profile - profile)))
            if rate_profile_error > profile_tolerance:
                raise ValueError(f"{tag}: rate profile differs from stored frozen weights")

            analytic_increment = rate[0] * source_area * transport_timestep_s
            profiles[tag] = profile.copy()
            integrated_masses.append(integrated_mass)
            checks[tag] = {
                "integrated_mass_kg": integrated_mass,
                "relative_mass_error": mass_error,
                "profile_max_abs_error": rate_profile_error,
                "analytic_increment_per_heartbeat_kg": float(
                    analytic_increment.sum(dtype=np.float64)
                ),
            }

    spread = (max(integrated_masses) - min(integrated_masses)) / expected_mass
    if spread > equal_tolerance:
        raise ValueError("source tag masses differ from one another")
    evidence = {
        "path": str(source_path),
        "sha256": sha256(source_path),
        "equal_tag_relative_spread": float(spread),
        "checks": checks,
    }
    return profiles, reference, evidence


def checkpoint_filename(label: str, model_time: datetime) -> str:
    return f"GEOSChem.PlumeCheckpoint.{label}.{model_time.strftime('%Y%m%d_%H%M%S')}z.nc4"


def load_checkpoint(
    path: Path,
    manifest: dict,
    reference: dict[str, np.ndarray],
    checkpoint_id: int,
    label: str,
    state_offset_s: int,
    heartbeat_index: int,
    model_time: datetime,
    elapsed_seconds: int,
    internal_tolerance: float,
    nonnegative_floor: float,
    denominator_floor: float,
) -> Checkpoint:
    expected_name = checkpoint_filename(label, model_time)
    if path.name != expected_name:
        raise ValueError(f"checkpoint filename {path.name!r} != {expected_name!r}")

    with h5py.File(path, "r") as dataset:
        required = {
            "lon",
            "lat",
            "lev",
            "grid_cell_area",
            "dry_air_mass",
            "Met_DELPDRY",
            "tag_id",
            "global_plume_mass",
            *(f"PlumeMass_{tag}" for tag in TAGS),
        }
        missing = required.difference(dataset.keys())
        if missing:
            raise KeyError(f"{path}: missing checkpoint variables {sorted(missing)}")

        expected_text_attributes = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "run_id": str(manifest["case_id"]),
            "checkpoint_label": label,
            "tracer_state_units": "kg species kg-1 dry air",
            "mass_formula": "PlumeMass = SpeciesConc * dry_air_mass",
        }
        for name, expected in expected_text_attributes.items():
            actual = text_attribute(dataset, name)
            if actual != expected:
                raise ValueError(f"{path}: {name} {actual!r} != {expected!r}")

        expected_integer_attributes = {
            "checkpoint_id": checkpoint_id,
            "model_date": int(model_time.strftime("%Y%m%d")),
            "model_time": int(model_time.strftime("%H%M%S")),
            "heartbeat_index": heartbeat_index,
            "elapsed_seconds": elapsed_seconds,
            "state_time_offset_seconds": state_offset_s,
            "transport_active": 1,
            "transport_timestep_seconds": int(manifest["run"]["transport_timestep_s"]),
            "emissions_timestep_seconds": int(manifest["run"]["emissions_elapsed_time_s"]),
            "chemistry_timestep_seconds": int(manifest["run"]["chemistry_timestep_s"]),
        }
        for name, expected in expected_integer_attributes.items():
            actual = integer_attribute(dataset, name)
            if actual != expected:
                raise ValueError(f"{path}: {name} {actual} != {expected}")

        for name in ("lon", "lat"):
            require_float64(dataset[name], f"{path}:{name}")
            require_dimensions(dataset[name], (name,))
            values = read_array(dataset, name)
            expected = reference[name]
            if values.shape != expected.shape or not np.allclose(
                values, expected, rtol=0.0, atol=1.0e-12
            ):
                raise ValueError(f"{path}: {name} coordinate differs from source")

        lev = read_array(dataset, "lev")
        require_dimensions(dataset["lev"], ("lev",))
        expected_lev = np.arange(1, int(manifest["grid"]["levels"]) + 1)
        if not np.array_equal(lev, expected_lev):
            raise ValueError(f"{path}: checkpoint levels are not one-based model levels")

        require_float64(dataset["grid_cell_area"], f"{path}:grid_cell_area")
        require_float64(dataset["dry_air_mass"], f"{path}:dry_air_mass")
        require_float64(dataset["Met_DELPDRY"], f"{path}:Met_DELPDRY")
        require_dimensions(dataset["grid_cell_area"], ("lat", "lon"))
        require_dimensions(dataset["dry_air_mass"], ("lev", "lat", "lon"))
        require_dimensions(dataset["Met_DELPDRY"], ("lev", "lat", "lon"))
        if text_attribute(dataset["grid_cell_area"], "units") != "m2":
            raise ValueError(f"{path}: grid-cell area units are not m2")
        if text_attribute(dataset["dry_air_mass"], "units") != "kg":
            raise ValueError(f"{path}: dry-air mass units are not kg")
        if text_attribute(dataset["Met_DELPDRY"], "units") != "hPa":
            raise ValueError(f"{path}: DELPDRY units are not hPa")

        area = read_array(dataset, "grid_cell_area")
        dry_air_mass = read_array(dataset, "dry_air_mass")
        delp_dry = read_array(dataset, "Met_DELPDRY")
        if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
            raise ValueError(f"{path}: invalid grid-cell area")
        if np.any(~np.isfinite(dry_air_mass)) or np.any(dry_air_mass <= 0.0):
            raise ValueError(f"{path}: invalid dry-air mass")
        if np.any(~np.isfinite(delp_dry)) or np.any(delp_dry <= 0.0):
            raise ValueError(f"{path}: invalid DELPDRY")
        reconstructed_air = delp_dry * 100.0 * area[np.newaxis, :, :] / G0_M_S2
        air_error = relative_l1(dry_air_mass, reconstructed_air, denominator_floor)
        if air_error > internal_tolerance:
            raise ValueError(f"{path}: dry-air mass is inconsistent with DELPDRY ({air_error})")

        require_dimensions(dataset["tag_id"], ("tag",))
        tag_ids = read_array(dataset, "tag_id")
        if not np.array_equal(tag_ids, np.arange(1, len(TAGS) + 1)):
            raise ValueError(f"{path}: tag identifiers are invalid")
        if text_attribute(dataset["tag_id"], "tag_names") != ",".join(TAGS):
            raise ValueError(f"{path}: tag-name metadata is invalid")
        require_float64(dataset["global_plume_mass"], f"{path}:global_plume_mass")
        require_dimensions(dataset["global_plume_mass"], ("tag",))
        if text_attribute(dataset["global_plume_mass"], "units") != "kg":
            raise ValueError(f"{path}: global plume mass units are not kg")
        recorded_global = read_array(dataset, "global_plume_mass")
        if recorded_global.shape != (len(TAGS),) or np.any(~np.isfinite(recorded_global)):
            raise ValueError(f"{path}: invalid global plume mass")

        masses: dict[str, np.ndarray] = {}
        global_masses: dict[str, float] = {}
        for index, tag in enumerate(TAGS):
            name = f"PlumeMass_{tag}"
            require_float64(dataset[name], f"{path}:{name}")
            require_dimensions(dataset[name], ("lev", "lat", "lon"))
            if text_attribute(dataset[name], "units") != "kg":
                raise ValueError(f"{path}:{name}: units are not kg")
            mass = read_array(dataset, name)
            if mass.shape != dry_air_mass.shape or np.any(~np.isfinite(mass)):
                raise ValueError(f"{path}:{name}: invalid tracer-mass field")
            if float(mass.min()) < -nonnegative_floor:
                raise ValueError(f"{path}:{name}: negative tracer mass")
            field_sum = float(mass.sum(dtype=np.float64))
            internal_error = relative_difference(
                float(recorded_global[index]), field_sum, denominator_floor
            )
            if internal_error > internal_tolerance:
                raise ValueError(
                    f"{path}:{name}: global mass does not match field sum ({internal_error})"
                )
            masses[tag] = mass
            global_masses[tag] = float(recorded_global[index])

    return Checkpoint(
        path=path,
        sha256=sha256(path),
        area=area,
        dry_air_mass=dry_air_mass,
        delp_dry=delp_dry,
        mass=masses,
        global_mass=global_masses,
    )


def load_checkpoints(
    directory: Path,
    manifest: dict,
    reference: dict[str, np.ndarray],
    run_start: datetime,
    internal_tolerance: float,
    nonnegative_floor: float,
    denominator_floor: float,
) -> dict[tuple[int, str], Checkpoint]:
    if directory != Path(manifest["paths"]["checkpoint_directory"]).resolve():
        raise ValueError("checkpoint directory is not the manifest-declared directory")
    if directory.parent != Path(manifest["paths"]["run_directory"]).resolve() / "OutputDir":
        raise ValueError("checkpoint directory is outside the run OutputDir")
    if not directory.is_dir():
        raise FileNotFoundError(f"checkpoint directory is absent: {directory}")

    transport_timestep = int(manifest["run"]["transport_timestep_s"])
    expected_paths: set[Path] = set()
    for heartbeat in range(2):
        model_time = run_start + timedelta(seconds=heartbeat * transport_timestep)
        for _, label, _ in CHECKPOINTS:
            expected_paths.add(directory / checkpoint_filename(label, model_time))
    actual_paths = set(directory.glob("GEOSChem.PlumeCheckpoint.*.nc4"))
    if actual_paths != expected_paths:
        missing = sorted(str(path) for path in expected_paths - actual_paths)
        extra = sorted(str(path) for path in actual_paths - expected_paths)
        raise ValueError(f"checkpoint file set differs; missing={missing}, extra={extra}")
    if len(actual_paths) != int(manifest["checkpoint_runtime"]["expected_files"]):
        raise ValueError("checkpoint file count differs from the manifest")

    checkpoints: dict[tuple[int, str], Checkpoint] = {}
    for heartbeat in range(2):
        elapsed = heartbeat * transport_timestep
        model_time = run_start + timedelta(seconds=elapsed)
        for checkpoint_id, label, offset in CHECKPOINTS:
            path = directory / checkpoint_filename(label, model_time)
            checkpoints[(heartbeat, label)] = load_checkpoint(
                path,
                manifest,
                reference,
                checkpoint_id,
                label,
                offset,
                heartbeat + 1,
                model_time,
                elapsed,
                internal_tolerance,
                nonnegative_floor,
                denominator_floor,
            )

    first = checkpoints[(0, "C0_PRE_TPCORE")]
    expected_source_area = float(manifest["source"]["cell_area_m2"])
    source_j = int(manifest["source"]["cell_index_zero_based"]["j"])
    source_i = int(manifest["source"]["cell_index_zero_based"]["i"])
    if relative_error(float(first.area[source_j, source_i]), expected_source_area) > 1.0e-7:
        raise ValueError("checkpoint source-cell area differs from the manifest")
    for key, checkpoint in checkpoints.items():
        require_exact_array(checkpoint.area, first.area, f"{key} grid-cell area")
        checkpoint_id = next(item[0] for item in CHECKPOINTS if item[1] == key[1])
        if checkpoint_id >= 1:
            c1 = checkpoints[(key[0], "C1_POST_TPCORE")]
            require_exact_array(checkpoint.dry_air_mass, c1.dry_air_mass, f"{key} air mass")
            require_exact_array(checkpoint.delp_dry, c1.delp_dry, f"{key} DELPDRY")
    return checkpoints


def validate_checkpoint_ledger(
    checkpoints: dict[tuple[int, str], Checkpoint],
    profiles: dict[str, np.ndarray],
    expected_increment: dict[str, np.ndarray],
    manifest: dict,
    tolerances: dict[str, float],
) -> dict:
    source_j = int(manifest["source"]["cell_index_zero_based"]["j"])
    source_i = int(manifest["source"]["cell_index_zero_based"]["i"])
    denominator_floor = tolerances["relative_denominator_floor_kg"]

    initial = checkpoints[(0, "C0_PRE_TPCORE")]
    for tag in TAGS:
        if np.any(initial.mass[tag] != 0.0):
            raise ValueError(f"{tag}: initial C0 plume mass is not exactly zero")

    inactive_checks: dict[str, dict[str, dict[str, float]]] = {}
    inactive_floor = tolerances["inactive_operator_increment_absolute_kg"]
    for heartbeat in range(2):
        heartbeat_checks: dict[str, dict[str, float]] = {}
        for before_label, after_label in INACTIVE_TRANSITIONS:
            before = checkpoints[(heartbeat, before_label)]
            after = checkpoints[(heartbeat, after_label)]
            transition = f"{before_label}_to_{after_label}"
            tag_maxima: list[float] = []
            for tag in TAGS:
                maximum = max_abs_difference(after.mass[tag], before.mass[tag])
                if maximum > inactive_floor:
                    raise ValueError(
                        f"heartbeat {heartbeat + 1} {transition} {tag}: "
                        f"inactive increment {maximum} > {inactive_floor}"
                    )
                tag_maxima.append(maximum)
            heartbeat_checks[transition] = {
                "maximum_absolute_cell_increment_kg": max(tag_maxima)
            }
        inactive_checks[str(heartbeat + 1)] = heartbeat_checks

    do_tend_checks: dict[str, dict[str, dict[str, float]]] = {}
    total_increment: dict[str, float] = {tag: 0.0 for tag in TAGS}
    for heartbeat in range(2):
        before = checkpoints[(heartbeat, "C2_FLUX_READY")]
        after = checkpoints[(heartbeat, "C3_POST_MIXING")]
        heartbeat_checks = {}
        realization_responses: list[float] = []
        for tag in TAGS:
            actual = after.mass[tag] - before.mass[tag]
            expected = expected_increment[tag]
            field_error = relative_l1(actual, expected, denominator_floor)
            if field_error > tolerances["do_tend_increment_relative"]:
                raise ValueError(
                    f"heartbeat {heartbeat + 1} {tag}: DO_TEND 3-D increment error "
                    f"{field_error}"
                )
            actual_total = float(actual.sum(dtype=np.float64))
            expected_total = float(expected.sum(dtype=np.float64))
            total_error = relative_difference(actual_total, expected_total, denominator_floor)
            if total_error > tolerances["do_tend_increment_relative"]:
                raise ValueError(f"heartbeat {heartbeat + 1} {tag}: DO_TEND mass error")
            source_layer = actual[:, source_j, source_i]
            source_total = float(source_layer.sum(dtype=np.float64))
            if source_total <= 0.0:
                raise ValueError(f"heartbeat {heartbeat + 1} {tag}: no positive source increment")
            profile = source_layer / source_total
            profile_error = float(np.max(np.abs(profile - profiles[tag])))
            if profile_error > tolerances["model_source_profile_absolute"]:
                raise ValueError(f"heartbeat {heartbeat + 1} {tag}: source profile mismatch")
            realization_response = actual_total / expected_total
            realization_responses.append(realization_response)
            total_increment[tag] += actual_total
            heartbeat_checks[tag] = {
                "actual_increment_kg": actual_total,
                "expected_increment_kg": expected_total,
                "relative_global_error": total_error,
                "relative_3d_l1_error": field_error,
                "profile_max_abs_error": profile_error,
                "realization_normalized_response": realization_response,
            }
        spread = max(realization_responses) - min(realization_responses)
        if spread > tolerances["checkpoint_equal_tag_relative"]:
            raise ValueError(
                f"heartbeat {heartbeat + 1}: realization-normalized DO_TEND "
                "responses differ"
            )
        heartbeat_checks["realization_normalized_response_spread"] = {
            "value": float(spread)
        }
        do_tend_checks[str(heartbeat + 1)] = heartbeat_checks
    for tag in TAGS:
        realized_expected_total = 2.0 * float(
            expected_increment[tag].sum(dtype=np.float64)
        )
        error = relative_difference(
            total_increment[tag], realized_expected_total, denominator_floor
        )
        if error > tolerances["do_tend_increment_relative"]:
            raise ValueError(
                f"{tag}: cumulative DO_TEND source differs from HEMCO realization"
            )

    transport_checks: dict[str, dict[str, dict[str, float | int]]] = {}
    for heartbeat in range(2):
        before = checkpoints[(heartbeat, "C0_PRE_TPCORE")]
        after = checkpoints[(heartbeat, "C1_POST_TPCORE")]
        heartbeat_checks = {}
        realization_responses: list[float] = []
        for tag in TAGS:
            before_mass = float(before.mass[tag].sum(dtype=np.float64))
            after_mass = float(after.mass[tag].sum(dtype=np.float64))
            conservation_error = relative_difference(
                after_mass, before_mass, denominator_floor
            )
            if conservation_error > tolerances["transport_conservation_relative"]:
                raise ValueError(
                    f"heartbeat {heartbeat + 1} {tag}: TPCORE global conservation error "
                    f"{conservation_error}"
                )
            delta = after.mass[tag] - before.mass[tag]
            l1_change = float(np.abs(delta).sum(dtype=np.float64))
            normalized_l1 = l1_change / max(
                float(np.abs(before.mass[tag]).sum(dtype=np.float64)), denominator_floor
            )
            changed_cells = int(np.count_nonzero(delta))
            if heartbeat == 0:
                if changed_cells != 0 or l1_change != 0.0:
                    raise ValueError(f"{tag}: first zero-state TPCORE call changed plume mass")
            else:
                if manifest["acceptance"]["require_nonzero_3d_redistribution_after_nonzero_c0"] is not True:
                    raise ValueError("manifest must require nonzero TPCORE redistribution")
                if (
                    changed_cells == 0
                    or l1_change <= denominator_floor
                    or normalized_l1 <= tolerances["cadence_state_relative_l1"]
                ):
                    raise ValueError(f"{tag}: nonzero C0 state was not redistributed by TPCORE")
                outside = after.mass[tag].copy()
                outside[:, source_j, source_i] = 0.0
                outside_mass = float(outside.sum(dtype=np.float64))
                if outside_mass <= denominator_floor:
                    raise ValueError(f"{tag}: TPCORE produced no mass outside the source column")
            if heartbeat == 0:
                realization_response = 0.0
            else:
                realized_reference = float(
                    expected_increment[tag].sum(dtype=np.float64)
                )
                realization_response = after_mass / realized_reference
            realization_responses.append(realization_response)
            heartbeat_checks[tag] = {
                "mass_before_kg": before_mass,
                "mass_after_kg": after_mass,
                "relative_conservation_error": conservation_error,
                "normalized_3d_l1_change": normalized_l1,
                "changed_cells": changed_cells,
                "realization_normalized_burden": realization_response,
            }
        spread = max(realization_responses) - min(realization_responses)
        if spread > tolerances["checkpoint_equal_tag_relative"]:
            raise ValueError(
                f"heartbeat {heartbeat + 1}: realization-normalized checkpoint "
                "burdens differ"
            )
        heartbeat_checks["realization_normalized_burden_spread"] = {
            "value": float(spread)
        }
        transport_checks[str(heartbeat + 1)] = heartbeat_checks

    cadence_checks: dict[str, dict[str, float]] = {}
    previous = checkpoints[(0, "C6_POST_WETDEP")]
    following = checkpoints[(1, "C0_PRE_TPCORE")]
    for tag in TAGS:
        error = relative_l1(following.mass[tag], previous.mass[tag], denominator_floor)
        if error > tolerances["cadence_state_relative_l1"]:
            raise ValueError(f"{tag}: state is discontinuous across the heartbeat boundary")
        cadence_checks[tag] = {"relative_3d_l1_error": error}

    first_c1 = checkpoints[(0, "C1_POST_TPCORE")]
    second_c0 = checkpoints[(1, "C0_PRE_TPCORE")]
    pressure_checks = {}
    for name in ("delp_dry", "dry_air_mass"):
        error = relative_l1(
            getattr(second_c0, name), getattr(first_c1, name), denominator_floor
        )
        if error > tolerances["pressure_continuity_relative"]:
            raise ValueError(f"{name}: pressure state is discontinuous at 00:10")
        pressure_checks[f"first_C1_to_second_C0_{name}_relative_l1"] = error

    return {
        "inactive_operator_checks": inactive_checks,
        "do_tend_checks": do_tend_checks,
        "cumulative_do_tend_increment_kg": total_increment,
        "transport_checks": transport_checks,
        "cadence_continuity_checks": cadence_checks,
        "pressure_continuity_checks": pressure_checks,
    }


def validate_budget_with_transport(
    path: Path,
    manifest: dict,
    reference: dict[str, np.ndarray],
    checkpoints: dict[tuple[int, str], Checkpoint],
    run_start: datetime,
    run_end: datetime,
    source_tolerance: float,
    transport_tolerance: float,
    crosscheck_tolerance: float,
    denominator_floor: float,
) -> tuple[dict[str, dict], dict[str, dict]]:
    duration_s = (run_end - run_start).total_seconds()
    expected_mass = float(manifest["source"]["total_mass_per_tag_kg"])
    source_j = int(manifest["source"]["cell_index_zero_based"]["j"])
    source_i = int(manifest["source"]["cell_index_zero_based"]["i"])
    source_checks: dict[str, dict] = {}
    transport_checks: dict[str, dict] = {}

    with h5py.File(path, "r") as dataset:
        require_time_reference(dataset, run_start, "minutes", "Budget diagnostic")
        require_coordinates(dataset, reference, "Budget diagnostic", include_lev=False)
        require_dimensions(dataset["AREA"], ("lat", "lon"))
        if text_attribute(dataset["AREA"], "units") != "m2":
            raise ValueError("Budget diagnostic AREA units are not m2")
        expected_start = run_start.strftime("%Y-%m-%d %H:%M:%Sz")
        expected_end = run_end.strftime("%Y-%m-%d %H:%M:%Sz")
        if text_attribute(dataset, "simulation_start_date_and_time") != expected_start:
            raise ValueError("Budget start time differs from manifest")
        if text_attribute(dataset, "simulation_end_date_and_time") != expected_end:
            raise ValueError("Budget end time differs from manifest")

        transport_before = checkpoints[(1, "C0_PRE_TPCORE")]
        transport_after = checkpoints[(1, "C1_POST_TPCORE")]
        for tag in TAGS:
            source_name = f"BudgetEmisDryDepFull_{tag}"
            transport_name = f"BudgetTransportFull_{tag}"
            for name in (source_name, transport_name):
                require_dimensions(dataset[name], ("time", "lat", "lon"))
                if text_attribute(dataset[name], "units") != "kg s-1":
                    raise ValueError(f"{name}: units are not kg s-1")
                if text_attribute(dataset[name], "averaging_method") != "time-averaged":
                    raise ValueError(f"{name}: field is not a time average")

            source_rate = read_array(dataset, source_name)
            if source_rate.shape[0] != 1 or np.any(~np.isfinite(source_rate)) or np.any(source_rate < 0.0):
                raise ValueError(f"{source_name}: invalid source-budget values")
            outside_max = require_source_cell_only(
                source_rate[0], source_j, source_i, source_name
            )
            integrated_source = float(source_rate[0].sum(dtype=np.float64) * duration_s)
            source_error = relative_error(integrated_source, expected_mass)
            if source_error > source_tolerance:
                raise ValueError(f"{source_name}: source ledger does not close")
            source_checks[tag] = {
                "integrated_mass_kg": integrated_source,
                "relative_mass_error": source_error,
                "outside_source_cell_max_kg_s": outside_max,
            }

            rate = read_array(dataset, transport_name)
            if rate.shape[0] != 1 or np.any(~np.isfinite(rate)):
                raise ValueError(f"{transport_name}: invalid transport-budget values")
            budget_delta = rate[0] * duration_s
            checkpoint_delta = (
                transport_after.mass[tag] - transport_before.mass[tag]
            ).sum(axis=0, dtype=np.float64)
            crosscheck_error = relative_l1(
                budget_delta, checkpoint_delta, denominator_floor
            )
            if crosscheck_error > crosscheck_tolerance:
                raise ValueError(
                    f"{transport_name}: Budget/checkpoint L1 error {crosscheck_error}"
                )
            global_delta = float(budget_delta.sum(dtype=np.float64))
            global_error = abs(global_delta) / max(expected_mass, denominator_floor)
            if global_error > transport_tolerance:
                raise ValueError(f"{transport_name}: global transport budget does not close")
            transport_checks[tag] = {
                "global_delta_kg": global_delta,
                "global_delta_relative_to_emitted": global_error,
                "budget_checkpoint_relative_l1_error": crosscheck_error,
                "budget_delta_l1_kg": float(np.abs(budget_delta).sum(dtype=np.float64)),
                "checkpoint_delta_l1_kg": float(
                    np.abs(checkpoint_delta).sum(dtype=np.float64)
                ),
            }

    source_masses = [source_checks[tag]["integrated_mass_kg"] for tag in TAGS]
    spread = (max(source_masses) - min(source_masses)) / expected_mass
    if spread > source_tolerance:
        raise ValueError("Budget source-ledger tag masses differ")
    return source_checks, transport_checks


def validate_endpoint_restart(
    path: Path,
    manifest: dict,
    reference: dict[str, np.ndarray],
    checkpoints: dict[tuple[int, str], Checkpoint],
    realized_expected_mass: dict[str, float],
    run_end: datetime,
    endpoint_tolerance: float,
    pressure_tolerance: float,
    equal_tag_tolerance: float,
    nonnegative_floor: float,
    denominator_floor: float,
) -> dict:
    mw_species = float(manifest["species"]["molecular_weight_g_mol"])
    final_checkpoint = checkpoints[(1, "C6_POST_WETDEP")]
    end_transport = checkpoints[(1, "C1_POST_TPCORE")]
    checks: dict[str, dict] = {}

    with h5py.File(path, "r") as dataset:
        require_time_reference(dataset, run_end, "minutes", "end restart")
        require_coordinates(dataset, reference, "end restart", include_lev=True)
        require_dimensions(dataset["AREA"], ("lat", "lon"))
        require_dimensions(dataset["Met_DELPDRY"], ("time", "lev", "lat", "lon"))
        if text_attribute(dataset["AREA"], "units") != "m2":
            raise ValueError("end-restart AREA units are not m2")
        if text_attribute(dataset["Met_DELPDRY"], "units") != "hPa":
            raise ValueError("end-restart DELPDRY units are not hPa")
        area = read_array(dataset, "AREA")
        delp_dry = read_array(dataset, "Met_DELPDRY")[0]
        if np.any(~np.isfinite(area)) or np.any(area <= 0.0):
            raise ValueError("end restart contains invalid area")
        if np.any(~np.isfinite(delp_dry)) or np.any(delp_dry <= 0.0):
            raise ValueError("end restart contains invalid DELPDRY")
        area_relative = np.abs(area - final_checkpoint.area) / np.maximum(
            np.abs(final_checkpoint.area), 1.0
        )
        maximum_area_relative_error = float(np.max(area_relative))
        if maximum_area_relative_error > 1.0e-7:
            raise ValueError(
                "end-restart area differs from checkpoint beyond float32 representation"
            )
        pressure_error = relative_l1(
            delp_dry, end_transport.delp_dry, denominator_floor
        )
        if pressure_error > pressure_tolerance:
            raise ValueError("end-restart pressure is not time-consistent with second C1")
        # Restart AREA is float32.  Use the checked full-precision checkpoint
        # area after bounding its representation error so pressure and burden
        # reconstruction are not limited by restart AREA quantization.
        dry_air_mass = (
            delp_dry
            * 100.0
            * final_checkpoint.area[np.newaxis, :, :]
            / G0_M_S2
        )
        air_mass_error = relative_l1(
            dry_air_mass, end_transport.dry_air_mass, denominator_floor
        )
        if air_mass_error > pressure_tolerance:
            raise ValueError("end-restart dry-air mass is not time-consistent with second C1")

        realization_responses: list[float] = []
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
                raise ValueError(f"{name}: non-finite mixing ratio")
            mass = mixing_ratio * dry_air_mass * (mw_species / AIR_MW_G_MOL)
            if float(mass.min()) < -nonnegative_floor:
                raise ValueError(f"{name}: negative endpoint mass")
            checkpoint_error = relative_l1(
                mass, final_checkpoint.mass[tag], denominator_floor
            )
            if checkpoint_error > endpoint_tolerance:
                raise ValueError(f"{tag}: endpoint restart differs from final checkpoint")
            burden = float(mass.sum(dtype=np.float64))
            burden_error = relative_difference(
                burden, realized_expected_mass[tag], denominator_floor
            )
            if burden_error > endpoint_tolerance:
                raise ValueError(
                    f"{tag}: endpoint burden differs from realized HEMCO source"
                )
            realization_response = burden / realized_expected_mass[tag]
            realization_responses.append(realization_response)
            checks[tag] = {
                "burden_kg": burden,
                "realized_expected_burden_kg": realized_expected_mass[tag],
                "relative_burden_error": burden_error,
                "checkpoint_relative_3d_l1_error": checkpoint_error,
                "realization_normalized_burden": realization_response,
            }
    spread = max(realization_responses) - min(realization_responses)
    if spread > equal_tag_tolerance:
        raise ValueError("endpoint realization-normalized tag burdens differ")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "second_C1_to_restart_DELPDRY_relative_l1": pressure_error,
        "second_C1_to_restart_dry_air_mass_relative_l1": air_mass_error,
        "checkpoint_to_restart_maximum_area_relative_error": maximum_area_relative_error,
        "realization_normalized_burden_spread": float(spread),
        "checks": checks,
    }


def acceptance_tolerances(manifest: dict) -> dict[str, float]:
    acceptance = manifest["acceptance"]
    if str(acceptance["contract_version"]) != CONTRACT_VERSION:
        raise ValueError(
            f"validator requires {CONTRACT_VERSION}, got {acceptance['contract_version']}"
        )
    if str(manifest.get("acceptance_contract")) != CONTRACT_VERSION:
        raise ValueError("top-level acceptance contract differs from validator contract")
    keys = (
        "profile_sum_absolute",
        "equal_source_relative",
        "source_flux_to_mass_relative",
        "model_source_ledger_relative",
        "model_source_profile_absolute",
        "do_tend_increment_relative",
        "transport_conservation_relative",
        "budget_transport_crosscheck_relative_l1",
        "endpoint_airborne_relative",
        "checkpoint_equal_tag_relative",
        "cadence_state_relative_l1",
        "pressure_continuity_relative",
        "checkpoint_internal_relative",
        "relative_denominator_floor_kg",
        "inactive_operator_increment_absolute_kg",
        "nonnegative_floor_kg",
    )
    tolerances = {key: finite_scalar(acceptance[key], key) for key in keys}
    if tolerances["relative_denominator_floor_kg"] <= 0.0:
        raise ValueError("relative denominator floor must be positive")
    required_flags = {
        "require_nonzero_3d_redistribution_after_nonzero_c0": True,
        "require_time_consistent_checkpoint_airmass": True,
        "allow_v0_endpoint_pressure_stagger_exception": False,
        "require_no_unaccounted_global_export": True,
    }
    for key, expected in required_flags.items():
        if acceptance[key] is not expected:
            raise ValueError(f"acceptance flag {key} must be {expected}")
    return tolerances


def load_validation_manifest(path: Path) -> dict:
    """Resolve a reviewed child manifest before validating its full contract."""

    manifest = load_manifest(path)
    if tuple(manifest["source"]["tags"]) != TAGS:
        raise ValueError(f"manifest tags must be exactly {TAGS}")
    return manifest


def run_validation(args: argparse.Namespace) -> None:
    manifest = load_validation_manifest(args.manifest)
    validate_operator_and_checkpoint_contract(manifest)
    tolerances = acceptance_tolerances(manifest)

    run_directory = Path(manifest["paths"]["run_directory"]).resolve()
    if not run_directory.is_dir():
        raise FileNotFoundError(f"run directory is absent: {run_directory}")
    source_path = checked_path(
        Path(manifest["paths"]["generated_source"]), run_directory, "generated source"
    )
    restart_path = checked_path(
        args.restart, run_directory / "Restarts", "end restart"
    )
    run_start = parse_utc(manifest["run"]["start"])
    run_end = parse_utc(manifest["run"]["end"])
    transport_timestep_s = int(manifest["run"]["transport_timestep_s"])
    run_duration_s = (run_end - run_start).total_seconds()
    if run_duration_s != 2 * transport_timestep_s:
        raise ValueError("TPCORE run must span exactly two transport timesteps")
    if float(manifest["source"]["duration_s"]) != run_duration_s:
        raise ValueError("source duration must equal the full run interval")
    expected_restart_name = f"GEOSChem.Restart.{run_end.strftime('%Y%m%d_%H%M')}z.nc4"
    if restart_path.name != expected_restart_name:
        raise ValueError("end restart filename does not match the run endpoint")

    checkpoint_directory = (
        args.checkpoint_directory
        or Path(manifest["paths"]["checkpoint_directory"])
    ).resolve()
    if checkpoint_directory != Path(manifest["paths"]["checkpoint_directory"]).resolve():
        raise ValueError("requested checkpoint directory differs from the manifest")
    budget_path = (args.budget or unique_default(
        run_directory / "OutputDir", "GEOSChem.Budget.*.nc4", "Budget diagnostic"
    )).resolve()
    hemco_path = (args.hemco_diagnostics or unique_default(
        run_directory / "OutputDir", "HEMCO_diagnostics.*.nc", "HEMCO diagnostic"
    )).resolve()
    if budget_path.parent != run_directory / "OutputDir":
        raise ValueError("Budget diagnostic is outside the run OutputDir")
    if hemco_path.parent != run_directory / "OutputDir":
        raise ValueError("HEMCO diagnostic is outside the run OutputDir")

    checked_inputs = validate_checked_inputs(run_directory, manifest)
    profiles, reference, source_evidence = validate_source(
        source_path,
        manifest,
        float(transport_timestep_s),
        tolerances["profile_sum_absolute"],
        tolerances["source_flux_to_mass_relative"],
        tolerances["equal_source_relative"],
    )
    checkpoints = load_checkpoints(
        checkpoint_directory,
        manifest,
        reference,
        run_start,
        tolerances["checkpoint_internal_relative"],
        tolerances["nonnegative_floor_kg"],
        tolerances["relative_denominator_floor_kg"],
    )
    expected_mass = float(manifest["source"]["total_mass_per_tag_kg"])
    source_j = int(manifest["source"]["cell_index_zero_based"]["j"])
    source_i = int(manifest["source"]["cell_index_zero_based"]["i"])
    hemco_checks, expected_increment, hemco_realization = validate_hemco(
        hemco_path,
        expected_mass,
        run_duration_s,
        tolerances["model_source_ledger_relative"],
        tolerances["model_source_profile_absolute"],
        source_j,
        source_i,
        {tag: profiles[tag].tolist() for tag in TAGS},
        reference,
        run_start,
        float(manifest["source"]["cell_area_m2"]),
        float(transport_timestep_s),
    )
    realized_expected_mass = {
        tag: float(hemco_checks[tag]["integrated_mass_kg"])
        for tag in TAGS
    }
    checkpoint_evidence = validate_checkpoint_ledger(
        checkpoints, profiles, expected_increment, manifest, tolerances
    )
    budget_source_checks, budget_transport_checks = validate_budget_with_transport(
        budget_path,
        manifest,
        reference,
        checkpoints,
        run_start,
        run_end,
        tolerances["model_source_ledger_relative"],
        tolerances["transport_conservation_relative"],
        tolerances["budget_transport_crosscheck_relative_l1"],
        tolerances["relative_denominator_floor_kg"],
    )
    endpoint_evidence = validate_endpoint_restart(
        restart_path,
        manifest,
        reference,
        checkpoints,
        realized_expected_mass,
        run_end,
        tolerances["endpoint_airborne_relative"],
        tolerances["pressure_continuity_relative"],
        tolerances["checkpoint_equal_tag_relative"],
        tolerances["nonnegative_floor_kg"],
        tolerances["relative_denominator_floor_kg"],
    )

    checkpoint_hashes = {
        f"heartbeat_{heartbeat + 1}:{label}": {
            "path": str(checkpoint.path),
            "sha256": checkpoint.sha256,
        }
        for (heartbeat, label), checkpoint in checkpoints.items()
    }
    report = {
        "status": "pass",
        "case_id": manifest["case_id"],
        "acceptance_contract": CONTRACT_VERSION,
        "manifest": str(args.manifest.resolve()),
        "validation_input_manifest_sha256": sha256(args.manifest),
        "run_directory": str(run_directory),
        "run_interval": {
            "start": run_start.isoformat(),
            "end": run_end.isoformat(),
            "duration_s": run_duration_s,
            "transport_timestep_s": transport_timestep_s,
        },
        "analytic_declared_mass_per_tag_kg": expected_mass,
        "tolerances": tolerances,
        "checked_inputs": checked_inputs,
        "source": source_evidence,
        "source_realization": {
            "analytic_declared_mass_per_tag_kg": expected_mass,
            "analytic_normalization_area_m2": float(
                manifest["source"]["cell_area_m2"]
            ),
            "hemco_diagnostic_source_cell_area_m2": float(
                hemco_realization["source_cell_area_m2"]
            ),
            "hemco_to_analytic_area_ratio": float(
                float(hemco_realization["source_cell_area_m2"])
                / float(manifest["source"]["cell_area_m2"])
            ),
            "hemco_diagnostic_area_dtype": hemco_realization["area_dtype"],
            "per_tag": {
                tag: {
                    "realized_expected_increment_per_heartbeat_kg": float(
                        expected_increment[tag].sum(dtype=np.float64)
                    ),
                    "realized_expected_cumulative_mass_kg": realized_expected_mass[tag],
                    "stored_rate_dtype": hemco_checks[tag]["stored_rate_dtype"],
                }
                for tag in TAGS
            },
            "tight_realization_basis": hemco_realization["basis"],
        },
        "checkpoint_files": checkpoint_hashes,
        "checkpoint_ledger": checkpoint_evidence,
        "hemco_diagnostics": {
            "path": str(hemco_path),
            "sha256": sha256(hemco_path),
            "checks": hemco_checks,
        },
        "budget": {
            "path": str(budget_path),
            "sha256": sha256(budget_path),
            "source_checks": budget_source_checks,
            "transport_checks": budget_transport_checks,
        },
        "endpoint_restart": endpoint_evidence,
        "interpretation": {
            "C2_to_C3": "native DO_TEND source application with PBL turbulence off",
            "C0_to_C1": "native TPCORE with inseparable PJC pressure and dry-air-mass reset",
            "endpoint": (
                "time-consistent physical airborne burden against cumulative "
                "HEMCO source realization; no V0 pressure-stagger exception"
            ),
            "global_export": "none on the frozen global grid",
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def failure_report(args: argparse.Namespace, error: Exception) -> dict[str, object]:
    manifest_path = args.manifest.resolve()
    case_id: object = None
    contract: object = CONTRACT_VERSION
    manifest_hash: object = None
    if manifest_path.is_file():
        manifest_hash = sha256(manifest_path)
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                manifest = yaml.safe_load(handle)
            if isinstance(manifest, dict):
                case_id = manifest.get("case_id")
                acceptance = manifest.get("acceptance", {})
                if isinstance(acceptance, dict):
                    contract = acceptance.get(
                        "contract_version",
                        manifest.get("acceptance_contract", CONTRACT_VERSION),
                    )
        except Exception:
            # Preserve the original validation exception and still emit all
            # provenance that can be recovered from the manifest bytes.
            pass
    return {
        "status": "fail",
        "case_id": case_id,
        "acceptance_contract": contract,
        "manifest": str(manifest_path),
        "validation_input_manifest_sha256": manifest_hash,
        "error_type": type(error).__name__,
        "error_message": str(error),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("restart", type=Path)
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--hemco-diagnostics", type=Path)
    parser.add_argument("--checkpoint-directory", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        run_validation(args)
    except Exception as error:
        if args.report:
            rendered = json.dumps(
                failure_report(args, error), indent=2, sort_keys=True
            ) + "\n"
            args.report.write_text(rendered, encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
