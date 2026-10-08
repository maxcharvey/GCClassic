#!/usr/bin/env python3
"""Build frozen FIREX-AQ Tier-F exclusion and support inventories."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any, Iterable, Mapping, Sequence

from firex_tier_f_phase2_join import load_icartt_source


OUTPUTS = (
    "row_membership.csv",
    "exclusion_cascade.csv",
    "cluster_inventory.csv",
    "uncertainty_completeness.csv",
    "support_inventory.csv",
    "evaluation_support_summary.json",
    "run_manifest.json",
)
SPECIAL_FIRES = {"10.1", "10.2"}
AGE_BINS = (
    ("[0,0.5)", Decimal("0"), Decimal("0.5")),
    ("[0.5,1)", Decimal("0.5"), Decimal("1")),
    ("[1,2)", Decimal("1"), Decimal("2")),
    ("[2,4)", Decimal("2"), Decimal("4")),
    ("[4,8)", Decimal("4"), Decimal("8")),
    ("[8,infinity)", Decimal("8"), None),
)
CASCADE = (
    ("source_preserved", "condition_source_preserved"),
    ("exact_regime_metadata", "condition_exact_regime_metadata"),
    ("smoke_flag_equals_1", "condition_smoke_flag"),
    ("finite_navigation", "condition_finite_navigation"),
    ("valid_mechanical_match", "condition_valid_mechanical_match"),
    ("valid_abs_405", "condition_valid_abs_405"),
    ("valid_abs_532", "condition_valid_abs_532"),
    ("valid_abs_664", "condition_valid_abs_664"),
    ("exclude_special_fire_10.1_10.2", "condition_primary_fire"),
)
COHORTS = (
    "C_abs_all",
    "C_abs_primary",
    "C_aae_all",
    "C_aae_primary",
    "C_age_nominal_all",
    "C_age_nominal_primary",
    "C_age_uncertainty_all",
    "C_age_uncertainty_primary",
    "C_context_all",
    "C_context_primary",
)
ENDPOINTS = ("abs_405", "abs_532", "abs_664")


class SupportInventoryError(RuntimeError):
    """Raised when a frozen input or inventory invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise SupportInventoryError(f"{label} is absent: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise SupportInventoryError(
            f"{label} SHA-256 changed: expected {expected}, got {actual}"
        )


