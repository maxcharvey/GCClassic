#!/usr/bin/env python3
"""Validate the frozen profile weights and generated HEMCO source rates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from generate_source import TAGS, build_profiles, sha256
from manifest_utils import load_manifest


def load_source_manifest(path: Path) -> dict:
    """Load a source contract, resolving its checked parent when present."""

    return load_manifest(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    manifest = load_source_manifest(args.manifest)
    expected_profiles, metadata = build_profiles(manifest)
    tolerance = float(manifest["source"]["normalization_tolerance"])
    mass = float(manifest["source"]["total_mass_per_tag_kg"])
    duration = float(manifest["source"]["duration_s"])
    area = float(manifest["source"]["cell_area_m2"])
    j = int(manifest["source"]["cell_index_zero_based"]["j"])
    i = int(manifest["source"]["cell_index_zero_based"]["i"])

    checks: dict[str, dict] = {}
    with netcdf_file(args.source, "r", mmap=False) as dataset:
        expected_shape = (1, len(metadata["lev"]), len(metadata["lat"]), len(metadata["lon"]))
        for tag in TAGS:
            rate = np.asarray(dataset.variables[tag][:], dtype=np.float64)
            if rate.shape != expected_shape:
                raise ValueError(f"{tag}: shape {rate.shape} != {expected_shape}")
            if np.any(~np.isfinite(rate)) or np.any(rate < 0.0):
                raise ValueError(f"{tag}: source contains invalid or negative values")

            profile = np.asarray(dataset.variables[f"weight_{tag}"][:, j, i], dtype=np.float64)
            profile_error = float(np.max(np.abs(profile - expected_profiles[tag])))
            outside = rate.copy()
            column = outside[0, :, j, i].copy()
            outside[0, :, j, i] = 0.0
            outside_max = float(np.max(np.abs(outside)))
            integrated_mass = float(column.sum(dtype=np.float64) * area * duration)
            relative_mass_error = abs(integrated_mass - mass) / mass
            if profile_error > tolerance:
                raise ValueError(f"{tag}: profile mismatch {profile_error} > {tolerance}")
            if outside_max != 0.0:
                raise ValueError(f"{tag}: nonzero source outside declared horizontal cell")
            if relative_mass_error > float(manifest["acceptance"]["source_flux_to_mass_relative"]):
                raise ValueError(f"{tag}: integrated source mass mismatch")
            checks[tag] = {
                "profile_sum": float(profile.sum(dtype=np.float64)),
                "profile_max_abs_error": profile_error,
                "integrated_mass_kg": integrated_mass,
                "relative_mass_error": relative_mass_error,
                "outside_source_cell_max": outside_max,
            }

    integrated_masses = np.asarray(
        [checks[tag]["integrated_mass_kg"] for tag in TAGS], dtype=np.float64
    )
    equal_source_relative_spread = float(
        (integrated_masses.max() - integrated_masses.min()) / mass
    )
    if equal_source_relative_spread > float(manifest["acceptance"]["equal_source_relative"]):
        raise ValueError("integrated tag sources do not agree within equal-source tolerance")

    report = {
        "status": "pass",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "equal_source_relative_spread": equal_source_relative_spread,
        "checks": checks,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
