#!/usr/bin/env python3
"""Compare matched GEOS-Chem PlaneFlight samples in pressure bins.

Example (no model execution):
  compare_planeflight_profiles.py LEFT/OutputDir RIGHT/OutputDir \
    --left-schedule-dir LEFT --right-schedule-dir RIGHT \
    --fields OCPI,BCPI,FSOAP,DBRCPOA --pressure-bins 400,500,600,700,800,900

This is an end-to-end *flight-track* comparison.  It reports paired model
samples in their native PlaneFlight concentration units (molec/cm3); it does
not infer a grid-column profile or perform mass conversion/interpolation.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np


LOG_RE = re.compile(r"^plane\.log\.(\d{8})$")
SCHEDULE_NAME = "Planeflight.dat.{date}"
KEY_COLUMNS = ("TYPE", "YYYYMMDD", "HHMM")
COORD_COLUMNS = ("LAT", "LON", "PRESS")
# PlaneFlight output prints these three columns to two decimal places.
PRINTED_PRECISION_TOLERANCE = 0.005001
MISSING_SENTINELS = frozenset((-999.0, -9999.0, -99999.0, -999999.0,
                               -1.0e30, 1.0e30))
# Units are verified only for named chemical-species fields: PlaneFlight writes
# those through its chemical-species branch as molec/cm3.  Met/AOD fields are
# intentionally excluded rather than being assigned an invented common unit.
CHEMICAL_SPECIES = frozenset((
    "OCPI", "OCPO", "BCPI", "BCPO", "SOAS", "SOAP", "FSOAP", "FSOAS",
    "NPBRCPOA", "DBRCPOA", "BRCSOA", "WTC", "PBRCPOA", "FFOCPI", "FFOCPO",
    "CO", "O3", "BENZ", "PHEN", "FURA", "CH2Cl2",
))


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reject_missing(value: float, context: str) -> None:
    if not np.isfinite(value):
        raise ValueError(f"{context}: nonfinite value")
    if value in MISSING_SENTINELS or abs(value) >= 1.0e29:
        raise ValueError(f"{context}: missing-value sentinel {value}")


def read_log(path: Path, requested: tuple[str, ...], expected_date: str) -> dict[tuple[str, str, str], dict[str, float]]:
    lines = path.read_text().splitlines()
    header_number = next((number for number, line in enumerate(lines) if line.strip()), None)
    if header_number is None:
        raise ValueError(f"{path}: empty PlaneFlight log")
    header = lines[header_number].split()
    if len(header) != len(set(header)):
        raise ValueError(f"{path}: duplicate header field")
    missing = [field for field in (*KEY_COLUMNS, *COORD_COLUMNS, *requested) if field not in header]
    if missing:
        raise ValueError(f"{path}: missing requested/header fields: {', '.join(missing)}")
    indices = {name: header.index(name) for name in (*KEY_COLUMNS, *COORD_COLUMNS, *requested)}
    output: dict[tuple[str, str, str], dict[str, float]] = {}
    for line_number, line in enumerate(lines[header_number + 1:], start=header_number + 2):
        if not line.strip():
            continue
        tokens = line.split()
        if len(tokens) != len(header):
            raise ValueError(f"{path}:{line_number}: expected {len(header)} columns, got {len(tokens)}")
        key = tuple(tokens[indices[name]] for name in KEY_COLUMNS)
        if key in output:
            raise ValueError(f"{path}:{line_number}: duplicate flight key {key}")
        if key[1] != expected_date:
            raise ValueError(f"{path}:{line_number}: YYYYMMDD does not match filename date {expected_date}")
        if not re.fullmatch(r"\d{8}", key[1]) or not re.fullmatch(r"\d{4}", key[2]):
            raise ValueError(f"{path}:{line_number}: invalid YYYYMMDD/HHMM key")
        try:
            datetime.strptime(key[1] + key[2], "%Y%m%d%H%M")
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid YYYYMMDD/HHMM key") from exc
        row: dict[str, float] = {}
        for name in (*COORD_COLUMNS, *requested):
            try:
                value = float(tokens[indices[name]])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}:{name}: nonnumeric value") from exc
            reject_missing(value, f"{path}:{line_number}:{name}")
            if name in requested and value < 0:
                raise ValueError(f"{path}:{line_number}:{name}: negative chemical concentration")
            row[name] = value
        output[key] = row
    if not output:
        raise ValueError(f"{path}: no data rows")
    return output


def parse_csv(values: str, label: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in values.split(",") if item.strip())
    if not result or len(result) != len(set(result)):
        raise ValueError(f"{label} must be a nonempty comma-separated unique list")
    return result


def parse_bins(values: str) -> tuple[float, ...]:
    try:
        edges = tuple(float(value) for value in parse_csv(values, "pressure bins"))
    except ValueError as exc:
        raise ValueError("pressure bins must be numeric") from exc
    if len(edges) < 2 or any(not np.isfinite(value) for value in edges) or any(a >= b for a, b in zip(edges, edges[1:])):
        raise ValueError("pressure bins must be at least two strictly increasing finite hPa edges")
    return edges


def discovered_dates(directory: Path) -> set[str]:
    if not directory.is_dir():
        raise ValueError(f"missing PlaneFlight directory: {directory}")
    return {match.group(1) for path in directory.iterdir()
            if (match := LOG_RE.match(path.name)) and path.is_file()}


def normalize_longitude(value: float) -> float:
    """Normalize a schedule longitude to the PlaneFlight output convention."""
    return (value + 180.) % 360. - 180.


def schedule_points(path: Path) -> dict[tuple[str, str, str], dict[str, float]]:
    """Read key and coordinates after the canonical Point/Type/DD-MM-YYYY/HH:MM header."""
    lines = path.read_text().splitlines()
    point_header = next((index for index, line in enumerate(lines)
                         if line.split()[:4] == ["Point", "Type", "DD-MM-YYYY", "HH:MM"]), None)
    if point_header is None:
        raise ValueError(f"{path}: missing canonical flight-point header")
    points: dict[tuple[str, str, str], dict[str, float]] = {}
    for line_number, line in enumerate(lines[point_header + 1:], start=point_header + 2):
        if not line.strip():
            continue
        tokens = line.split()
        if len(tokens) < 6:
            raise ValueError(f"{path}:{line_number}: malformed flight point")
        point_type, date, time = tokens[:3]
        if point_type == "99999END" and date == "00-00-0000" and time == "00:00":
            break
        match = re.fullmatch(r"\d+(.+)", point_type)
        if not match or not re.fullmatch(r"\d{2}-\d{2}-\d{4}", date) or not re.fullmatch(r"\d{2}:\d{2}", time):
            raise ValueError(f"{path}:{line_number}: invalid flight point key")
        day, month, year = date.split("-")
        key = (match.group(1), year + month + day, time.replace(":", ""))
        if key in points:
            raise ValueError(f"{path}:{line_number}: duplicate schedule key {key}")
        try:
            latitude, longitude, pressure = (float(value) for value in tokens[3:6])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: nonnumeric flight coordinates") from exc
        for name, value in (("LAT", latitude), ("LON", longitude), ("PRESS", pressure)):
            reject_missing(value, f"{path}:{line_number}:{name}")
        points[key] = {"LAT": latitude, "LON": normalize_longitude(longitude), "PRESS": pressure}
    if not points:
        raise ValueError(f"{path}: no flight points")
    return points


def schedule_keys(path: Path) -> set[tuple[str, str, str]]:
    """Compatibility helper for callers that need only schedule keys."""
    return set(schedule_points(path))


def summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "median": None, "q25": None, "q75": None}
    array = np.asarray(values, dtype=float)
    return {"count": int(array.size), "median": float(np.median(array)),
            "q25": float(np.quantile(array, .25)), "q75": float(np.quantile(array, .75))}


def bin_index(pressure: float, edges: tuple[float, ...]) -> int | None:
    if pressure < edges[0] or pressure > edges[-1]:
        return None
    index = int(np.searchsorted(edges, pressure, side="right") - 1)
    return min(index, len(edges) - 2)  # The final bin includes its upper edge.


def compare(left_dir: Path, right_dir: Path, left_schedule_dir: Path, right_schedule_dir: Path,
            fields: tuple[str, ...], edges: tuple[float, ...], expected_dates: tuple[str, ...] | None = None) -> dict:
    if not fields or len(fields) != len(set(fields)):
        raise ValueError("fields must be a nonempty unique sequence")
    if len(edges) < 2 or any(not np.isfinite(edge) for edge in edges) or any(a >= b for a, b in zip(edges, edges[1:])):
        raise ValueError("pressure bins must be at least two strictly increasing finite hPa edges")
    if any(field.startswith("TRA_") for field in fields):
        raise ValueError("TRA_* numeric fields are nonportable; request named fields only")
    unsupported = [field for field in fields if field not in CHEMICAL_SPECIES]
    if unsupported:
        raise ValueError("fields lack verified chemical-species molec/cm3 units: " + ", ".join(unsupported))
    if expected_dates is not None and (not expected_dates or len(expected_dates) != len(set(expected_dates)) or
                                       any(not re.fullmatch(r"\d{8}", date) for date in expected_dates)):
        raise ValueError("expected dates must be a nonempty unique YYYYMMDD sequence")
    left_dates, right_dates = discovered_dates(left_dir), discovered_dates(right_dir)
    dates = set(expected_dates) if expected_dates is not None else left_dates | right_dates
    if not dates:
        raise ValueError("no PlaneFlight dates supplied")
    missing_left, missing_right = sorted(dates - left_dates), sorted(dates - right_dates)
    if missing_left or missing_right:
        raise ValueError(f"missing PlaneFlight days: left={missing_left}, right={missing_right}")
    if expected_dates is None and left_dates != right_dates:
        raise ValueError(f"unmatched PlaneFlight days: left_only={sorted(left_dates-right_dates)}, right_only={sorted(right_dates-left_dates)}")

    bins = [{"lower_hpa": edges[index], "upper_hpa": edges[index + 1],
             "fields": {field: {"left": [], "right": [], "delta_14_8_minus_14_7": []}
                        for field in fields}}
            for index in range(len(edges) - 1)]
    date_report, excluded = {}, 0
    for date in sorted(dates):
        left_schedule = left_schedule_dir / SCHEDULE_NAME.format(date=date)
        right_schedule = right_schedule_dir / SCHEDULE_NAME.format(date=date)
        if not left_schedule.is_file() or not right_schedule.is_file():
            raise ValueError(f"{date}: missing corresponding input schedule")
        left_schedule_hash, right_schedule_hash = sha256(left_schedule), sha256(right_schedule)
        if left_schedule_hash != right_schedule_hash:
            raise ValueError(f"{date}: input schedule SHA-256 differs")
        left_path, right_path = left_dir / f"plane.log.{date}", right_dir / f"plane.log.{date}"
        left, right = read_log(left_path, fields, date), read_log(right_path, fields, date)
        scheduled = schedule_points(left_schedule)
        left_only, right_only = sorted(set(left) - set(right)), sorted(set(right) - set(left))
        if left_only or right_only:
            raise ValueError(f"{date}: unmatched track rows: left_only={left_only[:3]}, right_only={right_only[:3]}")
        if set(left) != set(scheduled) or set(right) != set(scheduled):
            raise ValueError(f"{date}: output rows do not exactly cover the input schedule")
        for key in left:
            for coordinate in COORD_COLUMNS:
                if abs(left[key][coordinate] - scheduled[key][coordinate]) > PRINTED_PRECISION_TOLERANCE:
                    raise ValueError(f"{date}:{key}: left {coordinate} differs from input schedule")
                if abs(right[key][coordinate] - scheduled[key][coordinate]) > PRINTED_PRECISION_TOLERANCE:
                    raise ValueError(f"{date}:{key}: right {coordinate} differs from input schedule")
            for coordinate in COORD_COLUMNS:
                if abs(left[key][coordinate] - right[key][coordinate]) > PRINTED_PRECISION_TOLERANCE:
                    raise ValueError(f"{date}:{key}: {coordinate} differs beyond printed precision")
            index = bin_index(left[key]["PRESS"], edges)
            if index is None:
                excluded += 1
                continue
            for field in fields:
                bins[index]["fields"][field]["left"].append(left[key][field])
                bins[index]["fields"][field]["right"].append(right[key][field])
                bins[index]["fields"][field]["delta_14_8_minus_14_7"].append(right[key][field] - left[key][field])
        date_report[date] = {"left_log_sha256": sha256(left_path), "right_log_sha256": sha256(right_path),
                             "schedule_sha256": left_schedule_hash, "matched_rows": len(left),
                             "scheduled_rows": len(scheduled)}
    for bin_record in bins:
        bin_record["fields"] = {field: {name: summarize(values) for name, values in measures.items()}
                                for field, measures in bin_record["fields"].items()}
    return {
        "status": "PASS", "dates": date_report, "pressure_bins": bins,
        "excluded_samples_outside_pressure_bins": excluded,
        "fields": list(fields),
        "units": {"pressure": "hPa", "chemical_species": "molec/cm3"},
        "scope": "Confounded end-to-end paired flight-track comparison; no mass conversion, interpolation, or grid-column inference.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("left_dir", type=Path, help="14.7 PlaneFlight OutputDir")
    parser.add_argument("right_dir", type=Path, help="14.8 PlaneFlight OutputDir")
    parser.add_argument("--left-schedule-dir", type=Path, required=True)
    parser.add_argument("--right-schedule-dir", type=Path, required=True)
    parser.add_argument("--fields", required=True, help="comma-separated named PlaneFlight fields")
    parser.add_argument("--pressure-bins", required=True, help="comma-separated increasing hPa edges")
    parser.add_argument("--expected-dates", help="optional comma-separated YYYYMMDD subset; otherwise all supplied dates")
    args = parser.parse_args(argv)
    try:
        fields = parse_csv(args.fields, "fields")
        expected_dates = parse_csv(args.expected_dates, "expected dates") if args.expected_dates else None
        if expected_dates and any(not re.fullmatch(r"\d{8}", date) for date in expected_dates):
            raise ValueError("expected dates must be YYYYMMDD")
        result = compare(args.left_dir, args.right_dir, args.left_schedule_dir, args.right_schedule_dir,
                         fields, parse_bins(args.pressure_bins), expected_dates)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
