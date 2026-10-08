#!/usr/bin/env python3
"""Prepare a stock TransportTracers run for a checked plume test case."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import h5py
import numpy as np
import yaml

from manifest_utils import load_manifest


TAGS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")
PRODUCT_TAGS = (
    "PLUME_SFC_PI",
    "PLUME_PBL_PI",
    "PLUME_6535_PI",
    "PLUME_LEV_PI",
    "PLUME_PROFILE_PI",
)
AGING_TAGS = TAGS + PRODUCT_TAGS
TAG_FULL_NAMES = {
    "PLUME_SFC": "Inert plume tag with surface source placement",
    "PLUME_PBL": "Inert plume tag with fractional PBL source placement",
    "PLUME_6535": "Inert plume tag with 65 percent PBL and 35 percent FT source placement",
    "PLUME_LEV": "Inert plume tag with fixed model-level source placement",
    "PLUME_PROFILE": "Inert plume tag with prescribed distributed source profile",
    "PLUME_SFC_PI": "Aged product of the surface plume tag",
    "PLUME_PBL_PI": "Aged product of the PBL plume tag",
    "PLUME_6535_PI": "Aged product of the 65/35 plume tag",
    "PLUME_LEV_PI": "Aged product of the fixed-level plume tag",
    "PLUME_PROFILE_PI": "Aged product of the distributed-profile plume tag",
}
DRYDEP_PROPERTIES = {
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
DRYDEP_FORBIDDEN_PROPERTIES = (
    "Is_Gas",
    "Is_WetDep",
    "Is_HygroGrowth",
    "DD_AeroDryDep",
    "DD_DustDryDep",
    "Radius",
)
WETDEP_PROPERTIES = {
    **DRYDEP_PROPERTIES,
    "Is_WetDep": True,
    "WD_AerScavEff": 1.0,
    "WD_KcScaleFac": [0.5, 0.5, 0.5],
    "WD_RainoutEff": [0.0, 0.0, 0.0],
}
AGING_PRODUCT_PROPERTIES = {
    key: value
    for key, value in WETDEP_PROPERTIES.items()
    if key not in {"Src_Add", "Src_Mode"}
}
AGING_PRODUCT_PROPERTIES.update({"Src_Add": False, "Src_Mode": "none"})
WETDEP_FORBIDDEN_PROPERTIES = (
    "Is_Gas",
    "Is_HygroGrowth",
    "DD_AeroDryDep",
    "DD_DustDryDep",
    "Radius",
    "Henry_CR",
    "Henry_K0",
    "Henry_PKA",
    "WD_ConvFacI2G",
    "WD_RetFactor",
    "WD_LiqAndGas",
    "WD_CoarseAer",
    "WD_Is_DSTbin",
    "WD_WashoutRainPara",
    "WD_WashoutSnowPara",
    "WD_KcScaleFac_Luo",
    "WD_RainoutEff_Luo",
)
DISABLED_SWITCHES = (
    "EDGARv42_SF6",
    "OCEAN_CH3I",
    "CEDS_01x01",
    "EDGARv43",
    "HTAP",
    "UNIFORM_CO",
)
REQUIRED_SUPPORT_SWITCHES = ("OLSON_LANDMAP", "YUAN_MODIS_LAI")
TPCORE_FILL_NEGATIVE_VALUES_PLACEHOLDER = "__PLUME_TPCORE_FILL_NEGATIVE_VALUES__"
PBL_MIXING_PREPARATION_CONTRACT = "stage1-pbl-mixing-v1"
CONVECTION_PREPARATION_CONTRACT = "stage1-convection-v1"
DRY_DEPOSITION_PREPARATION_CONTRACT = "stage1-dry-deposition-v1"
WET_DEPOSITION_PREPARATION_CONTRACT = "stage1-wet-deposition-v1"
AGING_PREPARATION_CONTRACT = "stage1-aging-v1"
DRYDEP_OPERATOR_PLACEHOLDERS = {
    "__PLUME_PBL_MIXING_ACTIVE__": "pbl_turbulence",
    "__PLUME_CONVECTION_ACTIVE__": "convection",
    "__PLUME_DRY_DEPOSITION_ACTIVE__": "dry_deposition",
    "__PLUME_WET_DEPOSITION_ACTIVE__": "wet_deposition",
}
TPCORE_CONFIG_PLACEHOLDERS = (
    ("__PLUME_START_YYYYMMDD__", "start date"),
    ("__PLUME_START_HHMMSS__", "start time"),
    ("__PLUME_END_YYYYMMDD__", "end date"),
    ("__PLUME_END_HHMMSS__", "end time"),
    ("__PLUME_TRANSPORT_TIMESTEP_S__", "transport timestep"),
    ("__PLUME_CHEMISTRY_TIMESTEP_S__", "chemistry timestep"),
)


def validate_bounded_qck_v2_runtime_contract(manifest: dict, contract: str) -> None:
    """Require the complete survey-free bounded-QCK v2 runtime contract."""

    if (
        manifest.get("acceptance", {}).get("contract_version")
        != "stage1-tpcore-causality-v2"
    ):
        raise ValueError(
            f"{contract} requires "
            "acceptance.contract_version=stage1-tpcore-causality-v2"
        )
    runtime_contract = manifest.get("runtime_contract", {})
    if set(runtime_contract.get("unset_environment", ())) != {
        "GC_QCK_BOTTOM_SURVEY",
        "GC_QCK_BOTTOM_SURVEY_RUN_ID",
        "GC_QCK_BOTTOM_SURVEY_FILE",
    }:
        raise ValueError(
            f"{contract} requires the native survey environment to be explicitly unset"
        )
    if runtime_contract.get("microclosure_environment") != {
        "GC_QCK_BOTTOM_MICROCLOSURE_EVENT_MAX_KG": "5e-8",
        "GC_QCK_BOTTOM_MICROCLOSURE_CALL_MAX_KG": "5e-8",
    }:
        raise ValueError(f"{contract} requires the frozen microclosure environment")
    if runtime_contract.get("cell_diagnostics_environment") != {
        "GC_PLUME_TPCORE_CELL_DIAGNOSTICS": "1",
        "GC_PLUME_TPCORE_CELL_DIAG_FILE": "./OutputDir/plume_tpcore_cell_events_v3.csv",
    }:
        raise ValueError(f"{contract} requires the cell diagnostics runtime environment")
    if runtime_contract.get("donor_diagnostics_environment") != {
        "GC_PLUME_TPCORE_DONOR_DIAGNOSTICS": "1",
        "GC_PLUME_TPCORE_DONOR_DIAG_FILE": "./OutputDir/plume_tpcore_donor_events_v3.csv",
    }:
        raise ValueError(f"{contract} requires the donor diagnostics runtime environment")


def validate_ras_surface_reevap_runtime_contract(manifest: dict, contract: str) -> None:
    """Require a provenance-complete RAS surface re-evaporation ledger."""

    runtime = manifest.get("ras_surface_reevap_runtime")
    if not isinstance(runtime, dict) or runtime.get("enabled") is not True:
        raise ValueError(f"{contract} requires ras_surface_reevap_runtime.enabled=true")
    if runtime.get("schema_version") != "ras-surface-reevap-ledger-v1":
        raise ValueError(f"{contract} requires the RAS surface re-evaporation schema")
    manifest_id = runtime.get("manifest_id")
    if (
        not isinstance(manifest_id, str)
        or not manifest_id.strip()
        or "replace-" in manifest_id.lower()
    ):
        raise ValueError(f"{contract} requires a concrete RAS ledger manifest_id")
    environment = runtime.get("environment")
    if not isinstance(environment, dict):
        raise ValueError(f"{contract} requires the RAS ledger runtime environment")
    expected = {
        "GC_RAS_SURFACE_REEVAP_LEDGER": "1",
        "GC_RAS_SURFACE_REEVAP_LEDGER_FILE": "./OutputDir/ras_surface_reevap.csv",
    }
    if contract == AGING_PREPARATION_CONTRACT:
        expected["GC_RAS_SURFACE_REEVAP_INCLUDE_AGED"] = "1"
    if set(environment) != {
        *expected,
        "GC_RAS_SURFACE_REEVAP_LEDGER_RUN_ID",
        "GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID",
    }:
        raise ValueError(f"{contract} has an incomplete RAS ledger environment")
    for name, value in expected.items():
        if environment.get(name) != value:
            raise ValueError(f"{contract} has an invalid RAS ledger {name}")
    run_id = environment["GC_RAS_SURFACE_REEVAP_LEDGER_RUN_ID"]
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or "replace-" in run_id.lower()
    ):
        raise ValueError(f"{contract} requires a concrete RAS ledger run ID")
    if environment["GC_RAS_SURFACE_REEVAP_LEDGER_MANIFEST_ID"] != manifest_id:
        raise ValueError(f"{contract} RAS ledger manifest ID differs from its contract")


def validate_aging_runtime_contract(manifest: dict, contract: str) -> None:
    """Require the complete, provenance-safe fixed-lifetime aging contract."""

    runtime = manifest.get("aging_runtime")
    if not isinstance(runtime, dict) or runtime.get("enabled") is not True:
        raise ValueError(f"{contract} requires aging_runtime.enabled=true")
    if runtime.get("schema_version") != "plume-aging-ledger-v1":
        raise ValueError(f"{contract} requires the plume aging ledger schema")
    if runtime.get("lifetime_s") != 99360:
        raise ValueError(f"{contract} requires the frozen 99360 s reference lifetime")
    manifest_id = runtime.get("manifest_id")
    if (
        not isinstance(manifest_id, str)
        or not manifest_id.strip()
        or "replace-" in manifest_id.lower()
    ):
        raise ValueError(f"{contract} requires a concrete aging ledger manifest_id")
    if runtime.get("clear_environment") != ["GC_PLUME_AGING"]:
        raise ValueError(f"{contract} must clear the inherited aging gate")

    environment = runtime.get("environment")
    if not isinstance(environment, dict):
        raise ValueError(f"{contract} requires the aging runtime environment")
    expected = {
        "GC_PLUME_AGING_LIFETIME_S",
        "GC_PLUME_AGING_FILE",
        "GC_PLUME_AGING_RUN_ID",
        "GC_PLUME_AGING_MANIFEST_ID",
    }
    requested = manifest.get("run", {}).get("operators", {}).get("aging")
    if not isinstance(requested, bool):
        raise ValueError(f"{contract} requires a boolean run.operators.aging switch")
    allowed = set(expected)
    if requested:
        allowed.add("GC_PLUME_AGING")
    if set(environment) != allowed:
        raise ValueError(f"{contract} has an incomplete or conflicting aging environment")
    if environment.get("GC_PLUME_AGING_LIFETIME_S") != "99360" or \
       environment.get("GC_PLUME_AGING_FILE") != "./OutputDir/plume_aging_v1.csv":
        raise ValueError(f"{contract} has an invalid aging lifetime or ledger path")
    if requested and environment.get("GC_PLUME_AGING") != "1":
        raise ValueError(f"{contract} aging-on requires GC_PLUME_AGING=1")
    if environment.get("GC_PLUME_AGING_MANIFEST_ID") != manifest_id:
        raise ValueError(f"{contract} aging ledger manifest ID differs from its contract")
    run_id = environment.get("GC_PLUME_AGING_RUN_ID")
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or "replace-" in run_id.lower()
    ):
        raise ValueError(f"{contract} requires a concrete aging ledger run ID")

    checkpoint_environment = manifest.get("checkpoint_runtime", {}).get("environment")
    if not isinstance(checkpoint_environment, dict) or \
       checkpoint_environment.get("GC_PLUME_CHECKPOINT_AGED_POOLS") != "1":
        raise ValueError(f"{contract} requires ten-pool aging checkpoints")


def validate_operator_contract(manifest: dict, config: dict) -> bool:
    """Fail closed unless the runtime YAML exactly matches the case switches."""

    requested = manifest["run"]["operators"]
    operations = config["operations"]
    actual = {
        "chemistry": bool(operations["chemistry"]["activate"]),
        "transport": bool(operations["transport"]["gcclassic_tpcore"]["activate"]),
        "pbl_turbulence": bool(operations["pbl_mixing"]["activate"]),
        "convection": bool(operations["convection"]["activate"]),
        "dry_deposition": bool(operations["dry_deposition"]["activate"]),
        "wet_deposition": bool(operations["wet_deposition"]["activate"]),
    }
    for name, value in actual.items():
        if value != bool(requested[name]):
            raise ValueError(
                f"configured operator {name}={value} differs from manifest "
                f"value {bool(requested[name])}"
            )
    tpcore = operations["transport"]["gcclassic_tpcore"]
    if bool(requested["native_tpcore"]) != bool(tpcore["activate"]):
        raise ValueError("native_tpcore manifest switch differs from runtime YAML")
    if bool(requested["transport_fill_negative_values"]) != bool(
        tpcore["fill_negative_values"]
    ):
        raise ValueError("TPCORE negative-value filling differs from manifest")
    if tuple(tpcore["iord_jord_kord"]) != tuple(
        requested["transport_orders_i_j_k"]
    ):
        raise ValueError("TPCORE numerical orders differ from manifest")
    contract = manifest.get("preparation_contract")
    expected_tags = AGING_TAGS if contract == AGING_PREPARATION_CONTRACT else TAGS
    if tuple(operations["transport"]["transported_species"]) != expected_tags:
        raise ValueError("runtime transported-species list differs from frozen plume tags")
    timesteps = config["timesteps"]
    if int(timesteps["transport_timestep_in_s"]) != int(
        manifest["run"]["transport_timestep_s"]
    ):
        raise ValueError("transport timestep differs from manifest")
    if int(timesteps["chemistry_timestep_in_s"]) != int(
        manifest["run"]["chemistry_timestep_s"]
    ):
        raise ValueError("chemistry timestep differs from manifest")
    if not bool(requested["native_do_tend"]):
        raise ValueError("the controlled source cases require native_do_tend=true")
    if contract == PBL_MIXING_PREPARATION_CONTRACT:
        validate_bounded_qck_v2_runtime_contract(manifest, contract)
        required = {
            "chemistry": True,
            "transport": True,
            "convection": False,
            "dry_deposition": False,
            "wet_deposition": False,
        }
        for name, expected in required.items():
            if bool(requested[name]) is not expected:
                raise ValueError(
                    f"{PBL_MIXING_PREPARATION_CONTRACT} requires "
                    f"{name}={str(expected).lower()}"
                )
        if bool(operations["pbl_mixing"]["use_non_local_pbl"]):
            raise ValueError(
                f"{PBL_MIXING_PREPARATION_CONTRACT} requires full PBL mixing "
                "(use_non_local_pbl=false)"
            )
    elif contract == CONVECTION_PREPARATION_CONTRACT:
        validate_bounded_qck_v2_runtime_contract(manifest, contract)
        required = {
            "chemistry": True,
            "transport": True,
            "pbl_turbulence": True,
            "dry_deposition": False,
            "wet_deposition": False,
        }
        for name, expected in required.items():
            if bool(requested[name]) is not expected:
                raise ValueError(
                    f"{CONVECTION_PREPARATION_CONTRACT} requires "
                    f"{name}={str(expected).lower()}"
                )
        if bool(operations["pbl_mixing"]["use_non_local_pbl"]):
            raise ValueError(
                f"{CONVECTION_PREPARATION_CONTRACT} requires full PBL mixing "
                "(use_non_local_pbl=false)"
            )
    elif contract == DRY_DEPOSITION_PREPARATION_CONTRACT:
        validate_bounded_qck_v2_runtime_contract(manifest, contract)
        required = {
            "chemistry": True,
            "transport": True,
            "pbl_turbulence": True,
            "convection": True,
            "wet_deposition": False,
        }
        for name, expected in required.items():
            if bool(requested[name]) is not expected:
                raise ValueError(
                    f"{DRY_DEPOSITION_PREPARATION_CONTRACT} requires "
                    f"{name}={str(expected).lower()}"
                )
        if bool(operations["pbl_mixing"]["use_non_local_pbl"]):
            raise ValueError(
                f"{DRY_DEPOSITION_PREPARATION_CONTRACT} requires full PBL mixing "
                "(use_non_local_pbl=false)"
            )
    elif contract in {WET_DEPOSITION_PREPARATION_CONTRACT, AGING_PREPARATION_CONTRACT}:
        validate_bounded_qck_v2_runtime_contract(manifest, contract)
        validate_ras_surface_reevap_runtime_contract(manifest, contract)
        if contract == AGING_PREPARATION_CONTRACT:
            validate_aging_runtime_contract(manifest, contract)
        required = {
            "chemistry": True,
            "transport": True,
            "pbl_turbulence": True,
            "convection": True,
            "dry_deposition": True,
        }
        for name, expected in required.items():
            if bool(requested[name]) is not expected:
                raise ValueError(
                    f"{contract} requires "
                    f"{name}={str(expected).lower()}"
                )
        if bool(operations["pbl_mixing"]["use_non_local_pbl"]):
            raise ValueError(
                f"{contract} requires full PBL mixing "
                "(use_non_local_pbl=false)"
            )
    elif contract is not None:
        raise ValueError(f"unknown preparation_contract: {contract}")
    else:
        unsupported = {
            name for name in (
                "pbl_turbulence",
                "convection",
                "dry_deposition",
                "wet_deposition",
            ) if bool(requested[name])
        }
        if unsupported:
            raise ValueError(
                "prepare_run.py does not yet implement these operator cases: "
                + ", ".join(sorted(unsupported))
            )
    return bool(requested["transport"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"expected one {label}, found {count}")
    return text.replace(old, new, 1)


def replace_first(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise ValueError(f"could not find {label}")
    return text.replace(old, new, 1)


def timestamp_parts(value: object, label: str) -> tuple[str, str]:
    """Render a manifest timestamp as the unquoted GEOS-Chem YAML tokens."""

    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} is not an ISO-8601 timestamp") from error
    return timestamp.strftime("%Y%m%d"), timestamp.strftime("%H%M%S")


def render_tpcore_config(template: Path, manifest: dict) -> str:
    """Render the one reviewed runtime LFILL switch into the TPCORE template."""

    requested = bool(manifest["run"]["operators"]["transport_fill_negative_values"])
    rendered = template.read_text(encoding="utf-8")
    rendered = replace_once(
        rendered,
        TPCORE_FILL_NEGATIVE_VALUES_PLACEHOLDER,
        "true" if requested else "false",
        "TPCORE fill-negative-values placeholder",
    )
    for placeholder, operator in DRYDEP_OPERATOR_PLACEHOLDERS.items():
        count = rendered.count(placeholder)
        if count:
            rendered = replace_once(
                rendered,
                placeholder,
                "true" if bool(manifest["run"]["operators"][operator]) else "false",
                f"{operator} placeholder",
            )
    start_date, start_time = timestamp_parts(manifest["run"]["start"], "run.start")
    end_date, end_time = timestamp_parts(manifest["run"]["end"], "run.end")
    rendered_values = {
        "__PLUME_START_YYYYMMDD__": start_date,
        "__PLUME_START_HHMMSS__": start_time,
        "__PLUME_END_YYYYMMDD__": end_date,
        "__PLUME_END_HHMMSS__": end_time,
        "__PLUME_TRANSPORT_TIMESTEP_S__": str(
            int(manifest["run"]["transport_timestep_s"])
        ),
        "__PLUME_CHEMISTRY_TIMESTEP_S__": str(
            int(manifest["run"]["chemistry_timestep_s"])
        ),
    }
    for placeholder, label in TPCORE_CONFIG_PLACEHOLDERS:
        rendered = replace_once(rendered, placeholder, rendered_values[placeholder], label)
    if TPCORE_FILL_NEGATIVE_VALUES_PLACEHOLDER in rendered:
        raise ValueError("unresolved TPCORE fill-negative-values placeholder remains")
    unresolved = [
        placeholder for placeholder, _ in TPCORE_CONFIG_PLACEHOLDERS if placeholder in rendered
    ]
    if unresolved:
        raise ValueError(f"unresolved TPCORE configuration placeholders: {unresolved}")
    unresolved_operators = [
        placeholder for placeholder in DRYDEP_OPERATOR_PLACEHOLDERS if placeholder in rendered
    ]
    if unresolved_operators:
        raise ValueError(
            f"unresolved operator configuration placeholders: {unresolved_operators}"
        )
    configured = yaml.safe_load(rendered)
    if not isinstance(configured, dict):
        raise ValueError("rendered TPCORE configuration is not a YAML mapping")
    if validate_operator_contract(manifest, configured) is not True:
        raise AssertionError("rendered TPCORE configuration is not transport-active")
    return rendered


def patch_hemco(
    path: Path,
    source_name: str,
    diagnostic_frequency: str,
    data_root: Path,
) -> None:
    text = path.read_text(encoding="utf-8")
    placeholder_values = {
        "${RUNDIR_DATA_ROOT}": str(data_root).rstrip("/"),
        "${RUNDIR_GCAP2_SCENARIO}": "not_used",
        "${RUNDIR_GCAP2_VERTRES}": "not_used",
        "${RUNDIR_MET_AVAIL}": "# 1980-2021",
        "${RUNDIR_MET_FIELD_CONFIG}": "./HEMCO_Config.rc.gmao_metfields",
        "${RUNDIR_OCEAN_MASK}": (
            "1000 OCEAN_MASK  $METDIR/$CNYR/01/$MET.$CNYR0101.CN.$RES.$NC "
            "FROCEAN 2000/1/1/0 C xy 1 1 -180/-90/180/90"
        ),
    }
    for placeholder, value in placeholder_values.items():
        text = replace_once(text, placeholder, value, placeholder)
    if "${RUNDIR_" in text:
        raise ValueError("unresolved run-directory placeholder remains in HEMCO_Config.rc")

    text, count = re.subn(
        r"(?m)^DiagnFreq:\s+.*$",
        f"DiagnFreq:                   {diagnostic_frequency}",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("could not set HEMCO diagnostic frequency")

    for switch in DISABLED_SWITCHES:
        pattern = rf"(?m)^(\s*-->\s+{re.escape(switch)}\s+:\s+)(true|false)(.*)$"
        text, count = re.subn(pattern, r"\g<1>false\g<3>", text, count=1)
        if count != 1:
            raise ValueError(f"could not disable HEMCO switch {switch}")

    # GCClassic initializes land-type fractions and LAI even when deposition
    # and PBL turbulence are disabled.  Retain these stock support fields; they
    # do not introduce tracer emissions or activate a plume transport process.
    for switch in REQUIRED_SUPPORT_SWITCHES:
        pattern = rf"(?m)^(\s*-->\s+{re.escape(switch)}\s+:\s+)(true|false)(.*)$"
        text, count = re.subn(pattern, r"\g<1>true\g<3>", text, count=1)
        if count != 1:
            raise ValueError(f"could not enable required HEMCO support switch {switch}")

    text, count = re.subn(
        r"(?m)^(100\s+GC_Rn-Pb-Be\s+:\s+)(on|off)(.*)$",
        r"\g<1>off\g<3>",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("could not disable GC_Rn-Pb-Be extension")
    text, count = re.subn(
        r"(?m)^(101\s+ZHANG_Rn222\s+:\s+)(on|off)(.*)$",
        r"\g<1>off\g<3>",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("could not disable ZHANG_Rn222 extension")

    marker = "    --> GC_RESTART             :       true"
    text = replace_once(
        text,
        marker,
        marker + "\n    --> PLUME_SYNTHETIC        :       true",
        "GC_RESTART switch",
    )

    lines = [
        "(((PLUME_SYNTHETIC",
        *(
            f"0 {tag}_SOURCE ./{source_name} {tag} 2019/1/1/0 C xyz "
            f"kg/m2/s {tag} - 1 1"
            for tag in TAGS
        ),
        ")))PLUME_SYNTHETIC",
        "",
    ]
    # TransportTracers has additional scale-factor and mask sections that use
    # the same HEMCO section name.  The first occurrence is the base-emissions
    # section, which is where species source fields belong.
    text = replace_first(
        text,
        "(((EMISSIONS\n",
        "(((EMISSIONS\n\n" + "\n".join(lines),
        "EMISSIONS section marker",
    )
    path.write_text(text, encoding="utf-8")


def patch_drydep_species_database(path: Path) -> None:
    """Replace the inert plume species block with the reviewed OCPO analogue."""

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?ms)^PLUME_TAG_PROP:.*?(?=^Pb210_PROP:)"
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected one inert PLUME_TAG_PROP block, found {len(matches)}")

    lines = [
        "PLUME_DRYDEP_PROP: &PLUMEDRYDEPproperties",
        "  Background_VV: 1.0e-20",
        "  DD_DvzAerSnow: 0.03",
        "  DD_F0: 0.0",
        "  DD_Hstar: 0.0",
        "  Density: 1300.0",
        "  Is_Aerosol: true",
        "  Is_DryDep: true",
        "  Is_Tracer: true",
        "  MW_g: 12.01",
        "  Snk_Mode: none",
        "  Src_Add: true",
        "  Src_Mode: HEMCO",
    ]
    for tag in TAGS:
        lines.extend(
            [
                f"{tag}:",
                "  << : *PLUMEDRYDEPproperties",
                f"  FullName: {TAG_FULL_NAMES[tag]}",
            ]
        )
    replacement = "\n".join(lines) + "\n"
    path.write_text(pattern.sub(replacement, text, count=1), encoding="utf-8")
    validate_drydep_species_database(path)


def validate_drydep_species_database(path: Path) -> None:
    """Fail closed on any drift from the reviewed shared deposition properties."""

    database = yaml.safe_load(path.read_text(encoding="utf-8"))
    anchor = database.get("PLUME_DRYDEP_PROP")
    if anchor != DRYDEP_PROPERTIES:
        raise ValueError("PLUME_DRYDEP_PROP differs from the reviewed property contract")
    for tag in TAGS:
        species = database.get(tag)
        if not isinstance(species, dict):
            raise ValueError(f"species database is missing {tag}")
        expected = {**DRYDEP_PROPERTIES, "FullName": TAG_FULL_NAMES[tag]}
        if species != expected:
            raise ValueError(f"{tag} differs from the reviewed dry-deposition properties")
        forbidden = set(DRYDEP_FORBIDDEN_PROPERTIES).intersection(species)
        if forbidden:
            raise ValueError(f"{tag} contains forbidden properties: {sorted(forbidden)}")


def patch_wetdep_species_database(path: Path) -> None:
    """Install the active standard-OCPO wet-scavenging subset on plume tags."""

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?ms)^PLUME_TAG_PROP:.*?(?=^Pb210_PROP:)")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected one inert PLUME_TAG_PROP block, found {len(matches)}")

    lines = [
        "PLUME_WETDEP_PROP: &PLUMEWETDEPproperties",
        "  Background_VV: 1.0e-20",
        "  DD_DvzAerSnow: 0.03",
        "  DD_F0: 0.0",
        "  DD_Hstar: 0.0",
        "  Density: 1300.0",
        "  Is_Aerosol: true",
        "  Is_DryDep: true",
        "  Is_Tracer: true",
        "  Is_WetDep: true",
        "  MW_g: 12.01",
        "  Snk_Mode: none",
        "  Src_Add: true",
        "  Src_Mode: HEMCO",
        "  WD_AerScavEff: 1.0",
        "  WD_KcScaleFac: [0.5, 0.5, 0.5]",
        "  WD_RainoutEff: [0.0, 0.0, 0.0]",
    ]
    for tag in TAGS:
        lines.extend(
            [
                f"{tag}:",
                "  << : *PLUMEWETDEPproperties",
                f"  FullName: {TAG_FULL_NAMES[tag]}",
            ]
        )
    replacement = "\n".join(lines) + "\n"
    path.write_text(pattern.sub(replacement, text, count=1), encoding="utf-8")
    validate_wetdep_species_database(path)


def validate_wetdep_species_database(path: Path) -> None:
    """Fail closed on drift from the reviewed hydrophobic-OC wetdep contract."""

    database = yaml.safe_load(path.read_text(encoding="utf-8"))
    anchor = database.get("PLUME_WETDEP_PROP")
    if anchor != WETDEP_PROPERTIES:
        raise ValueError("PLUME_WETDEP_PROP differs from the reviewed property contract")
    for tag in TAGS:
        species = database.get(tag)
        if not isinstance(species, dict):
            raise ValueError(f"species database is missing {tag}")
        expected = {**WETDEP_PROPERTIES, "FullName": TAG_FULL_NAMES[tag]}
        if species != expected:
            raise ValueError(f"{tag} differs from the reviewed wet-deposition properties")
        forbidden = set(WETDEP_FORBIDDEN_PROPERTIES).intersection(species)
        if forbidden:
            raise ValueError(f"{tag} contains forbidden properties: {sorted(forbidden)}")


def patch_aging_species_database(path: Path) -> None:
    """Install matched wet/dry properties on five parent/product pairs."""

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?ms)^PLUME_TAG_PROP:.*?(?=^Pb210_PROP:)")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected one inert PLUME_TAG_PROP block, found {len(matches)}")
    physical_lines = [
        "  Background_VV: 1.0e-20",
        "  DD_DvzAerSnow: 0.03",
        "  DD_F0: 0.0",
        "  DD_Hstar: 0.0",
        "  Density: 1300.0",
        "  Is_Aerosol: true",
        "  Is_DryDep: true",
        "  Is_Tracer: true",
        "  Is_WetDep: true",
        "  MW_g: 12.01",
        "  Snk_Mode: none",
        "  WD_AerScavEff: 1.0",
        "  WD_KcScaleFac: [0.5, 0.5, 0.5]",
        "  WD_RainoutEff: [0.0, 0.0, 0.0]",
    ]
    lines = [
        "PLUME_AGING_PARENT_PROP: &PLUMEAGINGparentproperties",
        *physical_lines,
        "  Src_Add: true",
        "  Src_Mode: HEMCO",
        "PLUME_AGING_PRODUCT_PROP: &PLUMEAGINGproductproperties",
        *physical_lines,
        "  Src_Add: false",
        "  Src_Mode: none",
    ]
    for tag in TAGS:
        lines.extend([f"{tag}:", "  << : *PLUMEAGINGparentproperties",
                      f"  FullName: {TAG_FULL_NAMES[tag]}"])
    for tag in PRODUCT_TAGS:
        lines.extend([f"{tag}:", "  << : *PLUMEAGINGproductproperties",
                      f"  FullName: {TAG_FULL_NAMES[tag]}"])
    path.write_text(pattern.sub("\n".join(lines) + "\n", text, count=1),
                    encoding="utf-8")
    validate_aging_species_database(path)


def validate_aging_species_database(path: Path) -> None:
    database = yaml.safe_load(path.read_text(encoding="utf-8"))
    if database.get("PLUME_AGING_PARENT_PROP") != WETDEP_PROPERTIES:
        raise ValueError("aging parent properties differ from the reviewed contract")
    if database.get("PLUME_AGING_PRODUCT_PROP") != AGING_PRODUCT_PROPERTIES:
        raise ValueError("aging product properties differ from the reviewed contract")
    for tag in TAGS:
        expected = {**WETDEP_PROPERTIES, "FullName": TAG_FULL_NAMES[tag]}
        if database.get(tag) != expected:
            raise ValueError(f"{tag} differs from the aging parent contract")
    for tag in PRODUCT_TAGS:
        expected = {**AGING_PRODUCT_PROPERTIES, "FullName": TAG_FULL_NAMES[tag]}
        if database.get(tag) != expected:
            raise ValueError(f"{tag} differs from the aging product contract")


def make_restart(seed: Path, output: Path, tags: tuple[str, ...] = TAGS) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    expression = ";".join(
        f"SpeciesRst_{tag}=0.0f*SpeciesRst_PassiveTracer" for tag in tags
    )
    subprocess.run(
        ["ncap2", "-h", "-O", "-s", expression, str(seed), str(temporary)],
        check=True,
    )
    attributes = []
    for tag in tags:
        variable = f"SpeciesRst_{tag}"
        attributes.extend(
            [
                "-a", f"long_name,{variable},o,c,Dry mixing ratio of species {tag}",
                "-a", f"units,{variable},o,c,mol mol-1 dry",
                "-a", f"averaging_method,{variable},o,c,instantaneous",
            ]
        )
    subprocess.run(["ncatted", "-h", "-O", *attributes, str(temporary)], check=True)
    temporary.replace(output)


def validate_initial_restart(path: Path, tags: tuple[str, ...] = TAGS) -> None:
    with h5py.File(path, "r") as dataset:
        reference_shape = dataset["SpeciesRst_PassiveTracer"].shape
        for tag in tags:
            name = f"SpeciesRst_{tag}"
            if name not in dataset:
                raise ValueError(f"generated restart is missing {name}")
            values = np.asarray(dataset[name][:], dtype=np.float64)
            if values.shape != reference_shape:
                raise ValueError(f"{name} has shape {values.shape}, expected {reference_shape}")
            if np.any(~np.isfinite(values)) or np.any(values != 0.0):
                raise ValueError(f"{name} is not explicitly and exactly zero")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--code-directory", type=Path, default=Path("src/GEOS-Chem"))
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    if tuple(manifest["source"]["tags"]) != TAGS:
        raise ValueError(f"manifest tags must be {TAGS}")

    run_directory = args.run_directory.resolve()
    expected = Path(manifest["paths"]["run_directory"]).resolve()
    if run_directory != expected:
        raise ValueError(f"run directory does not match manifest: {run_directory} != {expected}")
    if not (run_directory / "HEMCO_Config.rc").is_file():
        raise FileNotFoundError("stock HEMCO_Config.rc is missing from run directory")

    source = Path(manifest["paths"]["generated_source"]).resolve()
    if not source.is_file() or source.parent != run_directory:
        raise FileNotFoundError("generated source file is absent from the declared run directory")

    templates = Path(__file__).resolve().parent / "templates"
    transport_active = bool(manifest["run"]["operators"]["transport"])
    preparation_contract = manifest.get("preparation_contract")
    active_tags = AGING_TAGS if preparation_contract == AGING_PREPARATION_CONTRACT else TAGS
    if preparation_contract == PBL_MIXING_PREPARATION_CONTRACT:
        config_template = "geoschem_config.pbl.yml"
        history_template = "HISTORY.tpcore.rc"
    elif preparation_contract == CONVECTION_PREPARATION_CONTRACT:
        config_template = "geoschem_config.convection.yml"
        history_template = "HISTORY.tpcore.rc"
    elif preparation_contract == DRY_DEPOSITION_PREPARATION_CONTRACT:
        config_template = "geoschem_config.drydep.yml"
        history_template = "HISTORY.drydep.rc"
    elif preparation_contract == WET_DEPOSITION_PREPARATION_CONTRACT:
        config_template = "geoschem_config.wetdep.yml"
        history_template = "HISTORY.wetdep.rc"
    elif preparation_contract == AGING_PREPARATION_CONTRACT:
        config_template = "geoschem_config.aging.yml"
        history_template = "HISTORY.aging.rc"
    else:
        config_template = (
            "geoschem_config.tpcore.yml" if transport_active else "geoschem_config.yml"
        )
        history_template = "HISTORY.tpcore.rc" if transport_active else "HISTORY.rc"
    config_path = run_directory / "geoschem_config.yml"
    if transport_active:
        config_path.write_text(
            render_tpcore_config(templates / config_template, manifest),
            encoding="utf-8",
        )
    else:
        shutil.copyfile(templates / config_template, config_path)
    shutil.copyfile(templates / history_template, run_directory / "HISTORY.rc")
    shutil.copyfile(templates / "HEMCO_Diagn.rc", run_directory / "HEMCO_Diagn.rc")
    with config_path.open(encoding="utf-8") as handle:
        configured = yaml.safe_load(handle)
    if validate_operator_contract(manifest, configured) != transport_active:
        raise AssertionError("operator contract validation returned inconsistent transport state")
    shutil.copyfile(
        args.code_directory.resolve()
        / "run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.TransportTracers",
        run_directory / "HEMCO_Config.rc",
    )
    shutil.copyfile(
        args.code_directory.resolve() / "run/shared/species_database.yml",
        run_directory / "species_database.yml",
    )
    if preparation_contract == DRY_DEPOSITION_PREPARATION_CONTRACT:
        patch_drydep_species_database(run_directory / "species_database.yml")
    elif preparation_contract == WET_DEPOSITION_PREPARATION_CONTRACT:
        patch_wetdep_species_database(run_directory / "species_database.yml")
    elif preparation_contract == AGING_PREPARATION_CONTRACT:
        patch_aging_species_database(run_directory / "species_database.yml")
    patch_hemco(
        run_directory / "HEMCO_Config.rc",
        source.name,
        str(manifest["outputs"]["history_frequency"]),
        Path("/cluster/work/climate/GEOS-Chem/ExtData/"),
    )

    seed = Path(manifest["restart"]["seed"])
    if sha256(seed) != manifest["restart"]["seed_sha256"]:
        raise ValueError("seed restart SHA-256 does not match manifest")
    restart = Path(manifest["paths"]["generated_restart"])
    make_restart(seed, restart, active_tags)
    validate_initial_restart(restart, active_tags)

    (run_directory / "OutputDir").mkdir(exist_ok=True)
    (run_directory / "OutputDir" / "PlumeCheckpoints").mkdir(exist_ok=True)
    print(f"Prepared {run_directory}")
    print(f"Source SHA-256: {sha256(source)}")
    print(f"Restart SHA-256: {sha256(restart)}")


if __name__ == "__main__":
    main()
