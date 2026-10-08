#!/usr/bin/env python3
"""Validate survey-free bounded-QCK v2 Stage-1 dry-deposition A/B controls.

The four positional run directories are dry deposition off/on, each at one
and eight OpenMP threads.  Dry deposition shares the C2--C3 boundary with the
HEMCO source and full PBL mixing, so the off arm supplies the realized source
increment.  ``DryDepMix`` remains qualitative; checkpoint A/B loss is
authoritative and ``BudgetEmisDryDepFull`` is the precision-limited crosscheck.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import yaml

import validate_pbl_ab as common


TAGS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")
TIMES = ("000000", "001000")
LABELS = (
    "C0_PRE_TPCORE",
    "C1_POST_TPCORE",
    "C2_FLUX_READY",
    "C3_POST_MIXING",
    "C4_POST_CONVECTION",
    "C5_POST_CHEMISTRY",
    "C6_POST_WETDEP",
)
AVOGADRO_MOLEC_MOL = 6.02214076e23
PLUME_MW_G_MOL = 12.01
HEARTBEAT_SECONDS = 600.0
BUDGET_HISTORY_ABSOLUTE_PRECISION_KG = 5.0e-5
BUDGET_HISTORY_RELATIVE_PRECISION = 2.0e-4
ACTIVE_LOSS_KG = 1.0e-12
ACTIVE_LOSS_TAGS = {"PLUME_SFC", "PLUME_PBL", "PLUME_6535"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def drydep_flux_to_mass_kg(
    flux_molec_cm2_s: np.ndarray,
    area_m2: np.ndarray,
    *,
    duration_s: float = HEARTBEAT_SECONDS,
    molecular_weight_g_mol: float = PLUME_MW_G_MOL,
    avogadro_molec_mol: float = AVOGADRO_MOLEC_MOL,
) -> float:
    """Integrate a 2-D molecular flux to kg over one diagnostic interval."""
    flux = np.asarray(flux_molec_cm2_s, dtype=np.float64)
    area = np.asarray(area_m2, dtype=np.float64)
    if flux.shape != area.shape:
        raise ValueError(f"flux/area shape mismatch: {flux.shape} != {area.shape}")
    operands = (flux, area)
    if any(np.any(~np.isfinite(value)) for value in operands):
        raise ValueError("dry-deposition conversion operands must be finite")
    if np.any(flux < 0.0) or np.any(area <= 0.0):
        raise ValueError("dry-deposition flux must be nonnegative and area positive")
    scalars = (duration_s, molecular_weight_g_mol, avogadro_molec_mol)
    if any(not math.isfinite(value) or value <= 0.0 for value in scalars):
        raise ValueError("dry-deposition conversion constants must be finite and positive")
    cell_mass = (
        flux
        * area
        * 1.0e4
        * duration_s
        * molecular_weight_g_mol
        * 1.0e-3
        / avogadro_molec_mol
    )
    return float(cell_mass.sum(dtype=np.float64))


def checkpoint_drydep_loss_kg(off_increment_kg: float, on_increment_kg: float) -> float:
    """Isolate deposition from the coupled source/deposition/PBL boundary."""
    values = (float(off_increment_kg), float(on_increment_kg))
    if any(not math.isfinite(value) for value in values):
        raise ValueError("checkpoint increments must be finite")
    return values[0] - values[1]


def budget_drydep_loss_kg(
    off_rate_kg_s: np.ndarray,
    on_rate_kg_s: np.ndarray,
    *,
    duration_s: float = HEARTBEAT_SECONDS,
) -> float:
    """Convert the ON-minus-OFF net source budget difference to positive loss."""
    off_rate = np.asarray(off_rate_kg_s, dtype=np.float64)
    on_rate = np.asarray(on_rate_kg_s, dtype=np.float64)
    if off_rate.shape != on_rate.shape:
        raise ValueError(f"budget shape mismatch: {off_rate.shape} != {on_rate.shape}")
    if np.any(~np.isfinite(off_rate)) or np.any(~np.isfinite(on_rate)):
        raise ValueError("budget rates must be finite")
    if not math.isfinite(duration_s) or duration_s <= 0.0:
        raise ValueError("budget duration must be finite and positive")
    # BudgetEmisDryDepFull is the net emissions-plus-dry-deposition rate.
    # Therefore ON-OFF is the signed negative deposition rate.
    return float((off_rate - on_rate).sum(dtype=np.float64) * duration_s)


def reconciliation_tolerance_kg(budget_loss_kg: float) -> float:
    if not math.isfinite(budget_loss_kg) or budget_loss_kg < 0.0:
        raise ValueError("Budget dry-deposition loss must be finite and nonnegative")
    return max(
        BUDGET_HISTORY_ABSOLUTE_PRECISION_KG,
        BUDGET_HISTORY_RELATIVE_PRECISION * budget_loss_kg,
    )


def reconcile_losses(
    checkpoint_loss_kg: float, budget_loss_kg: float
) -> dict[str, float | bool]:
    """Require checkpoint and native Budget dry-deposition losses to reconcile."""
    checkpoint_loss = float(checkpoint_loss_kg)
    budget_loss = float(budget_loss_kg)
    if not math.isfinite(checkpoint_loss):
        raise ValueError("checkpoint dry-deposition loss must be finite")
    tolerance = reconciliation_tolerance_kg(budget_loss)
    if checkpoint_loss < -tolerance:
        raise ValueError("checkpoint dry-deposition loss is materially negative")
    checked_loss = max(checkpoint_loss, 0.0)
    residual = checked_loss - budget_loss
    if abs(residual) > tolerance:
        raise ValueError(
            "checkpoint/Budget dry-deposition mismatch: "
            f"{checked_loss} vs {budget_loss} kg (tolerance {tolerance})"
        )
    return {
        "checkpoint_loss_raw_kg": checkpoint_loss,
        "checkpoint_loss_kg": checked_loss,
        "checkpoint_negative_roundoff_clipped": checkpoint_loss < 0.0,
        "budget_loss_kg": budget_loss,
        "checkpoint_minus_budget_kg": residual,
        "tolerance_kg": tolerance,
    }


def checkpoint(run: Path, label: str, time: str) -> Path:
    path = (
        run
        / "OutputDir/PlumeCheckpoints"
        / f"GEOSChem.PlumeCheckpoint.{label}.20190101_{time}z.nc4"
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def plume_mass(run: Path, label: str, time: str, tag: str) -> np.ndarray:
    with h5py.File(checkpoint(run, label, time), "r") as dataset:
        values = np.asarray(dataset[f"PlumeMass_{tag}"][:], dtype=np.float64)
    if values.shape != (72, 46, 72) or np.any(~np.isfinite(values)):
        raise ValueError(f"invalid checkpoint plume mass: {run.name} {label} {time} {tag}")
    if float(np.min(values)) < -1.0e-12:
        raise ValueError(f"materially negative checkpoint plume mass: {run.name} {label} {time} {tag}")
    return values


def load_config(run: Path) -> dict[str, Any]:
    return yaml.safe_load((run / "geoschem_config.yml").read_text(encoding="utf-8"))


def require_case_config(off: Path, on: Path) -> None:
    off_config = load_config(off)
    on_config = load_config(on)
    for run, config in ((off, off_config), (on, on_config)):
        if config["operations"]["pbl_mixing"] != {
            "activate": True,
            "use_non_local_pbl": False,
        }:
            raise ValueError(f"{run}: full PBL mixing is not held on")
        if config["operations"]["convection"] != {"activate": True}:
            raise ValueError(f"{run}: convection is not held on")
    if off_config["operations"]["dry_deposition"] != {"activate": False}:
        raise ValueError(f"{off}: unexpected dry-deposition-off configuration")
    if on_config["operations"]["dry_deposition"] != {"activate": True}:
        raise ValueError(f"{on}: unexpected dry-deposition-on configuration")
    on_config["operations"]["dry_deposition"]["activate"] = False
    if on_config != off_config:
        raise ValueError("dry-deposition A/B configs differ beyond dry_deposition.activate")


def require_inactive_post_convection(run: Path) -> None:
    """Keep chemistry and wet-deposition checkpoint boundaries exact no-ops."""

    for time in TIMES:
        for tag in TAGS:
            reference = plume_mass(run, "C4_POST_CONVECTION", time, tag)
            for label in ("C5_POST_CHEMISTRY", "C6_POST_WETDEP"):
                if not np.array_equal(reference, plume_mass(run, label, time, tag)):
                    raise ValueError(f"inactive operator changed {tag}: {run.name} {label} {time}")


def require_species_contract(run: Path) -> None:
    database = yaml.safe_load((run / "species_database.yml").read_text(encoding="utf-8"))
    required = {
        "Background_VV": 1.0e-20,
        "DD_DvzAerSnow": 0.03,
        "DD_F0": 0.0,
        "DD_Hstar": 0.0,
        "Density": 1300.0,
        "Is_Aerosol": True,
        "Is_DryDep": True,
        "Is_Tracer": True,
        "MW_g": 12.01,
        "Snk_Mode": "none",
        "Src_Add": True,
        "Src_Mode": "HEMCO",
    }
    forbidden = {
        "Is_Gas",
        "Is_WetDep",
        "Is_HygroGrowth",
        "DD_AeroDryDep",
        "DD_DustDryDep",
        "Radius",
    }
    for tag in TAGS:
        entry = database.get(tag)
        if not isinstance(entry, dict):
            raise ValueError(f"{run}: species database is missing {tag}")
        for name, expected in required.items():
            if entry.get(name) != expected:
                raise ValueError(f"{run}: {tag}.{name} differs from drydep contract")
        present = forbidden.intersection(entry)
        if present:
            raise ValueError(f"{run}: {tag} contains forbidden fields {sorted(present)}")


def require_input_identity(runs: tuple[Path, ...]) -> dict[str, str]:
    inputs = {
        "executable": Path("gcclassic"),
        "source": Path("PlumeSource.20190101_0000z.nc"),
        "initial_restart": Path("Restarts/GEOSChem.Restart.20190101_0000z.nc4"),
        "species_database": Path("species_database.yml"),
        "hemco_config": Path("HEMCO_Config.rc"),
        "hemco_met_config": Path("HEMCO_Config.rc.gmao_metfields"),
        "hemco_diagnostics": Path("HEMCO_Diagn.rc"),
        "history_config": Path("HISTORY.rc"),
    }
    result: dict[str, str] = {}
    for role, relative in inputs.items():
        hashes = {sha256(run / relative) for run in runs}
        if len(hashes) != 1:
            raise ValueError(f"{role} is not byte-identical across all controls")
        result[f"{role}_sha256"] = hashes.pop()
    for run in runs:
        require_species_contract(run)
    return result


def require_thread_identity(one: Path, eight: Path) -> dict[str, object]:
    checked = 0
    for time in TIMES:
        for label in LABELS:
            for tag in TAGS:
                left = plume_mass(one, label, time, tag)
                right = plume_mass(eight, label, time, tag)
                if not np.array_equal(left, right):
                    maximum = float(np.max(np.abs(left - right)))
                    raise ValueError(
                        f"thread checkpoint mismatch: {one.name} {label} {time} {tag} ({maximum})"
                    )
                checked += 1
    return {"status": "pass", "arrays_checked": checked, "exactly_equal": True}


def require_qck_v2_thread_identity(one: Path, eight: Path) -> dict[str, object]:
    """Require matching survey-free QCK v2 acceptance summaries by thread count."""

    left = common.read_qck_v2_summary(one)
    right = common.read_qck_v2_summary(eight)
    if left != right:
        raise ValueError(f"QCK v2 summaries differ between thread counts: {one} vs {eight}")
    return {
        "status": "PASS",
        "event_count": int(left["event_count"]),
        "microclosure_total_kg": float(left["microclosure_total_kg"]),
        "microclosure_by_tag_kg": left["microclosure_by_tag_kg"],
        "survey_artifacts": "absent",
    }


def _text_attribute(variable: h5py.Dataset, name: str) -> str:
    if name not in variable.attrs:
        raise KeyError(f"{variable.name} is missing {name}")
    value = variable.attrs[name]
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _dimension_names(variable: h5py.Dataset) -> tuple[str, ...]:
    names: list[str] = []
    for dimension in variable.dims:
        scales = list(dimension.keys())
        if len(scales) != 1:
            raise ValueError(
                f"{variable.name}: expected one named scale per dimension, got {scales}"
            )
        names.append(scales[0])
    return tuple(names)


def _require_dimensions(variable: h5py.Dataset, expected: tuple[str, ...]) -> None:
    actual = _dimension_names(variable)
    if actual != expected:
        raise ValueError(f"{variable.name}: dimensions {actual} != {expected}")


def _drydep_files(run: Path) -> list[Path]:
    matches = sorted((run / "OutputDir").glob("GEOSChem.DryDep.*.nc4"))
    if not matches:
        raise ValueError(f"{run}: no DryDep files found")
    return matches


def _budget_files(run: Path) -> list[Path]:
    matches = sorted((run / "OutputDir").glob("GEOSChem.Budget.*.nc4"))
    if not matches:
        raise ValueError(f"{run}: no Budget files found")
    return matches


def absolute_record_times_seconds(values: np.ndarray, units: str) -> np.ndarray:
    """Convert a netCDF relative-time coordinate to absolute UTC seconds."""
    time = np.asarray(values, dtype=np.float64)
    if time.ndim != 1 or np.any(~np.isfinite(time)):
        raise ValueError("diagnostic time coordinate must be one-dimensional and finite")
    lowered = units.lower()
    if lowered.startswith("seconds since"):
        scale = 1.0
    elif lowered.startswith("minutes since"):
        scale = 60.0
    elif lowered.startswith("hours since"):
        scale = 3600.0
    else:
        raise ValueError(f"unsupported diagnostic time units: {units!r}")
    reference_text = units.split(" since ", 1)[1].strip()
    for suffix in (" GMT", " UTC"):
        if reference_text.upper().endswith(suffix):
            reference_text = reference_text[: -len(suffix)].strip()
            break
    reference_text = reference_text.removesuffix("Z")
    try:
        reference = datetime.fromisoformat(reference_text)
    except ValueError as error:
        raise ValueError(f"invalid diagnostic time reference: {units!r}") from error
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    else:
        reference = reference.astimezone(timezone.utc)
    return reference.timestamp() + time * scale


def _record_times(dataset: h5py.File) -> np.ndarray:
    return absolute_record_times_seconds(
        np.asarray(dataset["time"][:], dtype=np.float64),
        _text_attribute(dataset["time"], "units"),
    )


def _heartbeat_order(times: list[np.ndarray], label: str) -> np.ndarray:
    combined = np.concatenate(times)
    if combined.shape != (2,) or np.any(~np.isfinite(combined)):
        raise ValueError(f"{label} must contain exactly two finite records in total")
    order = np.argsort(combined, kind="stable")
    ordered = combined[order]
    if not np.isclose(
        ordered[1] - ordered[0], HEARTBEAT_SECONDS, rtol=0.0, atol=1.0e-6
    ):
        raise ValueError(f"{label} records are not separated by one 600-second heartbeat")
    return order


def read_drydep_diagnostics(run: Path) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]]:
    times: list[np.ndarray] = []
    area: np.ndarray | None = None
    flux_parts: dict[str, list[np.ndarray]] = {tag: [] for tag in TAGS}
    velocity_parts: dict[str, list[np.ndarray]] = {tag: [] for tag in TAGS}
    for path in _drydep_files(run):
        with h5py.File(path, "r") as dataset:
            file_times = _record_times(dataset)
            times.append(file_times)
            file_area = np.asarray(dataset["AREA"][:], dtype=np.float64)
            _require_dimensions(dataset["AREA"], ("lat", "lon"))
            if (
                file_area.shape != (46, 72)
                or np.any(~np.isfinite(file_area))
                or np.any(file_area <= 0.0)
            ):
                raise ValueError(f"{run}: invalid DryDep AREA")
            if _text_attribute(dataset["AREA"], "units") != "m2":
                raise ValueError(f"{run}: DryDep AREA units are not m2")
            if area is None:
                area = file_area
            elif not np.array_equal(area, file_area):
                raise ValueError(f"{run}: DryDep AREA differs between segmented files")
            for tag in TAGS:
                flux_variable = dataset[f"DryDepMix_{tag}"]
                velocity_variable = dataset[f"DryDepVel_{tag}"]
                _require_dimensions(flux_variable, ("time", "lat", "lon"))
                _require_dimensions(velocity_variable, ("time", "lat", "lon"))
                flux = np.asarray(flux_variable[:], dtype=np.float64)
                velocity = np.asarray(velocity_variable[:], dtype=np.float64)
                expected_shape = (file_times.size, 46, 72)
                if flux.shape != expected_shape or velocity.shape != expected_shape:
                    raise ValueError(f"{run}: unexpected DryDep shape for {tag}")
                if np.any(~np.isfinite(flux)) or np.any(flux < 0.0):
                    raise ValueError(f"{run}: invalid DryDepMix for {tag}")
                if np.any(~np.isfinite(velocity)) or np.any(velocity < 0.0):
                    raise ValueError(f"{run}: invalid DryDepVel for {tag}")
                flux_units = _text_attribute(flux_variable, "units").replace(" ", "")
                if flux_units not in {"molec/cm2/s", "moleccm-2s-1"}:
                    raise ValueError(f"{run}: unexpected DryDepMix units {flux_units!r}")
                flux_parts[tag].append(flux)
                velocity_parts[tag].append(velocity)
    order = _heartbeat_order(times, "DryDep diagnostic")
    if area is None:
        raise ValueError(f"{run}: no DryDep AREA was read")
    fluxes = {
        tag: np.concatenate(flux_parts[tag], axis=0)[order] for tag in TAGS
    }
    velocities = {
        tag: np.concatenate(velocity_parts[tag], axis=0)[order] for tag in TAGS
    }
    reference = velocities[TAGS[0]]
    for tag in TAGS[1:]:
        if not np.array_equal(reference, velocities[tag]):
            raise ValueError(f"{run}: DryDepVel differs despite identical properties: {tag}")
    return area, fluxes, velocities


def read_budget_diagnostics(run: Path) -> dict[str, np.ndarray]:
    """Read fail-closed net emissions/dry-deposition budget rates [kg s-1]."""
    times: list[np.ndarray] = []
    area: np.ndarray | None = None
    parts: dict[str, list[np.ndarray]] = {tag: [] for tag in TAGS}
    for path in _budget_files(run):
        with h5py.File(path, "r") as dataset:
            file_times = _record_times(dataset)
            times.append(file_times)
            file_area = np.asarray(dataset["AREA"][:], dtype=np.float64)
            _require_dimensions(dataset["AREA"], ("lat", "lon"))
            if (
                file_area.shape != (46, 72)
                or np.any(~np.isfinite(file_area))
                or np.any(file_area <= 0.0)
            ):
                raise ValueError(f"{run}: invalid Budget AREA")
            if _text_attribute(dataset["AREA"], "units") != "m2":
                raise ValueError(f"{run}: Budget AREA units are not m2")
            if area is None:
                area = file_area
            elif not np.array_equal(area, file_area):
                raise ValueError(f"{run}: Budget AREA differs between segmented files")
            for tag in TAGS:
                name = f"BudgetEmisDryDepFull_{tag}"
                variable = dataset[name]
                _require_dimensions(variable, ("time", "lat", "lon"))
                if _text_attribute(variable, "units") != "kg s-1":
                    raise ValueError(f"{run}: {name} units are not kg s-1")
                if _text_attribute(variable, "averaging_method") != "time-averaged":
                    raise ValueError(f"{run}: {name} is not a time average")
                values = np.asarray(variable[:], dtype=np.float64)
                if values.shape != (file_times.size, 46, 72) or np.any(~np.isfinite(values)):
                    raise ValueError(f"{run}: invalid {name}")
                parts[tag].append(values)
    order = _heartbeat_order(times, "Budget diagnostic")
    return {tag: np.concatenate(parts[tag], axis=0)[order] for tag in TAGS}


def require_drydep_thread_identity(
    one: tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]],
    eight: tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]],
) -> dict[str, object]:
    one_area, one_fluxes, one_velocities = one
    eight_area, eight_fluxes, eight_velocities = eight
    if not np.array_equal(one_area, eight_area):
        raise ValueError("DryDep diagnostic AREA differs between thread counts")
    checked = 1
    for tag in TAGS:
        for name, left, right in (
            ("DryDepMix", one_fluxes[tag], eight_fluxes[tag]),
            ("DryDepVel", one_velocities[tag], eight_velocities[tag]),
        ):
            if not np.array_equal(left, right):
                maximum = float(np.max(np.abs(left - right)))
                raise ValueError(f"{name}_{tag} differs between thread counts ({maximum})")
            checked += 1
    return {"status": "pass", "arrays_checked": checked, "exactly_equal": True}


def require_budget_thread_identity(
    one: dict[str, np.ndarray], eight: dict[str, np.ndarray]
) -> dict[str, object]:
    for tag in TAGS:
        if not np.array_equal(one[tag], eight[tag]):
            maximum = float(np.max(np.abs(one[tag] - eight[tag])))
            raise ValueError(
                f"BudgetEmisDryDepFull_{tag} differs between thread counts ({maximum})"
            )
    return {"status": "pass", "arrays_checked": len(TAGS), "exactly_equal": True}


def validate(off_one: Path, off_eight: Path, on_one: Path, on_eight: Path) -> dict[str, Any]:
    runs = tuple(path.resolve() for path in (off_one, off_eight, on_one, on_eight))
    off_one, off_eight, on_one, on_eight = runs
    require_case_config(off_one, on_one)
    require_case_config(off_eight, on_eight)
    if load_config(off_one) != load_config(off_eight):
        raise ValueError("dry-deposition-off config differs between thread counts")
    if load_config(on_one) != load_config(on_eight):
        raise ValueError("dry-deposition-on config differs between thread counts")
    for run in runs:
        require_inactive_post_convection(run)

    input_identity = require_input_identity(runs)
    thread_determinism = {
        "drydep_off": require_thread_identity(off_one, off_eight),
        "drydep_on": require_thread_identity(on_one, on_eight),
    }
    qck_determinism = {
        "drydep_off": require_qck_v2_thread_identity(off_one, off_eight),
        "drydep_on": require_qck_v2_thread_identity(on_one, on_eight),
    }

    on_diagnostics = read_drydep_diagnostics(on_one)
    on_eight_diagnostics = read_drydep_diagnostics(on_eight)
    thread_determinism["drydep_native_diagnostics"] = require_drydep_thread_identity(
        on_diagnostics, on_eight_diagnostics
    )
    area, fluxes, velocities = on_diagnostics
    off_budget = read_budget_diagnostics(off_one)
    off_eight_budget = read_budget_diagnostics(off_eight)
    on_budget = read_budget_diagnostics(on_one)
    on_eight_budget = read_budget_diagnostics(on_eight)
    thread_determinism["drydep_off_budget"] = require_budget_thread_identity(
        off_budget, off_eight_budget
    )
    thread_determinism["drydep_on_budget"] = require_budget_thread_identity(
        on_budget, on_eight_budget
    )
    loss_by_time: dict[str, dict[str, dict[str, float | bool | str]]] = {}
    for heartbeat, time in enumerate(TIMES):
        by_tag: dict[str, dict[str, float | bool | str]] = {}
        for tag in TAGS:
            off_increment_3d = (
                plume_mass(off_one, "C3_POST_MIXING", time, tag)
                - plume_mass(off_one, "C2_FLUX_READY", time, tag)
            )
            on_increment_3d = (
                plume_mass(on_one, "C3_POST_MIXING", time, tag)
                - plume_mass(on_one, "C2_FLUX_READY", time, tag)
            )
            off_increment = float(off_increment_3d.sum(dtype=np.float64))
            on_increment = float(on_increment_3d.sum(dtype=np.float64))
            checkpoint_loss = checkpoint_drydep_loss_kg(off_increment, on_increment)
            budget_loss = budget_drydep_loss_kg(
                off_budget[tag][heartbeat], on_budget[tag][heartbeat]
            )
            reconciled = reconcile_losses(checkpoint_loss, budget_loss)
            checkpoint_loss_by_column = (off_increment_3d - on_increment_3d).sum(
                axis=0, dtype=np.float64
            )
            budget_loss_by_column = (
                off_budget[tag][heartbeat] - on_budget[tag][heartbeat]
            ) * HEARTBEAT_SECONDS
            column_difference_l1 = float(
                np.abs(checkpoint_loss_by_column - budget_loss_by_column).sum(
                    dtype=np.float64
                )
            )
            column_reference_l1 = float(
                np.abs(budget_loss_by_column).sum(dtype=np.float64)
            )
            column_tolerance = max(
                BUDGET_HISTORY_ABSOLUTE_PRECISION_KG,
                BUDGET_HISTORY_RELATIVE_PRECISION * column_reference_l1,
            )
            if column_difference_l1 > column_tolerance:
                raise ValueError(
                    f"Budget/checkpoint column-L1 mismatch: {time} {tag} "
                    f"({column_difference_l1} kg > {column_tolerance} kg)"
                )
            last_layer_equivalent = drydep_flux_to_mass_kg(
                fluxes[tag][heartbeat], area
            )
            by_tag[tag] = {
                "source_from_off_checkpoint_kg": off_increment,
                "on_source_minus_deposition_increment_kg": on_increment,
                **reconciled,
                "budget_on_minus_off_kg": -budget_loss,
                "budget_checkpoint_column_residual_l1_kg": column_difference_l1,
                "budget_column_reference_l1_kg": column_reference_l1,
                "budget_checkpoint_column_tolerance_kg": column_tolerance,
                "drydepmix_last_processed_layer_equivalent_kg": last_layer_equivalent,
                "drydepmix_interpretation": (
                    "qualitative only: full-PBL mixing overwrites DryDepMix at each "
                    "level, so this is the final processed layer rather than total loss"
                ),
            }
        loss_by_time[time] = by_tag

    inactive = [
        tag for tag in sorted(ACTIVE_LOSS_TAGS)
        if float(loss_by_time[TIMES[1]][tag]["checkpoint_loss_kg"]) <= ACTIVE_LOSS_KG
    ]
    if inactive:
        raise ValueError(f"heartbeat 2 did not exercise dry deposition for {inactive}")

    qck_off = common.read_qck_v2_summary(off_one)
    qck_on = common.read_qck_v2_summary(on_one)
    total_deposited = {
        tag: sum(float(loss_by_time[time][tag]["checkpoint_loss_kg"]) for time in TIMES)
        for tag in TAGS
    }
    endpoints = {
        mode: {
            tag: float(plume_mass(run, "C6_POST_WETDEP", TIMES[1], tag).sum(dtype=np.float64))
            for tag in TAGS
        }
        for mode, run in (("drydep_off", off_one), ("drydep_on", on_one))
    }
    return {
        "status": "diagnostic_pass_bounded_qck_v2",
        "scientific_acceptance": False,
        "qck_policy": "conservative full-column QCK_BOTTOM with bounded v2 microclosure",
        "operator_under_test": "native full-PBL dry deposition with convection retained",
        "input_identity": input_identity,
        "thread_determinism": thread_determinism,
        "qck_thread_determinism": qck_determinism,
        "acceptance": {
            "budget_history_absolute_precision_kg": BUDGET_HISTORY_ABSOLUTE_PRECISION_KG,
            "budget_history_relative_precision": BUDGET_HISTORY_RELATIVE_PRECISION,
            "mass_reconciliation_diagnostic": (
                "drydep-on minus drydep-off BudgetEmisDryDepFull at each heartbeat"
            ),
            "budget_units": "kg s-1",
            "budget_heartbeat_seconds": int(HEARTBEAT_SECONDS),
            "budget_history_precision_basis": (
                "float32 A/B subtraction of two net source budgets near 0.833 kg s-1; "
                "half-ULP per arm over 600 s is approximately 3.58e-5 kg"
            ),
            "checkpoint_loss_is_authoritative": True,
            "active_loss_threshold_kg": ACTIVE_LOSS_KG,
            "active_loss_required_tags": sorted(ACTIVE_LOSS_TAGS),
            "plume_lev_zero_loss_allowed": True,
            "drydep_velocity_finite_nonnegative_tag_identical": True,
        },
        "drydep_loss_by_heartbeat": loss_by_time,
        "total_checkpoint_deposited_kg": total_deposited,
        "drydep_velocity": {
            "minimum": float(velocities[TAGS[0]].min()),
            "maximum": float(velocities[TAGS[0]].max()),
            "tag_identical": True,
            "heartbeat_2_may_be_reused": True,
            "recomputation_cadence_seconds": 1200,
        },
        "drydepmix_limitation": (
            "DryDepMix is qualitative/thread-determinism evidence only for full-PBL "
            "mixing because the array is overwritten for each processed level; it is "
            "not used as a total-mass reconciliation diagnostic."
        ),
        "qck_microclosure": {
            "drydep_off_kg": float(qck_off["microclosure_total_kg"]),
            "drydep_on_kg": float(qck_on["microclosure_total_kg"]),
            "drydep_on_minus_off_kg": float(qck_on["microclosure_total_kg"])
            - float(qck_off["microclosure_total_kg"]),
            "drydep_off_event_count": int(qck_off["event_count"]),
            "drydep_on_event_count": int(qck_on["event_count"]),
            "all_controls": {
                "drydep_off_1thread": common.read_qck_v2_summary(off_one),
                "drydep_off_8thread": common.read_qck_v2_summary(off_eight),
                "drydep_on_1thread": common.read_qck_v2_summary(on_one),
                "drydep_on_8thread": common.read_qck_v2_summary(on_eight),
            },
        },
        "endpoint_airborne_mass_kg": endpoints,
        "guardrail": (
            "Dry-deposition behavior is diagnostic only; production and scientific "
            "interpretation remain blocked; bounded v2 is a diagnostic policy, "
            "not scientific acceptance."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("off_one", type=Path)
    parser.add_argument("off_eight", type=Path)
    parser.add_argument("on_one", type=Path)
    parser.add_argument("on_eight", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.off_one, args.off_eight, args.on_one, args.on_eight)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
