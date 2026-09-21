#!/usr/bin/env python3
"""Preflight GEOS-Chem HISTORY collection syntax and required modes."""
import argparse
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


def check_history(path, brc="on", rrtmg="on"):
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
    return {"path": str(Path(path).resolve()), "collections": names,
            "brc": brc, "rrtmg": rrtmg,
            "status": "FAIL" if errors else "PASS", "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("history", type=Path)
    parser.add_argument("--brc", choices=("on", "off"), default="on")
    parser.add_argument("--rrtmg", choices=("on", "off"), default="on")
    args = parser.parse_args()
    report = check_history(args.history, args.brc, args.rrtmg)
    import json
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
