#!/usr/bin/env python3
"""Read a daily official GFAS file in latitude chunks and report profile QC."""
import argparse
import json

import h5py
import numpy as np


def audit(path):
    result = {"file": str(path), "invalid": 0, "negative": 0,
              "active_columns": 0, "surface_without_profile": 0,
              "max_column_relative_difference": 0.0,
              "co_surface_sum": 0.0, "co_profile_sum": 0.0,
              "co_elevated_sum": 0.0}
    with h5py.File(path, "r") as nc:
        result["shape_3d"] = list(nc["cofire_3d"].shape)
        result["units"] = str(nc["cofire_3d"].attrs["units"])
        for start in range(0, len(nc["lat"]), 25):
            surface = np.asarray(nc["cofire"][0, start:start+25, :], dtype=float)
            profile = np.asarray(nc["cofire_3d"][0, :, start:start+25, :], dtype=float)
            result["invalid"] += int(np.count_nonzero(~np.isfinite(surface)))
            result["invalid"] += int(np.count_nonzero(~np.isfinite(profile)))
            result["negative"] += int(np.count_nonzero(surface < 0))
            result["negative"] += int(np.count_nonzero(profile < 0))
            if not (np.all(np.isfinite(surface)) and np.all(np.isfinite(profile))):
                continue
            column = profile.sum(axis=0)
            active = surface > 0
            result["active_columns"] += int(np.count_nonzero(active))
            result["surface_without_profile"] += int(np.count_nonzero(active & (column <= 0)))
            if np.any(active):
                relative = np.abs(column[active] - surface[active]) / surface[active]
                result["max_column_relative_difference"] = max(
                    result["max_column_relative_difference"], float(relative.max()))
            result["co_surface_sum"] += float(surface.sum())
            result["co_profile_sum"] += float(column.sum())
            result["co_elevated_sum"] += float(profile[1:].sum())
    result["status"] = "PASS" if (not result["invalid"] and not result["negative"]
        and not result["surface_without_profile"] and result["active_columns"] > 0
        and result["co_elevated_sum"] > 0
        and result["max_column_relative_difference"] <= 2e-6) else "FAIL"
    result["note"] = "Unweighted cell-flux sums are QC only, not global emissions mass."
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    report = audit(parser.parse_args().file)
    print(json.dumps(report, indent=2, allow_nan=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
