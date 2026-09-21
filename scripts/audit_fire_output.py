#!/usr/bin/env python3
"""Audit HEMCO fire-emission diagnostics without running GEOS-Chem."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np


REQUIRED = ("EmisCO_Fire", "EmisBCPI_Fire", "EmisBCPO_Fire",
            "EmisOCPI_Fire", "EmisOCPO_Fire", "EmisFSOAP_Fire",
            "EmisNPBRCPOA_Fire", "EmisPBRCPOA_Fire", "EmisDBRCPOA_Fire")


def _datasets(group, prefix=""):
    for name, obj in group.items():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(obj, h5py.Dataset):
            yield path, obj
        elif isinstance(obj, h5py.Group):
            yield from _datasets(obj, path)


def _field(ds):
    """Canonicalize only the documented (time, lev, lat, lon) contract."""
    arr = np.asarray(ds[...], dtype=float)
    if arr.ndim == 4:
        if arr.shape[0] != 1:
            raise ValueError("rank-4 fire fields must have one time record")
        arr = arr[0]
    if arr.ndim != 3:
        raise ValueError("fire fields must be rank-3 (lev,lat,lon) or rank-4 with time=1")
    return arr


def _closure_error(actual, expected):
    scale = np.maximum(np.abs(expected), 1e-25)
    return float(np.max(np.abs(actual - expected) / scale))


def audit(path, inventory="gfas"):
    errors = []
    metrics = {}
    with h5py.File(path, "r") as nc:
        fields = {name.rsplit("/", 1)[-1]: ds for name, ds in _datasets(nc)}
        if inventory != "gfas":
            return {"status": "FAIL", "errors": [f"unsupported inventory: {inventory}"]}
        missing = [name for name in REQUIRED if name not in fields]
        if missing:
            errors.append("missing required HEMCO diagnostics: " + ", ".join(missing))
            return {"file": str(Path(path).resolve()), "status": "FAIL", "errors": errors}
        try:
            data = {name: _field(fields[name]) for name in REQUIRED}
        except ValueError as exc:
            return {"file": str(Path(path).resolve()), "status": "FAIL", "errors": [str(exc)]}
        if len({arr.shape for arr in data.values()}) != 1:
            return {"file": str(Path(path).resolve()), "status": "FAIL", "errors": ["required fire fields have mismatched dimensions"]}
        for name, arr in data.items():
            if not np.all(np.isfinite(arr)):
                errors.append(f"{name} contains NaN/Inf")
            if np.any(arr < 0):
                errors.append(f"{name} contains negative values")
            if arr.ndim >= 3 and not np.any(arr[1:] > 0):
                errors.append(f"{name} has no above-level-1 injection")
        if errors:
            return {"file": str(Path(path).resolve()), "inventory": inventory,
                    "status": "FAIL", "metrics": metrics, "errors": errors}
        co = data["EmisCO_Fire"]
        fsoap = data["EmisFSOAP_Fire"]
        metrics["max_fsoap_co_relative_error"] = _closure_error(fsoap, .013 * co)
        if metrics["max_fsoap_co_relative_error"] > 2e-6:
            errors.append("FSOAP is not 0.013*CO within relative tolerance 2e-6")
        for lhs, rhs, factor, label in (
                ("EmisNPBRCPOA_Fire", "EmisPBRCPOA_Fire", 3., "NPBRC=3*PBRC"),
                ("EmisDBRCPOA_Fire", None, 4., "DBRC=4*(BCPI+BCPO)")):
            target = factor * (data["EmisBCPI_Fire"] + data["EmisBCPO_Fire"]) if rhs is None else factor * data[rhs]
            err = _closure_error(data[lhs], target)
            metrics[label + "_max_relative_error"] = err
            if err > 2e-6:
                errors.append(label + " closure failed")
        err = _closure_error(data["EmisOCPI_Fire"] + data["EmisOCPO_Fire"], 4 * data["EmisPBRCPOA_Fire"])
        metrics["OC_total_4PBRC_max_relative_error"] = err
        if err > 2e-6:
            errors.append("OCPI+OCPO=4*PBRC closure failed")
    return {"file": str(Path(path).resolve()), "inventory": inventory,
            "status": "FAIL" if errors else "PASS", "metrics": metrics,
            "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--inventory", choices=("gfas",), default="gfas")
    args = parser.parse_args()
    report = audit(args.file, args.inventory)
    print(json.dumps(report, indent=2, allow_nan=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
