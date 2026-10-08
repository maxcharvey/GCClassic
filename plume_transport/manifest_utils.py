"""Resolve small, reviewed case manifests layered on a frozen parent."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize checked manifest data deterministically for provenance hashes."""

    def normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): normalize(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(value) for value in item]
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, Path):
            return str(item)
        return item

    return json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of canonical manifest-compatible JSON data."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def resolved_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Hash the fully resolved manifest, excluding its self-referential field."""

    frozen = deepcopy(manifest)
    artifact_hashes = frozen.get("artifact_hashes")
    if isinstance(artifact_hashes, dict):
        artifact_hashes.pop("resolved_manifest_sha256", None)
    return canonical_sha256(frozen)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a recursive merge without mutating either checked manifest."""

    merged = deepcopy(base)
    replacement_keys = {str(key) for key in override.get("replace_parent_sections", [])}
    for key in {str(key) for key in override.get("drop_parent_sections", [])}:
        merged.pop(key, None)
    for key, value in override.items():
        if key in {
            "parent_manifest",
            "parent_manifest_sha256",
            "replace_parent_sections",
            "drop_parent_sections",
        }:
            continue
        if key in replacement_keys:
            merged[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a manifest, recursively checking and applying its parent if any."""

    path = path.resolve()
    with path.open(encoding="utf-8") as handle:
        child = yaml.safe_load(handle)
    if not isinstance(child, dict):
        raise ValueError(f"{path}: manifest must be a mapping")

    parent_value = child.get("parent_manifest")
    if parent_value is None:
        return child
    parent_path = Path(str(parent_value))
    if not parent_path.is_absolute():
        parent_path = path.parent / parent_path
    parent_path = parent_path.resolve()
    expected_hash = child.get("parent_manifest_sha256")
    if expected_hash is not None and sha256(parent_path) != str(expected_hash):
        raise ValueError(f"{path}: parent manifest hash differs from the review record")
    return deep_merge(load_manifest(parent_path), child)
