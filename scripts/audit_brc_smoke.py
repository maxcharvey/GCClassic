#!/usr/bin/env python3
"""Mechanical checks on short BrC integration runs, not science validation.

Requires numpy and h5py. Prints a JSON report; does not modify model output.
Example: python3 scripts/audit_brc_smoke.py RUN --brc on
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


def check_run(run, brc):
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
    matched = 0
    maxima = {}
    for path in files:
        with h5py.File(path, "r") as nc:
            for name, dataset in nc.items():
                if not isinstance(dataset, h5py.Dataset):
                    continue
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
                if name.startswith("BrCDryAOD"):
                    suffix = name.removeprefix("BrCDryAOD")
                    partner = f"AODHyg{suffix}_DBRCPOA"
                    # Store both fields in the Aerosols collection to verify
                    # requested-wavelength interpolation, including 527.1 nm.
                    if partner in nc:
                        ref = values(nc[partner])
                        if not np.allclose(data, ref, rtol=2e-6, atol=1e-12):
                            errors.append(f"{name} differs from {partner}")
                        matched += 1
                if name == "BrCBleachedFrac":
                    if np.ma.min(data) < -1e-7 or np.ma.max(data) > 1 + 1e-7:
                        errors.append("BrCBleachedFrac outside [0,1]")
            if "BrCAbsMass" in nc and "BrCTotMass" in nc:
                absorbing = values(nc["BrCAbsMass"])
                total = values(nc["BrCTotMass"])
                if np.ma.any(absorbing > total * (1 + 2e-6) + 1e-15):
                    errors.append("Absorbing carbon mass exceeds total carbon mass")
                for name in ("BrCAbsMass", "BrCTotMass"):
                    unit = nc[name].attrs.get("units", "")
                    if isinstance(unit, bytes):
                        unit = unit.decode()
                    checks[name + "_units"] = str(unit)
    checks["dry_aod_pairs"] = matched
    checks["brc_field_maxima"] = maxima
    if not matched and brc == "on":
        errors.append("No collocated BrCDryAOD / AODHyg_DBRCPOA pairs")
    if brc == "on":
        if not any(v > 0 for n, v in maxima.items() if n.startswith("BrCDryAOD")):
            errors.append("Enabled test did not exercise nonzero dry DBRC AOD")
    else:
        if not any(n.startswith("BrCDryAOD") for n in maxima):
            errors.append("Disabled control did not archive dry BrC diagnostics")
        for name, maximum in maxima.items():
            if name.startswith("BrCDryAOD") and maximum > 1e-15:
                errors.append(f"Disabled BrC has nonzero {name}")
    return {"run": str(run.resolve()), "brc": brc,
            "status": "FAIL" if errors else "PASS", "checks": checks,
            "errors": errors,
            "scope": "Runtime/finite-value and dry-AOD wiring checks only; not physical qualification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--brc", required=True, choices=("on", "off"))
    args = parser.parse_args()
    report = check_run(args.run, args.brc)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
