#!/usr/bin/env python3
"""Preflight GEOS-Chem HISTORY collection syntax and required modes."""
import argparse
import calendar
from datetime import datetime, timedelta
import re
from pathlib import Path


_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")


def collections(text):
    found = []
    errors = []
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0]
        if "COLLECTIONS:" in line:
            in_block = True
        elif in_block and line.strip() == "::":
            in_block = False
            continue
        if not in_block:
            continue
        names = _QUOTED.findall(line)
        if len(names) > 1:
            errors.append(f"line {lineno}: multiple collection names on one line")
        if names:
            if any(f'"{name}"' in line for name in names):
                errors.append(f"line {lineno}: collection names must use single quotes")
            if not line.rstrip().endswith(","):
                errors.append(f"line {lineno}: collection entry must end with a comma")
        found.extend(names)
        if line.strip() and not names:
            errors.append(f"line {lineno}: invalid collection entry or missing ::")
    if in_block:
        errors.append("COLLECTIONS block is missing closing ::")
    return found, errors


def cadence_errors(text, names, start, end):
    """Validate active YYYYMMDD HHMMSS periods against the actual run window."""
    start, end = datetime.fromisoformat(start), datetime.fromisoformat(end)
    if end <= start:
        return ["end must be after start"]
    errors = []
    for name in names:
        for kind in ("frequency", "duration"):
            values = re.findall(rf"^\s*{re.escape(name)}\.{kind}:\s*([^#\n]+)", text, re.M)
            if len(values) != 1:
                errors.append(f"{name}.{kind}: expected exactly one active setting")
                continue
            value = values[0].strip().rstrip(",").strip("'\"")
            if value == "End":
                continue
            match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})\s+(\d{2})(\d{2})(\d{2})", value)
            if not match:
                errors.append(f"{name}.{kind}: invalid YYYYMMDD HHMMSS period")
                continue
            years, months, days, hours, minutes, seconds = map(int, match.groups())
            try:
                month_index = start.year * 12 + start.month - 1 + years * 12 + months
                year, month0 = divmod(month_index, 12)
                day = min(start.day, calendar.monthrange(year, month0 + 1)[1])
                next_time = start.replace(year=year, month=month0 + 1, day=day)
                next_time += timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            except (ValueError, OverflowError):
                errors.append(f"{name}.{kind}: period outside supported calendar")
                continue
            if next_time <= start or next_time > end:
                errors.append(f"{name}.{kind}: period must be positive and no longer than the run")
            if (end - start > timedelta(days=3) and name in
                    {"Restart", "SpeciesConc", "Aerosols", "StateMet"} and
                    next_time - start <= timedelta(hours=1)):
                errors.append(f"{name}.{kind}: hourly broad output forbidden for a long validation run")
    return errors


def check_history(path, brc="on", rrtmg="on", start=None, end=None):
    text = Path(path).read_text()
    names, errors = collections(text)
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"\w+\.(?:filename|template|format):\s*(.*)$", line)
        if match and not re.fullmatch(r"'[^']*',", match.group(1)):
            errors.append(f"line {lineno}: filename/template/format requires a single-quoted string and trailing comma")
    actual = set(names)
    required = {"Restart"}
    if brc == "on":
        required.update(("Aerosols", "BrCDiagnostics"))
    if rrtmg == "on":
        required.add("RRTMG")
    missing = sorted(required - actual)
    if missing:
        errors.append("missing required collections: " + ", ".join(missing))
    forbidden = []
    if rrtmg == "off" and "RRTMG" in actual:
        forbidden.append("RRTMG")
    if forbidden:
        errors.append("disabled-mode collections present: " + ", ".join(forbidden))
    if (start is None) != (end is None):
        errors.append("start and end must be supplied together")
    elif start is not None:
        errors.extend(cadence_errors(text, names, start, end))
    return {"path": str(Path(path).resolve()), "collections": names,
            "brc": brc, "rrtmg": rrtmg,
            "status": "FAIL" if errors else "PASS", "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("history", type=Path)
    parser.add_argument("--brc", choices=("on", "off"), default="on")
    parser.add_argument("--rrtmg", choices=("on", "off"), default="on")
    parser.add_argument("--start", help="ISO run start; enables cadence validation")
    parser.add_argument("--end", help="ISO run end; required with --start")
    args = parser.parse_args()
    report = check_history(args.history, args.brc, args.rrtmg, args.start, args.end)
    import json
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
