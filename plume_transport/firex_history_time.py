#!/usr/bin/env python3
"""Read-only CF-time ingestion for FIREX GEOS-Chem HISTORY files.

Timestamped HISTORY filenames identify a file reference, not necessarily the
timestamp of every record within that file.  This module therefore derives
model times only from the NetCDF ``time`` coordinate and its CF ``units``
attribute.  It deliberately supports the exact, explicitly declared contract
needed by the FIREX replay: finite one-dimensional ``minutes since`` values
with a Gregorian calendar.  Unsupported metadata fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

import h5py
import numpy as np
from numpy.typing import ArrayLike, NDArray


_NANOSECONDS_PER_MINUTE = 60_000_000_000
_CF_MINUTES_SINCE = re.compile(
    r"^\s*minutes\s+since\s+(.+?)\s*$", flags=re.IGNORECASE
)
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?$"
)


class FirexHistoryTimeError(ValueError):
    """Raised when a HISTORY time coordinate violates the ingestion contract."""


@dataclass(frozen=True)
class HistoryTimeFile:
    """Decoded time coordinate and immutable provenance for one HISTORY file."""

    path: Path
    numeric_minutes: NDArray[np.float64]
    units: str
    calendar: str
    timestamps: NDArray[np.datetime64]


@dataclass(frozen=True)
class HistoryTimeSeries:
    """Strictly increasing concatenation of decoded HISTORY time coordinates."""

    files: tuple[HistoryTimeFile, ...]
    timestamps: NDArray[np.datetime64]


def _attribute_text(value: object, name: str, path: Path) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        try:
            return bytes(value).decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise FirexHistoryTimeError(
                f"{path}: time:{name} must be ASCII"
            ) from exc
    if isinstance(value, str):
        return value
    raise FirexHistoryTimeError(
        f"{path}: time:{name} must be an ASCII string, got {type(value).__name__}"
    )


def parse_utc_timestamp(value: str, name: str) -> np.datetime64:
    """Parse an explicit UTC timestamp without guessing a timezone or format."""

    if not isinstance(value, str):
        raise FirexHistoryTimeError(f"{name} must be a string")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1]
    elif normalized.upper().endswith(" UTC"):
        normalized = normalized[:-4]
    if not _UTC_TIMESTAMP.fullmatch(normalized):
        raise FirexHistoryTimeError(
            f"{name} must be an ISO-like UTC timestamp, got {value!r}"
        )
    try:
        result = np.datetime64(normalized.replace(" ", "T"), "ns")
    except ValueError as exc:
        raise FirexHistoryTimeError(
            f"{name} is not a valid UTC timestamp: {value!r}"
        ) from exc
    if np.isnat(result):
        raise FirexHistoryTimeError(f"{name} is not a finite timestamp: {value!r}")
    return result


def format_utc_timestamp(value: np.datetime64) -> str:
    """Render a nanosecond timestamp as a compact, explicitly UTC string."""

    timestamp = np.datetime64(value, "ns")
    if np.isnat(timestamp):
        raise FirexHistoryTimeError("cannot format NaT as a UTC timestamp")
    rendered = np.datetime_as_string(timestamp, unit="ns")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered + "Z"


def decode_cf_minutes_since(
    values: ArrayLike,
    units: str,
    calendar: str,
) -> NDArray[np.datetime64]:
    """Decode the supported CF coordinate exactly; never use a filename time.

    Values are represented at nanosecond precision.  A coordinate requiring
    finer precision or an unsupported calendar raises ``FirexHistoryTimeError``
    instead of applying an implicit approximation.
    """

    try:
        numeric = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise FirexHistoryTimeError("time coordinate must be numeric") from exc
    if numeric.ndim != 1 or numeric.size == 0:
        raise FirexHistoryTimeError(
            "time coordinate must be a nonempty one-dimensional numeric array"
        )
    if not np.all(np.isfinite(numeric)):
        raise FirexHistoryTimeError("time coordinate values must be finite")
    if not isinstance(calendar, str):
        raise FirexHistoryTimeError("time:calendar must be a string")
    if calendar.strip().lower() != "gregorian":
        raise FirexHistoryTimeError(
            f"unsupported CF calendar {calendar!r}; expected 'gregorian'"
        )

    if not isinstance(units, str):
        raise FirexHistoryTimeError("time:units must be a string")
    match = _CF_MINUTES_SINCE.fullmatch(units)
    if match is None:
        raise FirexHistoryTimeError(
            f"unsupported time units {units!r}; expected 'minutes since <UTC timestamp>'"
        )
    reference = parse_utc_timestamp(match.group(1), "CF time reference")

    raw_nanoseconds = numeric * _NANOSECONDS_PER_MINUTE
    if not np.all(np.isfinite(raw_nanoseconds)):
        raise FirexHistoryTimeError("time coordinate overflows nanosecond precision")
    rounded_nanoseconds = np.rint(raw_nanoseconds)
    bounds = np.iinfo(np.int64)
    if np.any(rounded_nanoseconds < bounds.min) or np.any(
        rounded_nanoseconds > bounds.max
    ):
        raise FirexHistoryTimeError("time coordinate exceeds int64 nanosecond range")
    if np.any(np.abs(raw_nanoseconds - rounded_nanoseconds) > 0.5):
        raise FirexHistoryTimeError(
            "time coordinate cannot be represented at nanosecond precision"
        )

    offsets = rounded_nanoseconds.astype(np.int64).astype("timedelta64[ns]")
    timestamps = reference + offsets
    if np.any(np.isnat(timestamps)):
        raise FirexHistoryTimeError("decoded time coordinate is outside datetime64 range")
    return timestamps


def read_history_time_file(path: Path | str) -> HistoryTimeFile:
    """Read and decode only the root ``time`` coordinate of one HISTORY file."""

    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FirexHistoryTimeError(f"HISTORY file is absent: {resolved}")
    try:
        with h5py.File(resolved, "r") as dataset:
            if "time" not in dataset:
                raise FirexHistoryTimeError(f"{resolved}: missing root time coordinate")
            coordinate = dataset["time"]
            if coordinate.ndim != 1:
                raise FirexHistoryTimeError(
                    f"{resolved}: time coordinate must be one-dimensional"
                )
            if "units" not in coordinate.attrs:
                raise FirexHistoryTimeError(f"{resolved}: time:units is absent")
            if "calendar" not in coordinate.attrs:
                raise FirexHistoryTimeError(f"{resolved}: time:calendar is absent")
            units = _attribute_text(coordinate.attrs["units"], "units", resolved)
            calendar = _attribute_text(
                coordinate.attrs["calendar"], "calendar", resolved
            )
            numeric_minutes = np.asarray(coordinate[:], dtype=np.float64)
    except FirexHistoryTimeError:
        raise
    except OSError as exc:
        raise FirexHistoryTimeError(
            f"{resolved}: cannot open as a readable NetCDF4/HDF5 file"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise FirexHistoryTimeError(
            f"{resolved}: time coordinate is not a readable numeric array"
        ) from exc

    timestamps = decode_cf_minutes_since(numeric_minutes, units, calendar)
    return HistoryTimeFile(
        path=resolved,
        numeric_minutes=numeric_minutes,
        units=units,
        calendar=calendar,
        timestamps=timestamps,
    )


def load_history_time_series(paths: Sequence[Path | str]) -> HistoryTimeSeries:
    """Read files in caller-supplied order and require a strict global timeline."""

    if not paths:
        raise FirexHistoryTimeError("at least one HISTORY file is required")
    files = tuple(read_history_time_file(path) for path in paths)
    timestamps = np.concatenate([record.timestamps for record in files])
    integer_time = timestamps.astype("datetime64[ns]").astype(np.int64)
    nonincreasing = np.flatnonzero(np.diff(integer_time) <= 0)
    if nonincreasing.size:
        index = int(nonincreasing[0])
        raise FirexHistoryTimeError(
            "decoded HISTORY times must be strictly increasing; "
            f"records {index} and {index + 1} are "
            f"{format_utc_timestamp(timestamps[index])} and "
            f"{format_utc_timestamp(timestamps[index + 1])}"
        )
    return HistoryTimeSeries(files=files, timestamps=timestamps)


def validate_regular_time_series(
    series: HistoryTimeSeries,
    *,
    expected_records: int,
    cadence_minutes: int,
    expected_first: str,
    expected_last: str,
) -> dict[str, object]:
    """Fail closed unless a decoded timeline matches an explicit regular contract."""

    if not isinstance(expected_records, (int, np.integer)) or isinstance(
        expected_records, bool
    ) or expected_records < 1:
        raise FirexHistoryTimeError("expected_records must be a positive integer")
    if not isinstance(cadence_minutes, (int, np.integer)) or isinstance(
        cadence_minutes, bool
    ) or cadence_minutes < 1:
        raise FirexHistoryTimeError("cadence_minutes must be a positive integer")
    if series.timestamps.size != expected_records:
        raise FirexHistoryTimeError(
            f"decoded record count {series.timestamps.size} != expected {expected_records}"
        )

    first = parse_utc_timestamp(expected_first, "expected first timestamp")
    last = parse_utc_timestamp(expected_last, "expected last timestamp")
    actual = series.timestamps.astype("datetime64[ns]")
    if actual[0] != first:
        raise FirexHistoryTimeError(
            "decoded first timestamp "
            f"{format_utc_timestamp(actual[0])} != expected "
            f"{format_utc_timestamp(first)}"
        )
    if actual[-1] != last:
        raise FirexHistoryTimeError(
            "decoded last timestamp "
            f"{format_utc_timestamp(actual[-1])} != expected "
            f"{format_utc_timestamp(last)}"
        )

    expected_spacing = cadence_minutes * _NANOSECONDS_PER_MINUTE
    observed_spacing = np.diff(actual.astype(np.int64))
    bad_spacing = np.flatnonzero(observed_spacing != expected_spacing)
    if bad_spacing.size:
        index = int(bad_spacing[0])
        raise FirexHistoryTimeError(
            f"decoded cadence between records {index} and {index + 1} is "
            f"{observed_spacing[index] / _NANOSECONDS_PER_MINUTE:g} minutes, "
            f"not {cadence_minutes}"
        )

    return {
        "decoded_records": int(actual.size),
        "decoded_first": format_utc_timestamp(actual[0]),
        "decoded_last": format_utc_timestamp(actual[-1]),
        "cadence_minutes": cadence_minutes,
    }
