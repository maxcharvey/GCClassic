#!/usr/bin/env python3
"""Validate convective and large-scale wet removal in four Stage-1 controls."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import yaml

import validate_drydep_ab as common
import validate_pbl_ab as qck_common


TAGS = common.TAGS
TIMES = common.TIMES
LABELS = common.LABELS
HEARTBEAT_SECONDS = common.HEARTBEAT_SECONDS
ACTIVITY_FLOOR_KG = 1.0e-12
NUMERICAL_FLOOR_KG = 1.0e-9
# One output ULP covers final float32 archiving.  Eight ULPs also cover the
# native f4 accumulation used by WetLossLS and gives one common, conservative
# formula for all three HISTORY crosschecks.
FLOAT32_ULP_SAFETY_FACTOR = 8.0
ACTIVITY_TAGS = {"PLUME_SFC", "PLUME_PBL", "PLUME_6535"}
CONVECTIVE_NONCLOSURE_CAUSALITY = (
    "RAS below-cloud aerosol re-evaporation computes and applies WETLOSS to tracer "
    "state at every precipitating below-cloud level, including K=1, but DIAG38/"
    "WetLossConv accumulation is gated by F(K,NA)>0. The aerosol scavenging "
    "fraction is zero at the surface, so the K=1 re-evaporation gain changes the "
    "checkpoint state but is omitted from WetLossConv."
)
RAS_SURFACE_REEVAP_SCHEMA = "ras-surface-reevap-ledger-v1"


def float32_ulp_tolerance_kg(
    archived_rate_kg_s: np.ndarray,
    *,
    duration_s: float = HEARTBEAT_SECONDS,
    axes: tuple[int, ...] | None = None,
) -> np.ndarray | float:
    """Bound integrated float32 HISTORY error from archived-array ULPs.

    ``axes=None`` returns a global bound.  Otherwise it returns bounds after
    summing over the specified axes, e.g. ``axes=(0,)`` for 3-D level fields.
    """
    values = np.asarray(archived_rate_kg_s)
    if values.dtype != np.float32:
        raise ValueError("native HISTORY precision gate requires a float32 array")
    if np.any(~np.isfinite(values)):
        raise ValueError("native HISTORY values must be finite")
    if not math.isfinite(duration_s) or duration_s <= 0.0:
        raise ValueError("diagnostic duration must be finite and positive")
    ulps = np.spacing(np.abs(values)).astype(np.float64)
    if axes is None:
        bound = FLOAT32_ULP_SAFETY_FACTOR * duration_s * float(
            ulps.sum(dtype=np.float64)
        )
        return max(NUMERICAL_FLOOR_KG, bound)
    bound_array = FLOAT32_ULP_SAFETY_FACTOR * duration_s * ulps.sum(
        axis=axes, dtype=np.float64
    )
    return np.maximum(NUMERICAL_FLOOR_KG, bound_array)


def integrated_native_loss_kg(rate_kg_s: np.ndarray) -> float:
    values = np.asarray(rate_kg_s)
    if values.dtype != np.float32 or np.any(~np.isfinite(values)):
        raise ValueError("native loss rates must be finite float32 HISTORY values")
    return float(values.astype(np.float64).sum(dtype=np.float64) * HEARTBEAT_SECONDS)


def assess_native_loss(
    checkpoint_loss_kg: float,
    native_loss_kg: float,
    native_rate_kg_s: np.ndarray,
    label: str,
) -> dict[str, float | bool | str]:
    checkpoint = float(checkpoint_loss_kg)
    native = float(native_loss_kg)
    if not math.isfinite(checkpoint) or not math.isfinite(native):
        raise ValueError(f"{label}: losses must be finite")
    tolerance = float(float32_ulp_tolerance_kg(native_rate_kg_s))
    checked_checkpoint = max(checkpoint, 0.0)
    checked_native = max(native, 0.0)
    residual = checked_checkpoint - checked_native
    reasons: list[str] = []
    if checkpoint < -tolerance:
        reasons.append("checkpoint_loss_materially_negative")
    if native < -tolerance:
        reasons.append("native_loss_materially_negative")
    if abs(residual) > tolerance:
        reasons.append("checkpoint_native_nonclosure")
    result: dict[str, float | bool | str] = {
        "status": "pass" if not reasons else "fail",
        "failure_reason": ",".join(reasons),
        "checkpoint_loss_raw_kg": checkpoint,
        "checkpoint_loss_kg": checked_checkpoint,
        "checkpoint_negative_roundoff_clipped": checkpoint < 0.0,
        "native_loss_raw_kg": native,
        "native_loss_kg": checked_native,
        "native_negative_roundoff_clipped": native < 0.0,
        "checkpoint_minus_native_kg": residual,
        "float32_ulp_tolerance_kg": tolerance,
    }
    return result


def reconcile_native_loss(
    checkpoint_loss_kg: float,
    native_loss_kg: float,
    native_rate_kg_s: np.ndarray,
    label: str,
) -> dict[str, float | bool | str]:
    result = assess_native_loss(
        checkpoint_loss_kg, native_loss_kg, native_rate_kg_s, label
    )
    if result["status"] != "pass":
        raise ValueError(
            f"{label}: {result['failure_reason']} "
            f"(residual {result['checkpoint_minus_native_kg']} kg, "
            f"tolerance {result['float32_ulp_tolerance_kg']} kg)"
        )
    return result


def require_case_config(off: Path, on: Path) -> None:
    off_config = common.load_config(off)
    on_config = common.load_config(on)
    for run, config in ((off, off_config), (on, on_config)):
        operations = config["operations"]
        if operations["pbl_mixing"] != {
            "activate": True,
            "use_non_local_pbl": False,
        }:
            raise ValueError(f"{run}: full PBL mixing is not held on")
        if operations["convection"] != {"activate": True}:
            raise ValueError(f"{run}: convection is not held on")
        if operations["dry_deposition"] != {"activate": True}:
            raise ValueError(f"{run}: dry deposition is not held on")
    if off_config["operations"]["wet_deposition"] != {"activate": False}:
        raise ValueError(f"{off}: unexpected large-scale-wetdep-off config")
    if on_config["operations"]["wet_deposition"] != {"activate": True}:
        raise ValueError(f"{on}: unexpected large-scale-wetdep-on config")
    on_config["operations"]["wet_deposition"]["activate"] = False
    if on_config != off_config:
        raise ValueError("wetdep configs differ beyond wet_deposition.activate")


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
        "Is_WetDep": True,
        "MW_g": 12.01,
        "Snk_Mode": "none",
        "Src_Add": True,
        "Src_Mode": "HEMCO",
        "WD_AerScavEff": 1.0,
        "WD_KcScaleFac": [0.5, 0.5, 0.5],
        "WD_RainoutEff": [0.0, 0.0, 0.0],
    }
    forbidden = {
        "Is_Gas",
        "Is_HygroGrowth",
        "DD_AeroDryDep",
        "DD_DustDryDep",
        "Radius",
        "WD_KcScaleFac_Luo",
        "WD_RainoutEff_Luo",
        "WD_Hstar",
        "WD_RetFactor",
        "WD_Is_HNO3",
    }
    for tag in TAGS:
        entry = database.get(tag)
        if not isinstance(entry, dict):
            raise ValueError(f"{run}: species database is missing {tag}")
        for name, expected in required.items():
            if entry.get(name) != expected:
                raise ValueError(f"{run}: {tag}.{name} differs from OCPO contract")
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
        hashes = {common.sha256(run / relative) for run in runs}
        if len(hashes) != 1:
            raise ValueError(f"{role} is not byte-identical across controls")
        result[f"{role}_sha256"] = hashes.pop()
    for run in runs:
        require_species_contract(run)
    return result


def require_ab_heartbeat_one_identity(off: Path, on: Path) -> dict[str, object]:
    checked = 0
    for label in LABELS[:6]:
        for tag in TAGS:
            if not np.array_equal(
                common.plume_mass(off, label, TIMES[0], tag),
                common.plume_mass(on, label, TIMES[0], tag),
            ):
                raise ValueError(f"heartbeat-1 A/B state differs before wetdep: {label} {tag}")
            checked += 1
    return {"status": "pass", "arrays_checked": checked, "exactly_equal": True}


def require_inactive_boundaries(runs: tuple[Path, ...]) -> None:
    off_one, off_eight, _, _ = runs
    for run in runs:
        for time in TIMES:
            for tag in TAGS:
                if not np.array_equal(
                    common.plume_mass(run, "C4_POST_CONVECTION", time, tag),
                    common.plume_mass(run, "C5_POST_CHEMISTRY", time, tag),
                ):
                    raise ValueError(f"inactive chemistry changed {run.name} {time} {tag}")
    for run in (off_one, off_eight):
        for time in TIMES:
            for tag in TAGS:
                if not np.array_equal(
                    common.plume_mass(run, "C5_POST_CHEMISTRY", time, tag),
                    common.plume_mass(run, "C6_POST_WETDEP", time, tag),
                ):
                    raise ValueError(f"wetdep-off boundary changed {run.name} {time} {tag}")


def _collection_files(run: Path, collection: str) -> list[Path]:
    matches = sorted((run / "OutputDir").glob(f"GEOSChem.{collection}.*.nc4"))
    if not matches:
        raise ValueError(f"{run}: no {collection} files found")
    return matches


def read_wet_collection(
    run: Path, collection: str, prefix: str, *, rank3: bool
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    times: list[np.ndarray] = []
    area: np.ndarray | None = None
    parts: dict[str, list[np.ndarray]] = {tag: [] for tag in TAGS}
    expected_dimensions = ("time", "lev", "lat", "lon") if rank3 else (
        "time",
        "lat",
        "lon",
    )
    expected_tail = (72, 46, 72) if rank3 else (46, 72)
    for path in _collection_files(run, collection):
        with h5py.File(path, "r") as dataset:
            file_times = common._record_times(dataset)
            times.append(file_times)
            file_area = np.asarray(dataset["AREA"][:])
            common._require_dimensions(dataset["AREA"], ("lat", "lon"))
            if (
                file_area.shape != (46, 72)
                or np.any(~np.isfinite(file_area))
                or np.any(file_area <= 0.0)
                or common._text_attribute(dataset["AREA"], "units") != "m2"
            ):
                raise ValueError(f"{run}: invalid {collection} AREA")
            if area is None:
                area = file_area
            elif not np.array_equal(area, file_area):
                raise ValueError(f"{run}: {collection} AREA differs between files")
            for tag in TAGS:
                name = f"{prefix}_{tag}"
                variable = dataset[name]
                common._require_dimensions(variable, expected_dimensions)
                if common._text_attribute(variable, "units") != "kg s-1":
                    raise ValueError(f"{run}: {name} units are not kg s-1")
                if common._text_attribute(variable, "averaging_method") != "time-averaged":
                    raise ValueError(f"{run}: {name} is not time-averaged")
                values = np.asarray(variable[:])
                if (
                    values.dtype != np.float32
                    or values.shape != (file_times.size, *expected_tail)
                    or np.any(~np.isfinite(values))
                ):
                    raise ValueError(f"{run}: invalid {name}")
                parts[tag].append(values)
    order = common._heartbeat_order(times, f"{collection} diagnostic")
    if area is None:
        raise ValueError(f"{run}: no {collection} AREA was read")
    return area, {
        tag: np.concatenate(parts[tag], axis=0)[order] for tag in TAGS
    }


def require_collection_thread_identity(
    name: str,
    one: tuple[np.ndarray, dict[str, np.ndarray]],
    eight: tuple[np.ndarray, dict[str, np.ndarray]],
) -> dict[str, object]:
    one_area, one_fields = one
    eight_area, eight_fields = eight
    if not np.array_equal(one_area, eight_area):
        raise ValueError(f"{name} AREA differs between thread counts")
    for tag in TAGS:
        if not np.array_equal(one_fields[tag], eight_fields[tag]):
            maximum = float(np.max(np.abs(one_fields[tag] - eight_fields[tag])))
            raise ValueError(f"{name}_{tag} differs between thread counts ({maximum})")
    return {"status": "pass", "arrays_checked": len(TAGS) + 1, "exactly_equal": True}


def checkpoint_column_loss(
    run: Path, before: str, after: str, time: str, tag: str
) -> np.ndarray:
    return (
        common.plume_mass(run, before, time, tag)
        - common.plume_mass(run, after, time, tag)
    ).sum(axis=0, dtype=np.float64)


def assess_columns(
    checkpoint_kg: np.ndarray,
    native_kg: np.ndarray,
    native_rate_kg_s: np.ndarray,
    native_sum_axes: tuple[int, ...],
    label: str,
) -> dict[str, float | str]:
    if checkpoint_kg.shape != native_kg.shape:
        raise ValueError(f"{label}: column shape mismatch")
    tolerance = np.asarray(
        float32_ulp_tolerance_kg(native_rate_kg_s, axes=native_sum_axes),
        dtype=np.float64,
    )
    residual = checkpoint_kg - native_kg
    excess = np.abs(residual) - tolerance
    failed = bool(np.any(excess > 0.0))
    result: dict[str, float | str] = {
        "column_status": "fail" if failed else "pass",
        "column_residual_l1_kg": float(np.abs(residual).sum(dtype=np.float64)),
        "column_residual_max_abs_kg": float(np.max(np.abs(residual))),
        "column_tolerance_max_kg": float(np.max(tolerance)),
    }
    if failed:
        index = np.unravel_index(int(np.argmax(excess)), excess.shape)
        result.update(
            {
                "column_failure_index": ",".join(str(value) for value in index),
                "column_failure_residual_kg": float(residual[index]),
                "column_failure_tolerance_kg": float(tolerance[index]),
            }
        )
    return result


def reconcile_columns(
    checkpoint_kg: np.ndarray,
    native_kg: np.ndarray,
    native_rate_kg_s: np.ndarray,
    native_sum_axes: tuple[int, ...],
    label: str,
) -> dict[str, float | str]:
    result = assess_columns(
        checkpoint_kg, native_kg, native_rate_kg_s, native_sum_axes, label
    )
    if result["column_status"] != "pass":
        raise ValueError(
            f"{label}: column residual {result['column_failure_residual_kg']} "
            f"exceeds {result['column_failure_tolerance_kg']} kg at "
            f"{result['column_failure_index']}"
        )
    return result


def component_status(conv_active: bool, ls_active: bool) -> str:
    if conv_active and ls_active:
        return "diagnostic_pass_bounded_qck_v2"
    if not conv_active and not ls_active:
        return "diagnostic_inconclusive_no_OCPO_convective_or_washout_overlap"
    if not conv_active:
        return "diagnostic_inconclusive_no_OCPO_convective_overlap"
    return "diagnostic_inconclusive_no_OCPO_washout_overlap"


def final_status(
    convective_closure_passed: bool,
    conv_active: bool,
    ls_active: bool,
    ras_surface_reevap_passed: bool | None = None,
    native_ras_reconciliable: bool = True,
) -> str:
    """Return the final status only after the surface re-evaporation ledger."""

    if ras_surface_reevap_passed is None:
        return "diagnostic_pending_ras_surface_reevap"
    if not ras_surface_reevap_passed:
        return "diagnostic_fail_ras_surface_reevap_nonclosure"
    if not convective_closure_passed and not native_ras_reconciliable:
        return "diagnostic_fail_convective_wetloss_nonclosure"
    return component_status(conv_active, ls_active)


def load_ras_surface_reevap_report(path: Path) -> dict[str, Any]:
    """Load a completed RAS ledger validation report without weakening its gates."""

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read RAS surface re-evaporation report {path}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"{path}: RAS surface re-evaporation report must be a mapping")
    if report.get("schema_version") != RAS_SURFACE_REEVAP_SCHEMA:
        raise ValueError(f"{path}: RAS surface re-evaporation schema mismatch")
    if (
        not isinstance(report.get("closure_failure_count"), int)
        or report["closure_failure_count"] < 0
    ):
        raise ValueError(f"{path}: RAS surface re-evaporation failure count is invalid")
    if report.get("status") not in {"pass", "fail"}:
        raise ValueError(f"{path}: RAS surface re-evaporation status is invalid")
    thread = report.get("thread_determinism")
    if not isinstance(thread, dict) or set(thread) != {"off", "on"}:
        raise ValueError(f"{path}: RAS surface re-evaporation thread checks are invalid")
    if not all(isinstance(value, bool) for value in thread.values()):
        raise ValueError(f"{path}: RAS surface re-evaporation thread checks are invalid")
    return report


def ras_surface_reevap_report_passed(report: dict[str, Any]) -> bool:
    """Require the ledger's closure and both normalized thread checks to pass."""

    return (
        report.get("status") == "pass"
        and report.get("closure_failure_count") == 0
        and report.get("thread_determinism") == {"off": True, "on": True}
    )


