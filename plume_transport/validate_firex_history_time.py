#!/usr/bin/env python3
"""Validate a read-only, explicit CF-time contract for FIREX HISTORY files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

if __package__:
    from .firex_history_time import (
        FirexHistoryTimeError,
        HistoryTimeFile,
        format_utc_timestamp,
        load_history_time_series,
        validate_regular_time_series,
    )
else:
    from firex_history_time import (  # type: ignore[no-redef]
        FirexHistoryTimeError,
        HistoryTimeFile,
        format_utc_timestamp,
        load_history_time_series,
        validate_regular_time_series,
    )


def _file_report(record: HistoryTimeFile) -> dict[str, object]:
    return {
        "path": str(record.path),
        "time_records": int(record.timestamps.size),
        "numeric_time_minutes": [
            float(record.numeric_minutes[0]),
            float(record.numeric_minutes[-1]),
        ],
        "time_units": record.units,
        "calendar": record.calendar,
        "decoded_first": format_utc_timestamp(record.timestamps[0]),
        "decoded_last": format_utc_timestamp(record.timestamps[-1]),
    }


def build_report(
    history_files: Sequence[Path | str],
    *,
    expected_records: int,
    cadence_minutes: int,
    expected_first: str,
    expected_last: str,
) -> dict[str, object]:
    """Build a JSON-safe pass/fail report without changing any model output."""

    requested_paths = [str(Path(path).resolve()) for path in history_files]
    report: dict[str, object] = {
        "schema_version": "firex-history-time-v1",
        "validator": "validate_firex_history_time.py",
        "result": "fail",
        "input_files": requested_paths,
        "time_contract": {
            "decoder": "CF minutes-since reference plus numeric time coordinate",
            "filename_timestamp_used_for_record_time": False,
            "expected_records": expected_records,
            "cadence_minutes": cadence_minutes,
            "expected_first": expected_first,
            "expected_last": expected_last,
        },
        "files": [],
        "errors": [],
        "non_claims": [
            "No NetCDF value or metadata was written.",
            "Filename timestamps were not used to infer record timestamps.",
            "This is an ingestion-time gate, not scientific acceptance.",
        ],
    }
    try:
        series = load_history_time_series(history_files)
        report["files"] = [_file_report(record) for record in series.files]
        report["decoded_timeline"] = validate_regular_time_series(
            series,
            expected_records=expected_records,
            cadence_minutes=cadence_minutes,
            expected_first=expected_first,
            expected_last=expected_last,
        )
    except FirexHistoryTimeError as exc:
        report["errors"] = [str(exc)]
    else:
        report["result"] = "pass"
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read and validate a CF-time timeline without modifying NetCDF files."
    )
    parser.add_argument("history_files", nargs="+", type=Path)
    parser.add_argument("--expected-records", type=int, required=True)
    parser.add_argument("--cadence-minutes", type=int, required=True)
    parser.add_argument("--expected-first", required=True)
    parser.add_argument("--expected-last", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output is not None:
        input_paths = {path.resolve() for path in args.history_files}
        if args.output.resolve() in input_paths:
            raise FirexHistoryTimeError(
                "validation report path must not overwrite an input NetCDF file"
            )
    report = build_report(
        args.history_files,
        expected_records=args.expected_records,
        cadence_minutes=args.cadence_minutes,
        expected_first=args.expected_first,
        expected_last=args.expected_last,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
