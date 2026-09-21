#!/usr/bin/env python3
"""Check the BrC forcing-definition/provenance contract; never infer physics.

Relative artifact paths are resolved against the JSON file's directory.
A PASS verifies the record, not the scientific claims in review documents.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


LABEL_FIELDS = ("metric", "boundary", "sky", "baseline", "species_scope",
                "inventory", "optics_scheme")
REPOSITORIES = ("GCClassic", "geos-chem", "HEMCO", "Cloud-J", "HETP")
REQUIRED_ROLES = {"geoschem_config", "hemco_config", "history", "executable",
                  "online_optics", "photolysis_optics", "restart"}
REVIEW_ROLES = {"review_optics", "review_parameters", "review_inventory",
               "review_operator"}


def nonempty(value):
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().lower() not in {"todo", "tbd", "unknown", "replace_me"})


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_record(record, base_dir, verify_files=True):
    errors = []
    if not isinstance(record, dict):
        return {"status": "FAIL", "errors": ["record must be an object"]}
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        errors.append("schema_version must be 1")
    if not nonempty(record.get("run_id")):
        errors.append("run_id is required")
    purpose = record.get("purpose")
    if purpose not in ("engineering", "science"):
        errors.append("purpose must be engineering or science")
    definition = record.get("definition", {})
    if not isinstance(definition, dict):
        definition = {}
    for name in LABEL_FIELDS:
        if not nonempty(definition.get(name)):
            errors.append(f"definition.{name} is required")

    sources = record.get("sources", {})
    if not isinstance(sources, dict):
        sources = {}
    for name in REPOSITORIES:
        source = sources.get(name, {})
        if not isinstance(source, dict):
            source = {}
        if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit", ""))):
            errors.append(f"sources.{name}.commit must be a full Git SHA")
        if not nonempty(source.get("ref")):
            errors.append(f"sources.{name}.ref is required (branch or release tag)")
        if source.get("dirty") is not False:
            errors.append(f"sources.{name}.dirty must be false; commit the tested source")

    radiation = record.get("radiation", {})
    if not isinstance(radiation, dict):
        radiation = {}
    for name in ("code", "flux_convention", "temporal_sampling"):
        if not nonempty(radiation.get(name)):
            errors.append(f"radiation.{name} is required")
    fields = radiation.get("diagnostic_fields")
    if not isinstance(fields, list) or not fields or not all(map(nonempty, fields)):
        errors.append("radiation.diagnostic_fields must list the actual archived fields")

    # Never manufacture absorption from a product of separately averaged fields.
    absorption = record.get("absorption", {})
    if not isinstance(absorption, dict):
        absorption = {}
    method = absorption.get("method")
    if method not in ("unavailable", "online_aaod", "paired_instantaneous_aod_ssa"):
        errors.append("absorption.method must be unavailable, online_aaod, or paired_instantaneous_aod_ssa")
    if method == "paired_instantaneous_aod_ssa":
        if absorption.get("sampling") != "instantaneous" or absorption.get("same_bins") is not True:
            errors.append("derived AAOD requires instantaneous AOD/SSA in identical bins")
    if method != "unavailable" and not nonempty(absorption.get("evidence")):
        errors.append("absorption.evidence is required for any claimed AAOD")
    if method in ("online_aaod", "paired_instantaneous_aod_ssa"):
        field_keys = ("aaod_fields",) if method == "online_aaod" else ("aod_fields", "ssa_fields")
        for key in field_keys:
            fields = absorption.get(key)
            if not isinstance(fields, list) or not fields or not all(map(nonempty, fields)):
                errors.append(f"absorption.{key} must name the archived diagnostic fields")
        if method == "online_aaod" and absorption.get("sampling") not in ("instantaneous", "mean_of_online_aaod"):
            errors.append("online AAOD must declare instantaneous or mean_of_online_aaod sampling")

    roles = set()
    artifact_paths = {}
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts must be a nonempty list")
        artifacts = []
    for number, artifact in enumerate(artifacts):
        prefix = f"artifacts[{number}]"
        if not isinstance(artifact, dict):
            errors.append(f"{prefix} must be an object")
            continue
        role, path, digest = (artifact.get(key) for key in ("role", "path", "sha256"))
        if not nonempty(role):
            errors.append(f"{prefix}.role is required")
            continue
        else:
            roles.add(role)
        if not nonempty(path):
            errors.append(f"{prefix}.path is required")
            continue
        # Multiple tables per optical role are expected, but a config, restart,
        # binary and optical table cannot all be represented by the same file.
        resolved = str((Path(base_dir) / path).resolve())
        prior_role = artifact_paths.get(resolved)
        if prior_role is not None and prior_role != role and (prior_role in REQUIRED_ROLES or role in REQUIRED_ROLES):
            errors.append(f"{prefix}: one file cannot stand in for both {prior_role} and {role}")
        artifact_paths[resolved] = role
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            errors.append(f"{prefix}.sha256 must be a full SHA-256")
            continue
        if verify_files:
            try:
                actual = sha256(Path(base_dir) / path)
                if actual != digest:
                    errors.append(f"{prefix}: hash mismatch: {path}")
            except OSError as exc:
                errors.append(f"{prefix}: cannot read {path}: {exc}")
    missing = REQUIRED_ROLES - roles
    if missing:
        errors.append("missing artifact roles: " + ", ".join(sorted(missing)))
    if method in ("online_aaod", "paired_instantaneous_aod_ssa") and "absorption_output" not in roles:
        errors.append("claimed AAOD requires a hashed absorption_output artifact")

    qualification = record.get("qualification", {})
    if not isinstance(qualification, dict):
        qualification = {}
    if qualification.get("optics") not in ("placeholder", "qualified"):
        errors.append("qualification.optics must be placeholder or qualified")
    if not nonempty(qualification.get("limitations")):
        errors.append("qualification.limitations is required")
    status = qualification.get("status")
    if status not in ("engineering_only", "reviewed_for_scope"):
        errors.append("qualification.status must be engineering_only or reviewed_for_scope")
    if purpose == "science":
        if status != "reviewed_for_scope":
            errors.append("science use requires an explicit reviewed_for_scope status")
        for key in ("reviewer", "review_date", "scope"):
            if not nonempty(qualification.get(key)):
                errors.append(f"science use requires qualification.{key}")
        if qualification.get("optics") != "qualified":
            errors.append("science use cannot promote placeholder optical tables")
        missing_reviews = REVIEW_ROLES - roles
        if missing_reviews:
            errors.append("science use needs hashed review evidence: " + ", ".join(sorted(missing_reviews)))
    if status == "reviewed_for_scope" and qualification.get("optics") != "qualified":
        errors.append("reviewed_for_scope conflicts with placeholder optics")

    return {"status": "FAIL" if errors else "PASS", "run_id": record.get("run_id"),
            "purpose": purpose, "files_verified": verify_files,
            "label": " / ".join(str(definition.get(key, "")) for key in LABEL_FIELDS),
            "science_approval": "not conferred by this checker", "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--schema-only", action="store_true",
                        help="check structure only, not artifact existence or hashes")
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text())
        report = check_record(record, args.record.resolve().parent, not args.schema_only)
    except (OSError, ValueError) as exc:
        report = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
