#!/usr/bin/env python3
"""Mechanical checks on short BrC integration runs, not science validation.

Requires numpy and h5py. Prints a JSON report; does not modify model output.
Example: python3 scripts/audit_brc_smoke.py RUN --brc on --rrtmg on
"""

import argparse
import json
from pathlib import Path

import h5py
import numpy as np


def values(dataset):
    data = np.asarray(dataset[...], dtype=np.float64)
    # GEOS-Chem may encode unavailable diagnostics with a finite fill value.
    # NaN/Inf are deliberately NOT masked: these must fail the finite gate.
    fill = dataset.attrs.get("_FillValue")
    if fill is not None and np.all(np.isfinite(fill)):
        data = np.ma.masked_equal(data, np.asarray(fill).item())
    return data


def datasets(nc, prefix=""):
    """Yield (path, dataset) for root and grouped NetCDF/HDF5 fields."""
    for name, obj in nc.items():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(obj, h5py.Dataset):
            yield path, obj
        elif isinstance(obj, h5py.Group):
            yield from datasets(obj, path)


def check_run(run, brc, rrtmg=None):
    errors = []
    checks = {}
    log = run / "GC.log"
    text = log.read_text(errors="replace") if log.exists() else ""
    checks["normal_end"] = "E N D   O F   G E O S" in text
    if not checks["normal_end"]:
        errors.append("GC.log has no normal GEOS-Chem end marker")
    paths = sorted((run / "OutputDir").glob("GEOSChem.*.nc4"))
    files = [p for p in paths if any(x in p.name for x in
             ("Aerosols.", "BrCDiagnostics.", "RRTMG."))]
    checks["diagnostic_files"] = [p.name for p in files]
    if not files:
        errors.append("No requested BrC/aerosol/RRTMG output files")
    matched = set()
    carbon_fields = set()
    maxima = {}
    for path in files:
        with h5py.File(path, "r") as nc:
            fields = {name.rsplit("/", 1)[-1]: ds for name, ds in datasets(nc)}
            for name, dataset in fields.items():
                if not np.issubdtype(dataset.dtype, np.number):
                    continue
                data = values(dataset)
                if np.ma.count(data) == 0:
                    errors.append(f"{path.name}:{name} has no unmasked data")
                    continue
                if not np.all(np.isfinite(data)):
                    errors.append(f"{path.name}:{name} contains NaN/Inf")
                    continue
                if name.startswith(("BrC", "AODHyg", "RadAOD")):
                    maximum = float(np.ma.max(np.ma.abs(data)))
                    maxima[name] = max(maxima.get(name, 0.0), maximum)
                if name.startswith(("BrCDryAOD", "AODHyg", "RadAOD")) and np.ma.min(data) < -1e-15:
                    errors.append(f"{name} contains negative AOD")
                if "SSA" in name.upper() and (np.ma.min(data) < -1e-7 or np.ma.max(data) > 1 + 1e-7):
                    errors.append(f"{name} outside SSA range [0,1]")
                if name.startswith("BrCDryAOD"):
                    suffix = name.removeprefix("BrCDryAOD")
                    partner = f"AODHyg{suffix}_DBRCPOA"
                    # Store both fields in the Aerosols collection to verify
                    # requested-wavelength interpolation, including 527.1 nm.
                    if partner in fields:
                        ref = values(fields[partner])
                        if not np.allclose(data, ref, rtol=2e-6, atol=1e-12):
                            errors.append(f"{name} differs from {partner}")
                        matched.add(suffix)
                if name == "BrCBleachedFrac":
                    if np.ma.min(data) < -1e-7 or np.ma.max(data) > 1 + 1e-7:
                        errors.append("BrCBleachedFrac outside [0,1]")
            if "BrCAbsMass" in fields and "BrCTotMass" in fields:
                carbon_fields.update(("BrCAbsMass", "BrCTotMass"))
                absorbing = values(fields["BrCAbsMass"])
                total = values(fields["BrCTotMass"])
                if np.ma.any(absorbing > total * (1 + 2e-6) + 1e-15):
                    errors.append("Absorbing carbon mass exceeds total carbon mass")
                for name in ("BrCAbsMass", "BrCTotMass"):
                    if np.ma.min(values(fields[name])) < -1e-15:
                        errors.append(f"{name} contains negative carbon mass")
                    unit = fields[name].attrs.get("units", "")
                    if isinstance(unit, bytes):
                        unit = unit.decode()
                    checks[name + "_units"] = str(unit)
                    if "kgc" not in str(unit).lower().replace(" ", "") and "kgcarbon" not in str(unit).lower().replace(" ", ""):
                        errors.append(f"{name} units are not kgC: {unit}")
    checks["dry_aod_pairs"] = sorted(matched)
    checks["brc_field_maxima"] = maxima
    if brc == "on" and len(matched) < 3:
        errors.append("Fewer than three distinct BrCDryAOD/AODHyg_DBRCPOA wavelength pairs")
    if brc == "on":
        if carbon_fields != {"BrCAbsMass", "BrCTotMass"}:
            errors.append("Enabled output is missing required BrCAbsMass/BrCTotMass carbon fields")
        if not any(v > 0 for n, v in maxima.items() if n.startswith("BrCDryAOD")):
            errors.append("Enabled test did not exercise nonzero dry DBRC AOD")
    else:
        if not any(n.startswith("BrCDryAOD") for n in maxima):
            errors.append("Disabled control did not archive dry BrC diagnostics")
        for name, maximum in maxima.items():
            if name.startswith("BrCDryAOD") and maximum > 1e-15:
                errors.append(f"Disabled BrC has nonzero {name}")
    if rrtmg is not None:
        rrtmg_files = sorted((run / "OutputDir").glob("GEOSChem.RRTMG.*.nc4"))
        checks["rrtmg_files"] = [p.name for p in rrtmg_files]
        if rrtmg == "on" and not rrtmg_files:
            errors.append("--rrtmg on but no RRTMG output file exists")
        if rrtmg == "off" and rrtmg_files:
            errors.append("--rrtmg off but RRTMG output file exists")
        if brc == "off":
            for name, maximum in maxima.items():
                upper = name.upper()
                if "RADAOD" in upper and any(token in upper for token in ("BRC", "BRCT", "DBRC", "WTC")) and maximum > 1e-15:
                    errors.append(f"BrC-off has nonzero {name}")
    return {"run": str(run.resolve()), "brc": brc,
            "status": "FAIL" if errors else "PASS", "checks": checks,
            "errors": errors,
            "scope": "Runtime/finite-value and dry-AOD wiring checks only; not physical qualification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--brc", required=True, choices=("on", "off"))
    parser.add_argument("--rrtmg", choices=("on", "off"), default=None)
    args = parser.parse_args()
    report = check_run(args.run, args.brc, args.rrtmg)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
