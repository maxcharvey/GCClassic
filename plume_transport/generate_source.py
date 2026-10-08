#!/usr/bin/env python3
"""Generate normalized 3-D HEMCO plume-tag source rates from a run manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import h5py
import numpy as np
from scipy.io import netcdf_file

from manifest_utils import load_manifest as resolve_manifest


TAGS = ("PLUME_SFC", "PLUME_PBL", "PLUME_6535", "PLUME_LEV", "PLUME_PROFILE")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normal_cdf(values: np.ndarray, center: float, sigma: float) -> np.ndarray:
    scaled = (values - center) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + np.fromiter((math.erf(float(x)) for x in scaled), dtype=np.float64))


def normalized(values: np.ndarray, name: str, tolerance: float) -> np.ndarray:
    if np.any(~np.isfinite(values)) or np.any(values < 0.0):
        raise ValueError(f"{name}: weights must be finite and non-negative")
    total = float(values.sum(dtype=np.float64))
    if total <= 0.0:
        raise ValueError(f"{name}: profile has zero support")
    result = values.astype(np.float64, copy=True) / total
    if abs(float(result.sum(dtype=np.float64)) - 1.0) > tolerance:
        raise ValueError(f"{name}: normalized profile does not sum to one")
    return result


def load_manifest(path: Path) -> dict:
    manifest = resolve_manifest(path)
    tags = tuple(manifest["source"]["tags"])
    if tags != TAGS:
        raise ValueError(f"manifest tags must be {TAGS}, got {tags}")
    return manifest


def build_profiles(manifest: dict) -> tuple[dict[str, np.ndarray], dict]:
    restart = Path(manifest["restart"]["seed"])
    pbl_file = Path(manifest["meteorology"]["pblh_file"])
    j = int(manifest["source"]["cell_index_zero_based"]["j"])
    i = int(manifest["source"]["cell_index_zero_based"]["i"])
    tolerance = float(manifest["source"]["normalization_tolerance"])

    if sha256(restart) != manifest["restart"]["seed_sha256"]:
        raise ValueError("seed restart SHA-256 does not match manifest")
    if sha256(pbl_file) != manifest["meteorology"]["pblh_file_sha256"]:
        raise ValueError("PBLH file SHA-256 does not match manifest")

    with h5py.File(restart, "r") as dataset:
        lat = np.asarray(dataset["lat"][:], dtype=np.float64)
        lon = np.asarray(dataset["lon"][:], dtype=np.float64)
        lev = np.asarray(dataset["lev"][:], dtype=np.float64)
        area = np.asarray(dataset["AREA"][:], dtype=np.float64)
        box_height = np.asarray(dataset["Met_BXHEIGHT"][0, :, j, i], dtype=np.float64)
        delp_dry = np.asarray(dataset["Met_DELPDRY"][0, :, j, i], dtype=np.float64)

    with h5py.File(pbl_file, "r") as dataset:
        pblh = float(dataset["PBLH"][0, j, i])

    expected_cell = manifest["source"]["cell_center"]
    checks = (
        (float(lat[j]), float(expected_cell["latitude_degrees_north"]), "latitude"),
        (float(lon[i]), float(expected_cell["longitude_degrees_east"]), "longitude"),
        (float(area[j, i]), float(manifest["source"]["cell_area_m2"]), "cell area"),
    )
    for actual, expected, label in checks:
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-6):
            raise ValueError(f"manifest {label} mismatch: {actual} != {expected}")

    edges = np.concatenate(([0.0], np.cumsum(box_height, dtype=np.float64)))
    overlap = np.maximum(0.0, np.minimum(edges[1:], pblh) - edges[:-1]) / box_height

    surface = np.zeros_like(box_height)
    surface[0] = 1.0
    pbl = normalized(delp_dry * overlap, "PLUME_PBL", tolerance)

    pbl_top_layer = int(np.flatnonzero(overlap > 0.0)[-1])
    ft_start = pbl_top_layer + 1
    n_ft = int(manifest["source"]["profiles"]["PLUME_6535"]["ft_complete_levels_above_pbl"])
    ft_stop = min(ft_start + n_ft, len(delp_dry))
    if ft_stop - ft_start != n_ft:
        raise ValueError("not enough complete free-tropospheric levels")
    ft = np.zeros_like(box_height)
    ft[ft_start:ft_stop] = delp_dry[ft_start:ft_stop]
    ft = normalized(ft, "PLUME_6535 free-tropospheric component", tolerance)
    mix_spec = manifest["source"]["profiles"]["PLUME_6535"]
    pbl_fraction = float(mix_spec["pbl_fraction"])
    ft_fraction = float(mix_spec["ft_fraction"])
    if not math.isclose(pbl_fraction + ft_fraction, 1.0, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError("PLUME_6535 component fractions do not sum to one")
    mix = normalized(pbl_fraction * pbl + ft_fraction * ft, "PLUME_6535", tolerance)

    level_one_based = int(manifest["source"]["profiles"]["PLUME_LEV"]["level_one_based"])
    level = np.zeros_like(box_height)
    level[level_one_based - 1] = 1.0

    profile_spec = manifest["source"]["profiles"]["PLUME_PROFILE"]
    gaussian = normal_cdf(edges[1:], float(profile_spec["center_m"]), float(profile_spec["sigma_m"]))
    gaussian -= normal_cdf(edges[:-1], float(profile_spec["center_m"]), float(profile_spec["sigma_m"]))
    gaussian = normalized(gaussian, "PLUME_PROFILE", tolerance)

    profiles = {
        "PLUME_SFC": normalized(surface, "PLUME_SFC", tolerance),
        "PLUME_PBL": pbl,
        "PLUME_6535": mix,
        "PLUME_LEV": normalized(level, "PLUME_LEV", tolerance),
        "PLUME_PROFILE": gaussian,
    }
    metadata = {
        "lat": lat,
        "lon": lon,
        "lev": lev,
        "area": area,
        "box_height_m": box_height,
        "delp_dry_hpa": delp_dry,
        "height_edges_m_agl": edges,
        "pblh_m_agl": pblh,
        "pbl_top_layer_one_based": pbl_top_layer + 1,
        "ft_levels_one_based": [ft_start + 1, ft_stop],
        "source_j": j,
        "source_i": i,
    }
    return profiles, metadata


def write_source(path: Path, manifest: dict, profiles: dict[str, np.ndarray], metadata: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    nlev = len(metadata["lev"])
    nlat = len(metadata["lat"])
    nlon = len(metadata["lon"])
    duration = float(manifest["source"]["duration_s"])
    mass = float(manifest["source"]["total_mass_per_tag_kg"])
    area = float(metadata["area"][metadata["source_j"], metadata["source_i"]])
    column_rate = mass / (area * duration)

    with netcdf_file(path, "w", version=2) as dataset:
        dataset.createDimension("time", 1)
        dataset.createDimension("lev", nlev)
        dataset.createDimension("ilev", nlev + 1)
        dataset.createDimension("lat", nlat)
        dataset.createDimension("lon", nlon)

        time = dataset.createVariable("time", "d", ("time",))
        time[:] = [0.0]
        time.units = "minutes since 2019-01-01 00:00:00"
        time.calendar = "gregorian"
        for name, values, units in (
            ("lev", metadata["lev"], "level"),
            ("lat", metadata["lat"], "degrees_north"),
            ("lon", metadata["lon"], "degrees_east"),
        ):
            variable = dataset.createVariable(name, "d", (name,))
            variable[:] = values
            variable.units = units

        height = dataset.createVariable("height_edge_agl", "d", ("ilev",))
        height[:] = metadata["height_edges_m_agl"]
        height.units = "m"
        height.long_name = "geometric layer edges above local ground at source cell"

        for tag in TAGS:
            rate = np.zeros((1, nlev, nlat, nlon), dtype=np.float64)
            weight = np.zeros((nlev, nlat, nlon), dtype=np.float64)
            rate[0, :, metadata["source_j"], metadata["source_i"]] = column_rate * profiles[tag]
            weight[:, metadata["source_j"], metadata["source_i"]] = profiles[tag]

            variable = dataset.createVariable(tag, "d", ("time", "lev", "lat", "lon"))
            variable[:] = rate
            variable.units = "kg m-2 s-1"
            variable.long_name = f"controlled three-dimensional source rate for {tag}"

            variable = dataset.createVariable(f"weight_{tag}", "d", ("lev", "lat", "lon"))
            variable[:] = weight
            variable.units = "1"
            variable.long_name = f"normalized vertical source weights for {tag}"

        dataset.title = "GC plume-transport Stage-1 V0 controlled HEMCO source"
        dataset.case_id = manifest["case_id"]
        dataset.profile_time = str(manifest["meteorology"]["profile_reference_time"])
        dataset.pblh_m_agl = metadata["pblh_m_agl"]
        dataset.source_duration_s = duration
        dataset.source_mass_per_tag_kg = mass

    integrated = {}
    for tag in TAGS:
        integrated[tag] = float((column_rate * profiles[tag]).sum(dtype=np.float64) * area * duration)
    return {
        "case_id": manifest["case_id"],
        "source_file": str(path),
        "source_file_sha256": sha256(path),
        "source_cell_zero_based": {"j": metadata["source_j"], "i": metadata["source_i"]},
        "source_cell_center": {
            "latitude_degrees_north": float(metadata["lat"][metadata["source_j"]]),
            "longitude_degrees_east": float(metadata["lon"][metadata["source_i"]]),
        },
        "source_cell_area_m2": area,
        "column_rate_kg_m2_s": column_rate,
        "duration_s": duration,
        "pblh_m_agl": metadata["pblh_m_agl"],
        "pbl_top_layer_one_based": metadata["pbl_top_layer_one_based"],
        "ft_levels_one_based": metadata["ft_levels_one_based"],
        "profile_sums": {tag: float(profiles[tag].sum(dtype=np.float64)) for tag in TAGS},
        "profile_weights": {tag: profiles[tag].tolist() for tag in TAGS},
        "integrated_mass_kg": integrated,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    if bool(manifest["source"].get("reuse_v0_generated_source", False)):
        raise ValueError(
            "this manifest requires a byte-for-byte copy of the frozen V0 source; "
            "do not regenerate it"
        )
    profiles, metadata = build_profiles(manifest)
    summary = write_source(args.output, manifest, profiles, metadata)
    summary_path = args.summary or args.output.with_name("plume_source_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "source_file", "source_file_sha256", "profile_sums", "integrated_mass_kg"
    )}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