def read_csv(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SupportInventoryError(f"CSV has no header: {path}")
        return tuple(reader.fieldnames), list(reader)


def decimal_or_none(token: str) -> Decimal | None:
    try:
        value = Decimal(token.strip())
    except (InvalidOperation, AttributeError):
        return None
    return value if value.is_finite() else None


def numeric_state(token: str, missing_token: str) -> str:
    value = decimal_or_none(token)
    if value is None:
        return "invalid"
    missing = decimal_or_none(missing_token)
    if missing is not None and value == missing:
        return "missing"
    if value == Decimal("-8888"):
        return "LLOD"
    if value == Decimal("-7777"):
        return "ULOD"
    return "valid"


def finite_float(token: str) -> bool:
    try:
        return math.isfinite(float(token))
    except (TypeError, ValueError):
        return False


def decimal_equal(left: str, right: str) -> bool:
    a = decimal_or_none(left)
    b = decimal_or_none(right)
    return a is not None and b is not None and a == b


def textual_bool(value: str, label: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise SupportInventoryError(f"{label} is not a textual Boolean: {value!r}")


def age_bin(value: Decimal) -> tuple[str, Decimal, Decimal | None] | None:
    for item in AGE_BINS:
        _, lower, upper = item
        if value >= lower and (upper is None or value < upper):
            return item
    return None


def age_stability(age: Decimal, uncertainty: Decimal) -> tuple[str, str]:
    selected = age_bin(age)
    if selected is None:
        return "", "not_available"
    label, lower, upper = selected
    envelope_lower = age - uncertainty
    envelope_upper = age + uncertainty
    stable = envelope_lower >= lower and (
        upper is None or envelope_upper < upper
    )
    return label, "stable" if stable else "crossing"


def model_state(row: Mapping[str, str]) -> str:
    return "|".join(
        (
            row["model_history_file"],
            row["model_history_local_record_index"],
            row["model_level_index"],
            row["model_latitude_index"],
            row["model_longitude_index"],
        )
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise SupportInventoryError(f"refusing empty CSV output: {path.name}")
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _cohort(row: Mapping[str, Any], name: str) -> bool:
    return bool(row[name])


def _collapsed_states(counts: Counter[str]) -> str:
    present = sorted(state for state, count in counts.items() if count > 0)
    if not present:
        return "no_linked_source"
    return present[0] if len(present) == 1 else "mixed:" + "+".join(present)


def _eligibility(
    *,
    rows: int,
    states: int,
    clusters: int,
    nonzero_variation: bool,
) -> dict[str, str]:
    insufficient = "inconclusive_insufficient_independent_support"
    return {
        "counts_raw_points": "eligible",
        "point_summary": (
            "eligible" if rows >= 10 and states >= 5 else insufficient
        ),
        "mean_bias_MAE_RMSE": (
            "eligible" if rows >= 20 and states >= 5 else insufficient
        ),
        "Pearson_Spearman": (
            "eligible"
            if rows >= 30
            and states >= 10
            and clusters >= 5
            and nonzero_variation
            else insufficient
        ),
        "cluster_interval_95": (
            "eligible" if clusters >= 10 else insufficient
        ),
    }


def build_inventories(
    contract: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    inputs = contract["inputs"]
    frozen = contract["frozen_hashes"]
    phase2 = Path(inputs["phase2_root"])
    mechanical = Path(inputs["mechanical_root"])
    paths = {
        "carrier": phase2 / "carrier_join.csv",
        "links": phase2 / "carrier_source_links.csv",
        "phase2_seal": phase2 / "PHASE2_JOIN_SEAL.json",
        "mechanical_rows": mechanical / "OutputDir/tier_f_mechanical_matches.csv",
        "mechanical_summary": mechanical / "OutputDir/tier_f_mechanical_match_summary.json",
        "mechanical_validation": mechanical / "OutputDir/tier_f_mechanical_match_validation.json",
        "mechanical_seal": mechanical / "MECHANICAL_MATCH_SEAL.json",
        "ams_payload": Path(inputs["ams_payload"]),
        "semantic_audit": Path(inputs["semantic_audit"]),
    }
    frozen_keys = {
        "carrier": "phase2_carrier",
        "links": "phase2_links",
        "phase2_seal": "phase2_seal",
        "mechanical_rows": "mechanical_rows",
        "mechanical_summary": "mechanical_summary",
        "mechanical_validation": "mechanical_validation",
        "mechanical_seal": "mechanical_seal",
        "ams_payload": "ams_payload",
        "semantic_audit": "semantic_audit",
    }
    for label, path in paths.items():
        verify_hash(path, frozen[frozen_keys[label]], label)

    semantic = json.loads(paths["semantic_audit"].read_text(encoding="utf-8"))
    crosswalk = semantic.get("FSU_to_Holmes", {}).get("status") == "PASS"
    if not crosswalk:
        raise SupportInventoryError("frozen Holmes crosswalk is not PASS")
    validation = json.loads(paths["mechanical_validation"].read_text(encoding="utf-8"))
    if validation.get("result") != "pass":
        raise SupportInventoryError("mechanical validation is not pass")

    _, carrier_rows = read_csv(paths["carrier"])
    _, match_rows = read_csv(paths["mechanical_rows"])
    expected_rows = int(contract["expected"]["rows"])
    if len(carrier_rows) != expected_rows or len(match_rows) != expected_rows:
        raise SupportInventoryError("carrier/mechanical row count differs from contract")

    v1_root = paths["ams_payload"].parents[1]
    product_specs = {
        "AOP": (
            v1_root / "raw/firexaq-AOP-optical_DC8_20190806_R2.ict",
            frozen["aop_payload"],
            False,
        ),
        "FSU": (
            v1_root / "raw/firexaq-FSU-smokeage_dc8_20190806_R1.ict",
            frozen["fsu_payload"],
            False,
        ),
        "SP2": (
            v1_root / "raw/FIREXAQ-SP2-BC-1HZ_DC8_20190806_R4.ict",
            frozen["sp2_payload"],
            False,
        ),
        "AMS": (paths["ams_payload"], frozen["ams_payload"], True),
    }
    sources = {
        product: load_icartt_source(
            product, path, expected_sha256=digest, explicit_stop=explicit
        )
        for product, (path, digest, explicit) in product_specs.items()
    }
    missing = {
        product: {key.casefold(): value for key, value in source.missing_values.items()}
        for product, source in sources.items()
    }
    ams_by_id = {record.source_id: record for record in sources["AMS"].records}

    membership_rows: list[dict[str, Any]] = []
    for index, (carrier, match) in enumerate(
        zip(carrier_rows, match_rows, strict=True)
    ):
        if int(carrier["carrier_ordinal"]) != index:
            raise SupportInventoryError("carrier ordinal order changed")
        for field in ("carrier_source_record_id", "carrier_raw_record_sha256"):
            if carrier[field] != match[field]:
                raise SupportInventoryError(f"carrier/mechanical {field} mismatch")

        regime_fields = (
            "r9__source_record_id",
            "r12__source_record_id",
            "r9__fire_id",
            "r12__fire_id",
            "r9__transect_number",
            "r12__transect_number",
            "r9__transect_plume_number",
            "r12__plume_id",
        )
        exact_regime = all(carrier[field].strip() for field in regime_fields)
        exact_regime = exact_regime and all(
            (
                decimal_equal(carrier["r9__fire_id"], carrier["r12__fire_id"]),
                decimal_equal(
                    carrier["r9__transect_number"],
                    carrier["r12__transect_number"],
                ),
                decimal_equal(
                    carrier["r9__transect_plume_number"],
                    carrier["r12__plume_id"],
                ),
            )
        )
        smoke = decimal_or_none(carrier["r9__smoke_flag"]) == Decimal(1)
        navigation = all(
            finite_float(carrier[field])
            for field in ("Latitude", "Longitude", "MSL_GPS_Altitude")
        )
        valid_match = textual_bool(match["match_valid"], f"match row {index}")
        aop_states = {
            wavelength: numeric_state(
                carrier[f"aop__abs_dry_{wavelength}"],
                missing["AOP"][f"abs_dry_{wavelength}".casefold()],
            )
            for wavelength in (405, 532, 664)
        }
        special = exact_regime and carrier["r12__fire_id"] in SPECIAL_FIRES

        conditions = {
            "condition_source_preserved": True,
            "condition_exact_regime_metadata": exact_regime,
            "condition_smoke_flag": smoke,
            "condition_finite_navigation": navigation,
            "condition_valid_mechanical_match": valid_match,
            "condition_valid_abs_405": aop_states[405] == "valid",
            "condition_valid_abs_532": aop_states[532] == "valid",
            "condition_valid_abs_664": aop_states[664] == "valid",
            "condition_primary_fire": not special,
        }
        running = True
        first_failed = ""
        for label, key in CASCADE:
            running = running and conditions[key]
            if not running and not first_failed:
                first_failed = label
        c_abs_all = all(
            conditions[key] for _, key in CASCADE[:-1]
        )
        c_abs_primary = c_abs_all and conditions["condition_primary_fire"]
        obs_positive = all(
            decimal_or_none(carrier[f"aop__abs_dry_{w}"]) > 0
            for w in (405, 664)
        ) if c_abs_all else False
        model_positive = all(
            float(match[f"model_abs_{w}_tot_aop_reference_mm1"]) > 0
            for w in (405, 664)
        ) if c_abs_all else False

        age_state = numeric_state(
            carrier["fsu__smoke_age"], missing["FSU"]["smoke_age"]
        )
        age_unc_state = numeric_state(
            carrier["fsu__smoke_age_unc"], missing["FSU"]["smoke_age_unc"]
        )
        method_state = numeric_state(
            carrier["fsu__smoke_agemethod"], missing["FSU"]["smoke_agemethod"]
        )
        method = decimal_or_none(carrier["fsu__smoke_agemethod"])
        method_valid = (
            method_state == "valid"
            and method is not None
            and method == method.to_integral_value()
            and 1 <= int(method) <= 7
        )
        age_seconds = decimal_or_none(carrier["fsu__smoke_age"])
        age_unc_seconds = decimal_or_none(carrier["fsu__smoke_age_unc"])
        age_valid = (
            age_state == "valid"
            and age_seconds is not None
            and age_seconds >= 0
        )
        age_unc_valid = (
            age_unc_state == "valid"
            and age_unc_seconds is not None
            and age_unc_seconds >= 0
        )
        age = age_seconds / Decimal(3600) if age_valid else None
        age_unc = (
            age_unc_seconds / Decimal(3600) if age_unc_valid else None
        )
        bin_label = ""
        stability = "not_available"
        if age_valid:
            selected = age_bin(age)
            bin_label = selected[0] if selected else ""
        if age_valid and age_unc_valid:
            bin_label, stability = age_stability(age, age_unc)
        c_age_nominal_all = c_abs_all and age_valid and method_valid and exact_regime
        c_age_unc_all = (
            c_age_nominal_all and age_unc_valid and crosswalk and bool(bin_label)
        )

        sp2_mass_state = numeric_state(
            carrier["sp2__BC_mass_90_550_nm"],
            missing["SP2"]["bc_mass_90_550_nm"],
        )
        sp2_flag_state = numeric_state(
            carrier["sp2__BC_Dilution_Flag"],
            missing["SP2"]["bc_dilution_flag"],
        )
        sp2_flag = decimal_or_none(carrier["sp2__BC_Dilution_Flag"])
        sp2_valid = (
            sp2_mass_state == "valid"
            and sp2_flag_state == "valid"
            and sp2_flag in (Decimal(0), Decimal(1))
        )
        sp2_state = (
            "undiluted" if sp2_valid and sp2_flag == 0
            else "diluted" if sp2_valid and sp2_flag == 1
            else sp2_mass_state
        )
        sp2_uncertainty = (
            "0.20" if sp2_state == "undiluted"
            else "0.40" if sp2_state == "diluted"
            else ""
        )

        ams_ids = tuple(
            value for value in carrier["ams__source_record_ids"].split(";") if value
        )
        ams_records = []
        for source_id in ams_ids:
            if source_id not in ams_by_id:
                raise SupportInventoryError(f"unknown linked AMS source ID {source_id}")
            ams_records.append(ams_by_id[source_id])
        ams_fields = (
            "OA_PM1_AMS",
            "OA_prec_PM1_AMS",
            "OA_DL_PM1_AMS",
            "CloudFlag_AMS",
            "SDDataFlag_AMS",
        )
        ams_counts: dict[str, Counter[str]] = {}
        for field in ams_fields:
            ams_counts[field] = Counter(
                numeric_state(
                    record.values[field], missing["AMS"][field.casefold()]
                )
                for record in ams_records
            )
            if not ams_records:
                ams_counts[field]["no_linked_source"] += 1
        context_explicit = all(sum(counts.values()) > 0 for counts in ams_counts.values())
        context_explicit = context_explicit and bool(sp2_state)

        cluster_id = (
            f"2019-08-06|{carrier['r12__fire_id']}|{carrier['r12__plume_id']}"
            if exact_regime else ""
        )
        transect_id = carrier["r12__transect_number"] if exact_regime else ""
        output: dict[str, Any] = {
            "carrier_source_record_id": carrier["carrier_source_record_id"],
            "carrier_ordinal": index,
            "observation_time_utc": match["observation_time_utc"],
            "mechanical_match_valid": valid_match,
            "mechanical_rejection_reason": match["match_rejection_reason"],
            "r9_fire_id_raw": carrier["r9__fire_id"],
            "r12_fire_id": carrier["r12__fire_id"],
            "r12_plume_id": carrier["r12__plume_id"],
            "r12_transect_id": transect_id,
            "cluster_id": cluster_id,
            "model_state_id": model_state(match) if valid_match else "",
            **conditions,
            "special_fire_sensitivity": special,
            "cascade_first_failed": first_failed,
            "aop_405_state": aop_states[405],
            "aop_532_state": aop_states[532],
            "aop_664_state": aop_states[664],
            "age_state": age_state,
            "age_uncertainty_state": age_unc_state,
            "age_method_state": "valid" if method_valid else method_state,
            "smoke_age_seconds": (
                str(age_seconds) if age_valid else ""
            ),
            "smoke_age_uncertainty_seconds": (
                str(age_unc_seconds) if age_unc_valid else ""
            ),
            "smoke_age_hours": str(age) if age is not None else "",
            "smoke_age_uncertainty_hours": (
                str(age_unc) if age_unc is not None else ""
            ),
            "age_bin": bin_label,
            "age_boundary_state": stability,
            "sp2_state": sp2_state,
            "sp2_record_uncertainty_fraction": sp2_uncertainty,
            "sp2_uncertainty_metadata_state": (
                "available" if sp2_uncertainty else "explicit_unavailable"
            ),
            "ams_source_record_count": len(ams_records),
            "ams_oa_state": _collapsed_states(ams_counts["OA_PM1_AMS"]),
            "ams_oa_precision_state": _collapsed_states(ams_counts["OA_prec_PM1_AMS"]),
            "ams_oa_detection_limit_state": _collapsed_states(ams_counts["OA_DL_PM1_AMS"]),
            "ams_cloud_flag_state": _collapsed_states(ams_counts["CloudFlag_AMS"]),
            "ams_sd_flag_state": _collapsed_states(ams_counts["SDDataFlag_AMS"]),
            "ams_oa_states": json.dumps(dict(sorted(ams_counts["OA_PM1_AMS"].items())), sort_keys=True),
            "ams_oa_precision_states": json.dumps(dict(sorted(ams_counts["OA_prec_PM1_AMS"].items())), sort_keys=True),
            "ams_oa_detection_limit_states": json.dumps(dict(sorted(ams_counts["OA_DL_PM1_AMS"].items())), sort_keys=True),
            "ams_cloud_flag_states": json.dumps(dict(sorted(ams_counts["CloudFlag_AMS"].items())), sort_keys=True),
            "ams_sd_flag_states": json.dumps(dict(sorted(ams_counts["SDDataFlag_AMS"].items())), sort_keys=True),
            "C_abs_all": c_abs_all,
            "C_abs_primary": c_abs_primary,
            "C_aae_all": c_abs_all and obs_positive and model_positive,
            "C_aae_primary": c_abs_primary and obs_positive and model_positive,
            "C_age_nominal_all": c_age_nominal_all,
            "C_age_nominal_primary": c_age_nominal_all and not special,
            "C_age_uncertainty_all": c_age_unc_all,
            "C_age_uncertainty_primary": c_age_unc_all and not special,
            "C_context_all": c_abs_all and context_explicit,
            "C_context_primary": c_abs_primary and context_explicit,
            "_obs_405": carrier["aop__abs_dry_405"],
            "_obs_532": carrier["aop__abs_dry_532"],
            "_obs_664": carrier["aop__abs_dry_664"],
            "_model_405": match["model_abs_405_tot_aop_reference_mm1"] if valid_match else "",
            "_model_532": match["model_abs_532_tot_aop_reference_mm1"] if valid_match else "",
            "_model_664": match["model_abs_664_tot_aop_reference_mm1"] if valid_match else "",
            "_aop_source_id": carrier["aop__source_record_id"],
        }
        membership_rows.append(output)

    cascade_rows: list[dict[str, Any]] = []
    running = [True] * len(membership_rows)
    previous = len(running)
    for order, (stage, key) in enumerate(CASCADE):
        running = [keep and bool(row[key]) for keep, row in zip(running, membership_rows)]
        retained = sum(running)
        cascade_rows.append(
            {
                "stage_order": order,
                "stage": stage,
                "input_rows": previous,
                "excluded_at_stage": previous - retained,
                "retained_rows": retained,
            }
        )
        previous = retained

    cluster_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in membership_rows:
        if row["cluster_id"]:
            cluster_map[row["cluster_id"]].append(row)
    cluster_rows = []
    for cluster_id in sorted(cluster_map):
        values = cluster_map[cluster_id]
        example = values[0]
        item: dict[str, Any] = {
            "cluster_id": cluster_id,
            "flight_date": "2019-08-06",
            "fire_id": example["r12_fire_id"],
            "plume_id": example["r12_plume_id"],
            "transect_count": len({row["r12_transect_id"] for row in values}),
            "carrier_rows": len(values),
        }
        for cohort in COHORTS:
            item[f"{cohort}_rows"] = sum(bool(row[cohort]) for row in values)
        cluster_rows.append(item)

    completeness_rows: list[dict[str, Any]] = []
    completeness_fields = (
        "aop_405_state",
        "aop_532_state",
        "aop_664_state",
        "age_state",
        "age_uncertainty_state",
        "age_method_state",
        "age_boundary_state",
        "sp2_state",
        "sp2_uncertainty_metadata_state",
        "ams_oa_state",
        "ams_oa_precision_state",
        "ams_oa_detection_limit_state",
        "ams_cloud_flag_state",
        "ams_sd_flag_state",
    )
    scopes = ("all_carrier", *COHORTS)
    for scope in scopes:
        selected = (
            membership_rows
            if scope == "all_carrier"
            else [row for row in membership_rows if row[scope]]
        )
        for field in completeness_fields:
            counts = Counter(str(row[field]) for row in selected)
            for state, count in sorted(counts.items()):
                completeness_rows.append(
                    {
                        "scope": scope,
                        "field": field,
                        "state": state,
                        "rows": count,
                        "scope_rows": len(selected),
                    }
                )
        completeness_rows.append(
            {
                "scope": scope,
                "field": "AOP_low_signal_per_record_precision",
                "state": "not_available_by_design",
                "rows": len(selected),
                "scope_rows": len(selected),
            }
        )
        completeness_rows.append(
            {
                "scope": scope,
                "field": "AMS_organics_accuracy_fraction_at_2sdev",
                "state": "available:0.38",
                "rows": len(selected),
                "scope_rows": len(selected),
            }
        )

    support_rows: list[dict[str, Any]] = []
    for cohort in COHORTS:
        selected = [row for row in membership_rows if row[cohort]]
        bins: Iterable[tuple[str, list[dict[str, Any]]]] = (("all", selected),)
        if "age_" in cohort:
            bins = (
                ("all", selected),
                *(
                    (label, [row for row in selected if row["age_bin"] == label])
                    for label, _, _ in AGE_BINS
                ),
            )
        for bin_label, bin_rows in bins:
            for endpoint in ENDPOINTS:
                wavelength = endpoint.rsplit("_", 1)[1]
                obs = [
                    Decimal(row[f"_obs_{wavelength}"])
                    for row in bin_rows
                ]
                model = [
                    Decimal(row[f"_model_{wavelength}"])
                    for row in bin_rows
                ]
                states = len({row["model_state_id"] for row in bin_rows})
                clusters = len({row["cluster_id"] for row in bin_rows})
                variation = (
                    len(set(obs)) > 1 and len(set(model)) > 1
                    if bin_rows else False
                )
                eligibility = _eligibility(
                    rows=len(bin_rows),
                    states=states,
                    clusters=clusters,
                    nonzero_variation=variation,
                )
                stable_count = sum(
                    row["age_boundary_state"] == "stable" for row in bin_rows
                )
                stability_fraction = (
                    stable_count / len(bin_rows) if bin_rows else None
                )
                support_rows.append(
                    {
                        "cohort": cohort,
                        "age_bin": bin_label,
                        "endpoint": endpoint,
                        "rows": len(bin_rows),
                        "observation_source_records": len(
                            {row["_aop_source_id"] for row in bin_rows}
                        ),
                        "model_states": states,
                        "fires": len({row["r12_fire_id"] for row in bin_rows}),
                        "plumes": len({row["r12_plume_id"] for row in bin_rows}),
                        "transects": len({row["r12_transect_id"] for row in bin_rows}),
                        "clusters": clusters,
                        "nonzero_observation_and_model_variation": variation,
                        **eligibility,
                        "age_stable_rows": stable_count,
                        "age_stable_fraction": (
                            "" if stability_fraction is None else stability_fraction
                        ),
                        "age_stability_status": (
                            "eligible"
                            if stability_fraction is not None
                            and stability_fraction >= 0.8
                            else "inconclusive_age_boundary_uncertainty"
                        ),
                    }
                )

    public_membership = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in membership_rows
    ]
    cohort_counts = {
        cohort: sum(bool(row[cohort]) for row in membership_rows)
        for cohort in COHORTS
    }
    age_pattern: dict[str, dict[str, Any]] = {}
    for cohort in ("C_age_nominal_all", "C_age_nominal_primary",
                   "C_age_uncertainty_all", "C_age_uncertainty_primary"):
        rows_for_cohort = [
            row for row in support_rows
            if row["cohort"] == cohort
            and row["endpoint"] == "abs_405"
            and row["age_bin"] != "all"
        ]
        passing = sum(row["point_summary"] == "eligible" for row in rows_for_cohort)
        age_pattern[cohort] = {
            "bins_passing_point_summary": passing,
            "status": (
                "eligible"
                if passing >= 3
                else "inconclusive_insufficient_independent_support"
            ),
        }

    summary = {
        "schema_version": "firex-tier-f-evaluation-support-v1",
        "result": "completed",
        "scope": "membership and support inventories only; no paired statistics",
        "rows": {
            "carrier": len(membership_rows),
            "post_midnight": sum(
                str(row["observation_time_utc"]).startswith("2019-08-07")
                for row in membership_rows
            ),
            "mechanical_accepted": sum(
                row["mechanical_match_valid"] for row in membership_rows
            ),
            "mechanical_rejected": sum(
                not row["mechanical_match_valid"] for row in membership_rows
            ),
        },
        "cascade": cascade_rows,
        "cohort_counts": cohort_counts,
        "clusters": {
            "exact_lexical_top_level_clusters": len(cluster_rows),
            "identifier_contract": "flight-date|R12 exact fire ID|R12 exact plume ID",
        },
        "Holmes_crosswalk": "PASS",
        "age_pattern_support": age_pattern,
        "prohibitions_verified": {
            "statistics_computed": False,
            "bootstrap_executed": False,
            "rematching": False,
            "model_execution": False,
            "scientific_interpretation": False,
        },
    }
    return (
        public_membership,
        cascade_rows,
        cluster_rows,
        completeness_rows,
        support_rows,
        summary,
    )


def validate_outputs(
    membership: Sequence[Mapping[str, Any]],
    cascade: Sequence[Mapping[str, Any]],
    clusters: Sequence[Mapping[str, Any]],
    support: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    expected_rows: int,
) -> None:
    if len(membership) != expected_rows:
        raise SupportInventoryError("membership row count differs")
    if [int(row["carrier_ordinal"]) for row in membership] != list(range(expected_rows)):
        raise SupportInventoryError("membership order differs")
    if len({str(row["carrier_source_record_id"]) for row in membership}) != expected_rows:
        raise SupportInventoryError("membership source IDs are not unique")
    if len(cascade) != len(CASCADE):
        raise SupportInventoryError("cascade stage count differs")
    if int(cascade[-1]["retained_rows"]) != sum(
        bool(row["C_abs_primary"]) for row in membership
    ):
        raise SupportInventoryError("cascade and primary C_abs count disagree")
    cluster_ids = {str(row["cluster_id"]) for row in clusters}
    if "" in cluster_ids or len(cluster_ids) != len(clusters):
        raise SupportInventoryError("cluster inventory IDs are malformed")
    if not support:
        raise SupportInventoryError("support inventory is empty")
    if summary.get("prohibitions_verified", {}).get("statistics_computed") is not False:
        raise SupportInventoryError("scope prohibition is absent")


def execute(contract_path: Path, output_root: Path) -> None:
    if output_root.exists():
        raise SupportInventoryError(f"no-clobber output root already exists: {output_root}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    frozen = contract["frozen_hashes"]
    (
        membership,
        cascade,
        clusters,
        completeness,
        support,
        summary,
    ) = build_inventories(contract)
    validate_outputs(
        membership,
        cascade,
        clusters,
        support,
        summary,
        int(contract["expected"]["rows"]),
    )
    if summary["rows"]["post_midnight"] != int(
        contract["expected"]["post_midnight_rows"]
    ):
        raise SupportInventoryError("post-midnight row count differs from contract")
    output_root.mkdir(parents=True)
    _write_csv(output_root / "row_membership.csv", membership)
    _write_csv(output_root / "exclusion_cascade.csv", cascade)
    _write_csv(output_root / "cluster_inventory.csv", clusters)
    _write_csv(output_root / "uncertainty_completeness.csv", completeness)
    _write_csv(output_root / "support_inventory.csv", support)
    _write_json(output_root / "evaluation_support_summary.json", summary)
    manifest = {
        "schema_version": 1,
        "command": " ".join(sys.argv),
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "contract": {
            "path": str(contract_path.resolve()),
            "sha256": sha256_file(contract_path),
        },
        "inputs": {
            "phase2_carrier": {
                "path": str((Path(contract["inputs"]["phase2_root"]) / "carrier_join.csv").resolve()),
                "sha256": frozen["phase2_carrier"],
            },
            "phase2_links": {
                "path": str((Path(contract["inputs"]["phase2_root"]) / "carrier_source_links.csv").resolve()),
                "sha256": frozen["phase2_links"],
            },
            "mechanical_rows": {
                "path": str((Path(contract["inputs"]["mechanical_root"]) / "OutputDir/tier_f_mechanical_matches.csv").resolve()),
                "sha256": frozen["mechanical_rows"],
            },
            "aop_payload": {
                "path": str((Path(contract["inputs"]["ams_payload"]).parents[1] / "raw/firexaq-AOP-optical_DC8_20190806_R2.ict").resolve()),
                "sha256": frozen["aop_payload"],
            },
            "fsu_payload": {
                "path": str((Path(contract["inputs"]["ams_payload"]).parents[1] / "raw/firexaq-FSU-smokeage_dc8_20190806_R1.ict").resolve()),
                "sha256": frozen["fsu_payload"],
            },
            "sp2_payload": {
                "path": str((Path(contract["inputs"]["ams_payload"]).parents[1] / "raw/FIREXAQ-SP2-BC-1HZ_DC8_20190806_R4.ict").resolve()),
                "sha256": frozen["sp2_payload"],
            },
            "ams_payload": {
                "path": str(Path(contract["inputs"]["ams_payload"]).resolve()),
                "sha256": frozen["ams_payload"],
            },
            "semantic_audit": {
                "path": str(Path(contract["inputs"]["semantic_audit"]).resolve()),
                "sha256": frozen["semantic_audit"],
            },
        },
        "outputs": list(OUTPUTS[:-1]),
        "random_seed": {"applicable": False, "reason": "inventory gate uses no RNG"},
        "later_gates_opened": False,
    }
    _write_json(output_root / "run_manifest.json", manifest)
    hashes = {
        name: sha256_file(output_root / name)
        for name in OUTPUTS
    }
    _write_json(
        output_root / "ARTIFACT_MANIFEST.json",
        {"schema_version": 1, "artifacts": hashes},
    )
    _write_json(
        output_root / "EVALUATION_SUPPORT_SEAL.json",
        {
            "schema_version": 1,
            "status": "SEALED-PENDING-INDEPENDENT-REPRODUCTION",
            "artifact_manifest_sha256": sha256_file(
                output_root / "ARTIFACT_MANIFEST.json"
            ),
            "contract_sha256": sha256_file(contract_path),
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    execute(args.contract, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