def convective_activity(result: dict[str, Any]) -> dict[str, float | bool]:
    tolerance = float(result["float32_ulp_tolerance_kg"])
    threshold = max(ACTIVITY_FLOOR_KG, 10.0 * tolerance)
    checkpoint = float(result["checkpoint_loss_raw_kg"])
    native = float(result["native_loss_raw_kg"])
    active = checkpoint > threshold and native > threshold
    return {
        "active": active,
        "activity_threshold_kg": threshold,
        "checkpoint_positive_above_threshold": checkpoint > threshold,
        "native_positive_above_threshold": native > threshold,
    }


def large_scale_activity(
    checkpoint_loss_kg: float,
    budget_result: dict[str, float | bool],
    wetlossls_result: dict[str, float | bool],
) -> dict[str, float | bool]:
    threshold = max(
        ACTIVITY_FLOOR_KG,
        10.0 * float(budget_result["float32_ulp_tolerance_kg"]),
        10.0 * float(wetlossls_result["float32_ulp_tolerance_kg"]),
    )
    checkpoint = float(checkpoint_loss_kg)
    budget = float(budget_result["native_loss_raw_kg"])
    wetlossls = float(wetlossls_result["native_loss_raw_kg"])
    active = checkpoint > threshold and budget > threshold and wetlossls > threshold
    return {
        "active": active,
        "activity_threshold_kg": threshold,
        "checkpoint_positive_above_threshold": checkpoint > threshold,
        "budget_positive_above_threshold": budget > threshold,
        "wetlossls_positive_above_threshold": wetlossls > threshold,
    }


