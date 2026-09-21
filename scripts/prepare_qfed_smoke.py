#!/usr/bin/env python3
"""Stage paired, one-hour QFED2 BrC smoke fixtures without an executable.

This is deliberately a staging tool, not a launcher.  It only accepts a
completed GFED fixture as a donor and refuses to overwrite an output root.
The manifest leaves executable and source provenance PENDING for the build
and run stewards to fill after their respective gates pass.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


START = "20190701, 000000"
END = "20190701, 010000"
CASES = (("BRC_BASE_QFED2_ONLINE_HSOFF_20260921", False),
         ("BRC_BASE_QFED2_ONLINE_HSON_20260921", True))
SCALAR_IDS = ("288", "289", "290", "291", "292")
FIRE_FLAGS = {
    "QFED2": True,
    "QFED2_BRC_HARMONIZED_SENSITIVITY": False,
    "GFED4_CLIMATOLOGY": False,
    "FINNv25": False,
    "FINNV25_BRC_HARMONIZED_SENSITIVITY": False,
    "GFAS_BRC_HARMONIZED_SENSITIVITY": False,
    "BB4MIPS": False,
    "GFED4": False,
    "GFED_daily": False,
    "GFED_3hourly": False,
}

QFED_DIAGNOSTICS = (
    ("CO", "CO"), ("BCPI", "BCPI"), ("BCPO", "BCPO"),
    ("OCPI", "OCPI"), ("OCPO", "OCPO"), ("FSOAP", "FSOAP"),
    ("DBRCPOA", "DBRCPOA"), ("NPBRCPOA", "NPBRCPOA"),
    ("PBRCPOA", "PBRCPOA"),
)


def replace_setting(text: str, name: str, value: bool) -> str:
    """Set exactly one HEMCO setting while retaining its aligned comment."""
    pattern = re.compile(rf"^(\s*-->\s*{re.escape(name)}\s*:\s*)\S+(.*)$", re.M)
    text, count = pattern.subn(rf"\1{'true' if value else 'false'}\2", text)
    if count != 1:
        raise ValueError(f"expected one setting {name!r}, found {count}")
    return text


def ensure_setting(text: str, template: str, name: str, after: str) -> str:
    """Insert a reviewed setting once when an older donor predates it."""
    pattern = re.compile(rf"^\s*-->\s*{re.escape(name)}\s*:", re.M)
    count = len(pattern.findall(text))
    if count == 1:
        return text
    if count:
        raise ValueError(f"expected at most one setting {name!r}, found {count}")
    source = re.search(rf"^(\s*-->\s*{re.escape(name)}\s*:\s*.*)$", template, re.M)
    anchor = re.compile(rf"^(\s*-->\s*{re.escape(after)}\s*:\s*.*)$", re.M)
    if not source or len(anchor.findall(text)) != 1:
        raise ValueError(f"cannot insert reviewed setting {name!r}")
    return anchor.sub(lambda match: match.group(1) + "\n" + source.group(1), text, count=1)


def qfed_block(text: str) -> str:
    match = re.search(r"^# --- QFED2 biomass burning \(v2\.5r1\) ---\n"
                      r".*?^\)\)\)QFED2\s*$", text, re.M | re.S)
    if not match:
        raise ValueError("reviewed template has no complete QFED2 block")
    return match.group(0)


def scalar_lines(text: str) -> str:
    lines = []
    for ident in SCALAR_IDS:
        matches = re.findall(rf"^\s*{ident}\s+.*$", text, re.M)
        if len(matches) != 1:
            raise ValueError(f"reviewed template must define scalar {ident} once")
        lines.append(matches[0])
    return "\n".join(lines)


def replace_qfed_and_scalars(donor: str, template: str, harmonized: bool) -> str:
    for ident in SCALAR_IDS:
        if re.search(rf"^\s*{ident}\s+", donor, re.M):
            raise ValueError(f"donor already defines QFED scalar ID {ident}")
    donor_match = re.search(r"^# --- QFED2 biomass burning \(v2\.5r1\) ---\n"
                            r".*?^\)\)\)QFED2\s*$", donor, re.M | re.S)
    if not donor_match:
        raise ValueError("GFED donor has no replaceable QFED2 block")
    result = donor[:donor_match.start()] + qfed_block(template) + donor[donor_match.end():]
    result = ensure_setting(result, template, "QFED2_BRC_HARMONIZED_SENSITIVITY", "QFED2")
    for name, value in FIRE_FLAGS.items():
        result = replace_setting(result, name, value)
    result = replace_setting(result, "QFED2_BRC_HARMONIZED_SENSITIVITY", harmonized)
    # Keep the native GFAS extension inactive even if donor settings change.
    result, count = re.subn(r"^(\s*112\s+GFAS\s*:\s*)\S+(.*)$", r"\1off\2", result, flags=re.M)
    if count != 1:
        raise ValueError(f"expected one GFAS extension setting, found {count}")
    for extension, name in (("111", "GFED"), ("165", "FINNv25_Inject")):
        result, count = re.subn(rf"^(\s*{extension}\s+{name}\s*:\s*)\S+(.*)$", r"\1off\2", result, flags=re.M)
        if count != 1:
            raise ValueError(f"expected one {name} extension setting, found {count}")
    anchor = "### END SECTION SCALE FACTORS ###"
    if result.count(anchor) != 1:
        raise ValueError("cannot locate unique scale-factor section end")
    factors = "# QFED2 BrC harmonized-sensitivity factors (reviewed core template)\n" + scalar_lines(template) + "\n\n"
    return result.replace(anchor, factors + anchor)


def replace_time_and_brc(yaml_text: str) -> str:
    yaml_text, starts = re.subn(r"^(\s*start_date:\s*)\[[^]]+\]", r"\1[20190701, 000000]", yaml_text, flags=re.M)
    yaml_text, ends = re.subn(r"^(\s*end_date:\s*)\[[^]]+\]", r"\1[20190701, 010000]", yaml_text, flags=re.M)
    yaml_text, brc = re.subn(r"^(\s*brown_carbon:\s*)\S+", r"\1true", yaml_text, flags=re.M)
    if (starts, ends, brc) != (1, 1, 1):
        raise ValueError("expected one start_date, end_date, and brown_carbon key")
    return yaml_text


def one_hour_history(donor_history: str) -> str:
    """Retain the proven donor syntax and fields while enforcing 1-hour cadence."""
    if not all(name in donor_history for name in ("'Restart'", "'Aerosols'", "'BrCDiagnostics'", "'RRTMG'")):
        raise ValueError("donor HISTORY lacks required validated collections")
    donor_history, frequencies = re.subn(r"^(\s*\S+\.frequency:\s*)\S+\s+\S+", r"\g<1>00000000 010000", donor_history, flags=re.M)
    donor_history, durations = re.subn(r"^(\s*\S+\.duration:\s*)\S+\s+\S+", r"\g<1>00000000 010000", donor_history, flags=re.M)
    if not frequencies or frequencies != durations:
        raise ValueError("could not normalize donor HISTORY cadence")
    return donor_history


def qfed_diagn_rc(donor_diagn: str) -> str:
    """Reuse fire-auditor names, retargeted from GFED Ext111 to QFED rows."""
    for label, species in QFED_DIAGNOSTICS:
        for suffix, dimension in (("", "3"), ("Column", "2")):
            name = f"Emis{label}_Fire{suffix}"
            pattern = re.compile(rf"^{name}\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+(.*)$", re.M)
            replacement = f"{name} {species} 0 5 2 {dimension}\\1"
            donor_diagn, count = pattern.subn(replacement, donor_diagn)
            if count != 1:
                raise ValueError(f"expected one donor diagnostic {name}, found {count}")
    return donor_diagn


def stage_case(donor: Path, template: Path, case_dir: Path, harmonized: bool) -> None:
    case_dir.mkdir()
    for name in ("HEMCO_Config.rc.gmao_metfields", "species_database.yml"):
        shutil.copy2(donor / name, case_dir / name)
    shutil.copytree(donor / "build_info", case_dir / "build_info")
    (case_dir / "OutputDir").mkdir()
    (case_dir / "Restarts").mkdir()
    restart = donor / "Restarts" / "GEOSChem.Restart.20190701_0000z.nc4"
    if not restart.exists():
        raise FileNotFoundError(restart)
    shutil.copy2(restart.resolve(), case_dir / "Restarts" / restart.name)
    (case_dir / "HEMCO_Config.rc").write_text(replace_qfed_and_scalars(
        (donor / "HEMCO_Config.rc").read_text(), template.read_text(), harmonized))
    (case_dir / "geoschem_config.yml").write_text(replace_time_and_brc(
        (donor / "geoschem_config.yml").read_text()))
    (case_dir / "HISTORY.rc").write_text(one_hour_history((donor / "HISTORY.rc").read_text()))
    (case_dir / "HEMCO_Diagn.rc").write_text(qfed_diagn_rc((donor / "HEMCO_Diagn.rc").read_text()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor", type=Path, required=True, help="completed published GFED fixture")
    parser.add_argument("--qfed-template", type=Path, required=True, help="reviewed core fullchem HEMCO template")
    parser.add_argument("--outroot", type=Path, required=True, help="new, nonexistent staging root")
    args = parser.parse_args()
    for required in (args.donor / "HEMCO_Config.rc", args.donor / "geoschem_config.yml",
                     args.donor / "HISTORY.rc", args.donor / "HEMCO_Diagn.rc",
                     args.donor / "build_info", args.donor / "Restarts"):
        if not required.exists():
            raise FileNotFoundError(required)
    if args.outroot.exists():
        raise FileExistsError(f"refusing to overwrite existing {args.outroot}")
    args.outroot.mkdir(parents=True)
    try:
        for name, harmonized in CASES:
            stage_case(args.donor, args.qfed_template, args.outroot / name, harmonized)
        manifest = {
            "status": "PENDING_BUILD_AND_SOURCE_FREEZE",
            "donor": str(args.donor), "qfed_template": str(args.qfed_template),
            "start": START, "end": END, "executable": "PENDING",
            "source_contract": "PENDING", "cases": [name for name, _ in CASES],
        }
        (args.outroot / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    except Exception as error:
        (args.outroot / "manifest.json").write_text(json.dumps({
            "status": "STAGING_FAILED", "error": str(error),
            "executable": "PENDING", "source_contract": "PENDING",
        }, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