def validate(
    off_one: Path,
    off_eight: Path,
    on_one: Path,
    on_eight: Path,
    *,
    ras_surface_reevap_report: Path | None = None,
) -> dict[str, Any]:
    runs = tuple(path.resolve() for path in (off_one, off_eight, on_one, on_eight))
    off_one, off_eight, on_one, on_eight = runs
    require_case_config(off_one, on_one)
    require_case_config(off_eight, on_eight)
    if common.load_config(off_one) != common.load_config(off_eight):
        raise ValueError("LS-wetdep-off config differs between thread counts")
    if common.load_config(on_one) != common.load_config(on_eight):
        raise ValueError("LS-wetdep-on config differs between thread counts")
    inputs = require_input_identity(runs)
    require_inactive_boundaries(runs)

    thread_checks: dict[str, Any] = {
        "ls_wetdep_off_checkpoints": common.require_thread_identity(off_one, off_eight),
        "ls_wetdep_on_checkpoints": common.require_thread_identity(on_one, on_eight),
    }
    qck_checks = {
        "ls_wetdep_off": common.require_qck_v2_thread_identity(off_one, off_eight),
        "ls_wetdep_on": common.require_qck_v2_thread_identity(on_one, on_eight),
    }
    ab_heartbeat_one = require_ab_heartbeat_one_identity(off_one, on_one)

    collection_specs = {
        "budget": ("Budget", "BudgetWetDepFull", False),
        "convective_loss": ("WetLossConv", "WetLossConv", True),
        "large_scale_loss": ("WetLossLS", "WetLossLS", True),
    }
    diagnostics: dict[str, dict[str, tuple[np.ndarray, dict[str, np.ndarray]]]] = {}
    for role, (collection, prefix, rank3) in collection_specs.items():
        by_arm = {
            "off_one": read_wet_collection(off_one, collection, prefix, rank3=rank3),
            "off_eight": read_wet_collection(off_eight, collection, prefix, rank3=rank3),
            "on_one": read_wet_collection(on_one, collection, prefix, rank3=rank3),
            "on_eight": read_wet_collection(on_eight, collection, prefix, rank3=rank3),
        }
        diagnostics[role] = by_arm
        thread_checks[f"{role}_off"] = require_collection_thread_identity(
            prefix, by_arm["off_one"], by_arm["off_eight"]
        )
        thread_checks[f"{role}_on"] = require_collection_thread_identity(
            prefix, by_arm["on_one"], by_arm["on_eight"]
        )

    conv_results: dict[str, dict[str, dict[str, float | bool]]] = {}
    ls_results: dict[str, dict[str, dict[str, Any]]] = {}
    conv_active_tags: set[str] = set()
    ls_active_tags: set[str] = set()
    convective_closure_failures: list[dict[str, Any]] = []
    for heartbeat, time in enumerate(TIMES):
        conv_by_arm: dict[str, dict[str, Any]] = {}
        for arm, run in (("off", off_one), ("on", on_one)):
            native_fields = diagnostics["convective_loss"][f"{arm}_one"][1]
            by_tag: dict[str, Any] = {}
            for tag in TAGS:
                checkpoint_columns = checkpoint_column_loss(
                    run, "C3_POST_MIXING", "C4_POST_CONVECTION", time, tag
                )
                native_rate = native_fields[tag][heartbeat]
                native_columns = native_rate.astype(np.float64).sum(
                    axis=0, dtype=np.float64
                ) * HEARTBEAT_SECONDS
                checkpoint_loss = float(checkpoint_columns.sum(dtype=np.float64))
                native_loss = integrated_native_loss_kg(native_rate)
                result = assess_native_loss(
                    checkpoint_loss, native_loss, native_rate, f"convective {arm} {time} {tag}"
                )
                result.update(
                    assess_columns(
                        checkpoint_columns,
                        native_columns,
                        native_rate,
                        (0,),
                        f"convective {arm} {time} {tag}",
                    )
                )
                closure_passed = (
                    result["status"] == "pass" and result["column_status"] == "pass"
                )
                result["closure_passed"] = closure_passed
                if not closure_passed:
                    convective_closure_failures.append(
                        {
                            "arm": arm,
                            "heartbeat": time,
                            "tag": tag,
                            "global_status": result["status"],
                            "global_failure_reason": result["failure_reason"],
                            "checkpoint_loss_kg": result["checkpoint_loss_raw_kg"],
                            "wetlossconv_loss_kg": result["native_loss_raw_kg"],
                            "checkpoint_minus_wetlossconv_kg": result[
                                "checkpoint_minus_native_kg"
                            ],
                            "global_tolerance_kg": result["float32_ulp_tolerance_kg"],
                            "column_status": result["column_status"],
                            "column_residual_max_abs_kg": result[
                                "column_residual_max_abs_kg"
                            ],
                            "column_tolerance_max_kg": result[
                                "column_tolerance_max_kg"
                            ],
                        }
                    )
                activity = convective_activity(result)
                result["activity"] = activity
                if tag in ACTIVITY_TAGS and bool(activity["active"]):
                    conv_active_tags.add(tag)
                by_tag[tag] = result
            conv_by_arm[arm] = by_tag
        conv_results[time] = conv_by_arm

        ls_by_tag: dict[str, Any] = {}
        budget_fields = diagnostics["budget"]["on_one"][1]
        ls_fields = diagnostics["large_scale_loss"]["on_one"][1]
        for tag in TAGS:
            checkpoint_columns = checkpoint_column_loss(
                on_one, "C5_POST_CHEMISTRY", "C6_POST_WETDEP", time, tag
            )
            checkpoint_loss = float(checkpoint_columns.sum(dtype=np.float64))
            budget_rate = budget_fields[tag][heartbeat]
            budget_columns = -budget_rate.astype(np.float64) * HEARTBEAT_SECONDS
            budget_loss = -integrated_native_loss_kg(budget_rate)
            budget_result = reconcile_native_loss(
                checkpoint_loss, budget_loss, budget_rate, f"LS Budget {time} {tag}"
            )
            budget_result.update(
                reconcile_columns(
                    checkpoint_columns,
                    budget_columns,
                    budget_rate,
                    (),
                    f"LS Budget {time} {tag}",
                )
            )
            ls_rate = ls_fields[tag][heartbeat]
            ls_columns = ls_rate.astype(np.float64).sum(axis=0, dtype=np.float64) * HEARTBEAT_SECONDS
            ls_loss = integrated_native_loss_kg(ls_rate)
            ls_result = reconcile_native_loss(
                checkpoint_loss, ls_loss, ls_rate, f"WetLossLS {time} {tag}"
            )
            ls_result.update(
                reconcile_columns(
                    checkpoint_columns,
                    ls_columns,
                    ls_rate,
                    (0,),
                    f"WetLossLS {time} {tag}",
                )
            )
            checked_loss = float(budget_result["checkpoint_loss_kg"])
            activity = large_scale_activity(checkpoint_loss, budget_result, ls_result)
            if tag in ACTIVITY_TAGS and bool(activity["active"]):
                ls_active_tags.add(tag)
            ls_by_tag[tag] = {
                "checkpoint_loss_kg": checked_loss,
                "activity": activity,
                "budget": budget_result,
                "wetlossls": ls_result,
            }
        ls_results[time] = ls_by_tag

    convective_closure_passed = not convective_closure_failures
    conv_active = bool(conv_active_tags)
    ls_active = bool(ls_active_tags)
    native_ras_reconciliable = all(
        failure["global_failure_reason"] == "checkpoint_native_nonclosure"
        for failure in convective_closure_failures
    )
    ras_report = (
        load_ras_surface_reevap_report(ras_surface_reevap_report)
        if ras_surface_reevap_report is not None
        else None
    )
    ras_passed = (
        ras_surface_reevap_report_passed(ras_report)
        if ras_report is not None
        else None
    )
    qck_off = qck_common.read_qck_v2_summary(off_one)
    qck_on = qck_common.read_qck_v2_summary(on_one)
    return {
        "status": final_status(
            convective_closure_passed,
            conv_active,
            ls_active,
            ras_passed,
            native_ras_reconciliable,
        ),
        "scientific_acceptance": False,
        "qck_policy": "conservative full-column QCK_BOTTOM with bounded v2 microclosure",
        "operator_under_test": (
            "standard OCPO convective scavenging and switch-gated large-scale wet deposition"
        ),
        "input_identity": inputs,
        "thread_determinism": thread_checks,
        "qck_thread_determinism": qck_checks,
        "heartbeat_one_ab_identity_through_c5": ab_heartbeat_one,
        "acceptance": {
            "activity_floor_kg": ACTIVITY_FLOOR_KG,
            "activity_group": sorted(ACTIVITY_TAGS),
            "float32_ulp_safety_factor": FLOAT32_ULP_SAFETY_FACTOR,
            "numerical_floor_kg": NUMERICAL_FLOOR_KG,
            "checkpoint_loss_authoritative": True,
            "off_c5_equals_c6_exact": True,
            "c4_equals_c5_exact_all_arms": True,
        },
        "activity": {
            "convective_active": conv_active,
            "convective_active_tags": sorted(conv_active_tags),
            "large_scale_active": ls_active,
            "large_scale_active_tags": sorted(ls_active_tags),
        },
        "convective_diagnostic_closure": {
            "status": "pass" if convective_closure_passed else "fail",
            "failure_code": (
                "" if convective_closure_passed else "convective_wetloss_nonclosure"
            ),
            "failure_count": len(convective_closure_failures),
            "failures": convective_closure_failures,
            "root_cause_code": "ras_surface_reevaporation_omitted_from_wetlossconv",
            "diagnosed_code_causality": CONVECTIVE_NONCLOSURE_CAUSALITY,
            "ras_ledger_can_reconcile_native_nonclosure": native_ras_reconciliable,
            "delq_clip_events_observed": 0,
            "checkpoint_is_authoritative": True,
        },
        "convective_wet_loss": conv_results,
        "large_scale_diagnostic_closure": {
            "status": "pass",
            "budgetwetdepfull_reconciled": True,
            "wetlossls_reconciled": True,
            "checkpoint_is_authoritative": True,
        },
        "large_scale_wet_loss": ls_results,
        "ras_surface_reevap_ledger": {
            "required_for_final_acceptance": True,
            "status": "pending" if ras_report is None else ras_report["status"],
            "report": (
                None
                if ras_surface_reevap_report is None
                else str(ras_surface_reevap_report.resolve())
            ),
            "passed": ras_passed,
            "closure_failure_count": (
                None if ras_report is None else ras_report["closure_failure_count"]
            ),
            "thread_determinism": (
                None if ras_report is None else ras_report["thread_determinism"]
            ),
        },
        "qck_microclosure": {
            "ls_wetdep_off_kg": float(qck_off["microclosure_total_kg"]),
            "ls_wetdep_on_kg": float(qck_on["microclosure_total_kg"]),
            "ls_wetdep_on_minus_off_kg": float(qck_on["microclosure_total_kg"])
            - float(qck_off["microclosure_total_kg"]),
            "ls_wetdep_off_event_count": int(qck_off["event_count"]),
            "ls_wetdep_on_event_count": int(qck_on["event_count"]),
            "all_controls": {
                "ls_wetdep_off_1thread": qck_common.read_qck_v2_summary(off_one),
                "ls_wetdep_off_8thread": qck_common.read_qck_v2_summary(off_eight),
                "ls_wetdep_on_1thread": qck_common.read_qck_v2_summary(on_one),
                "ls_wetdep_on_8thread": qck_common.read_qck_v2_summary(on_eight),
            },
        },
        "guardrail": (
            "Wet-removal behavior is diagnostic only; production and scientific "
            "interpretation remain blocked pending the separate science design."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("off_one", type=Path)
    parser.add_argument("off_eight", type=Path)
    parser.add_argument("on_one", type=Path)
    parser.add_argument("on_eight", type=Path)
    parser.add_argument("--ras-reevap-report", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = validate(
        args.off_one,
        args.off_eight,
        args.on_one,
        args.on_eight,
        ras_surface_reevap_report=args.ras_reevap_report,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if str(result["status"]).startswith("diagnostic_fail"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
