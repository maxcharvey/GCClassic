#!/usr/bin/env python3
"""Build the fail-closed FIREX-AQ 2019-08-06 Tier-F Phase-2 join.

The output is a record-preserving temporal relationship, not a reaggregation
or a scientific evaluation.  Source tokens remain strings and every source
record retains a stable payload-hash/ordinal identity.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence

from fetch_firex_aq_tier_f_authorities import (
    AcquisitionError,
    R9_FIELDS,
    audit_r12,
    audit_r9,
    audit_r9_mrg01_mirrors,
    compare_r9_r12_intervals,
    sha256_file,
    verify_v1_seal,
)


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_CONTRACT = SCRIPT_PATH.with_name(
    "phase2_tier_f_join_contract_20190806_v1.json"
)
SEAL_NAME = "PHASE2_JOIN_SEAL.json"
ARTIFACT_MANIFEST_NAME = "ARTIFACT_MANIFEST.json"
RUN_MANIFEST_NAME = "run_manifest.json"
VALIDATION_NAME = "validation.json"
SOURCE_INVENTORY_NAME = "source_record_inventory.csv"
LINKS_NAME = "carrier_source_links.csv"
JOIN_NAME = "carrier_join.csv"

PRODUCT_FILENAMES = {
    "mrg01": "FIREXAQ-mrg01-DC8_merge_20190806_R3.ict",
    "AOP": "firexaq-AOP-optical_DC8_20190806_R2.ict",
    "FSU": "firexaq-FSU-smokeage_dc8_20190806_R1.ict",
    "SP2": "FIREXAQ-SP2-BC-1HZ_DC8_20190806_R4.ict",
    "AMS": "FIREXAQ-AMS_DC8_20190806_R3.ict",
    "R9": "firexaq-fire-Flags-1HZ_DC8_20190806_R9.ict",
    "R12": (
        "FIREXAQ-FIREFLAG-TABULARDATA_Analysis_"
        "20190724_R12_thru20190905.xlsx"
    ),
}

EXACT_ONE_SECOND_PRODUCTS = ("R9", "AOP", "FSU", "SP2")
LINK_PRODUCTS = ("R9", "AOP", "FSU", "SP2", "AMS", "R12")
NAVIGATION_FIELDS = (
    "Time_Start",
    "Time_Stop",
    "Day_Of_Year",
    "Latitude",
    "Longitude",
    "MSL_GPS_Altitude",
    "HAE_GPS_Altitude",
    "Pressure_Altitude",
    "Static_Air_Temp",
    "Static_Pressure",
    "Relative_Humidity",
)


class JoinError(RuntimeError):
    """Raised when a Phase-2 acceptance condition cannot be proved."""


@dataclass(frozen=True)
class SourceRecord:
    product: str
    source_id: str
    ordinal: int
    start: Decimal
    stop: Decimal
    raw_line: bytes
    values: Mapping[str, str]
    worksheet_row: int | None = None

    @property
    def raw_sha256(self) -> str:
        return hashlib.sha256(self.raw_line).hexdigest()


@dataclass(frozen=True)
class IcarttSource:
    product: str
    path: Path
    payload_sha256: str
    header_lines: int
    fields: tuple[str, ...]
    missing_values: Mapping[str, str]
    records: tuple[SourceRecord, ...]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def exact_decimal(value: str, label: str) -> Decimal:
    try:
        result = Decimal(value.strip())
    except InvalidOperation as error:
        raise JoinError(f"{label} is not an exact decimal: {value!r}") from error
    if not result.is_finite():
        raise JoinError(f"{label} is non-finite: {value!r}")
    return result


def integral_time(value: str, label: str) -> int:
    number = exact_decimal(value, label)
    if number != number.to_integral_value():
        raise JoinError(f"{label} is not integral: {value!r}")
    return int(number)


def record_id(payload_sha256: str, ordinal: int) -> str:
    return f"{payload_sha256}:{ordinal}"


def _field_lookup(fields: Sequence[str], requested: str) -> int:
    folded = [field.casefold() for field in fields]
    try:
        return folded.index(requested.casefold())
    except ValueError as error:
        raise JoinError(f"required field {requested!r} is absent") from error


def _read_header(
    handle: Any, path: Path
) -> tuple[int, tuple[str, ...], dict[str, str]]:
    first = handle.readline()
    if not first:
        raise JoinError(f"{path}: empty ICARTT payload")
    try:
        count = int(first.decode("latin1").split(",", 1)[0].strip())
    except (UnicodeError, ValueError) as error:
        raise JoinError(f"{path}: invalid ICARTT header count") from error
    if count < 1:
        raise JoinError(f"{path}: invalid ICARTT header count {count}")
    lines = [first]
    for _ in range(count - 1):
        line = handle.readline()
        if not line:
            raise JoinError(f"{path}: truncated ICARTT header")
        lines.append(line)
    fields = tuple(
        token.strip()
        for token in next(csv.reader([lines[-1].decode("latin1")]))
    )
    if not fields or len(set(field.casefold() for field in fields)) != len(fields):
        raise JoinError(f"{path}: empty or duplicate ICARTT field names")
    missing_values: dict[str, str] = {}
    if len(lines) >= 12:
        try:
            dependent_count = int(lines[9].decode("latin1").strip())
            missing_tokens = tuple(
                token.strip()
                for token in next(csv.reader([lines[11].decode("latin1")]))
            )
        except (UnicodeError, ValueError, csv.Error) as error:
            raise JoinError(
                f"{path}: invalid ICARTT dependent-variable metadata"
            ) from error
        if dependent_count != len(fields) - 1:
            raise JoinError(
                f"{path}: declared {dependent_count} dependent variables "
                f"but schema has {len(fields) - 1}"
            )
        if len(missing_tokens) != dependent_count or any(
            not token for token in missing_tokens
        ):
            raise JoinError(
                f"{path}: missing-value declaration width does not match "
                "dependent-variable count"
            )
        missing_values = dict(
            zip(fields[1:], missing_tokens, strict=True)
        )
    return count, fields, missing_values


def iter_icartt_rows(
    path: Path,
) -> tuple[
    int,
    tuple[str, ...],
    Mapping[str, str],
    Iterator[tuple[int, bytes, tuple[str, ...]]],
]:
    """Return header metadata and a generator owning its binary file handle."""
    handle = path.open("rb")
    try:
        header_lines, fields, missing_values = _read_header(handle, path)
    except Exception:
        handle.close()
        raise

    def rows() -> Iterator[tuple[int, bytes, tuple[str, ...]]]:
        try:
            ordinal = 0
            for physical in handle:
                raw = physical.rstrip(b"\r\n")
                if not raw.strip():
                    continue
                tokens = tuple(
                    token.strip()
                    for token in next(
                        csv.reader([raw.decode("latin1")], skipinitialspace=True)
                    )
                )
                if len(tokens) != len(fields):
                    raise JoinError(
                        f"{path}: row {ordinal} width {len(tokens)} "
                        f"does not match schema width {len(fields)}"
                    )
                yield ordinal, raw, tokens
                ordinal += 1
        finally:
            handle.close()

    return header_lines, fields, missing_values, rows()


def load_icartt_source(
    product: str,
    path: Path,
    *,
    expected_sha256: str,
    explicit_stop: bool,
) -> IcarttSource:
    observed_sha256 = sha256_file(path)
    if observed_sha256 != expected_sha256:
        raise JoinError(
            f"{product} payload hash changed: expected {expected_sha256}, "
            f"got {observed_sha256}"
        )
    header_lines, fields, missing_values, rows = iter_icartt_rows(path)
    if len(missing_values) != len(fields) - 1:
        raise JoinError(
            f"{product} lacks a complete ICARTT missing-value declaration"
        )
    start_index = _field_lookup(fields, "Time_Start")
    stop_index = _field_lookup(fields, "Time_Stop") if explicit_stop else None
    records: list[SourceRecord] = []
    for ordinal, raw, tokens in rows:
        start = exact_decimal(tokens[start_index], f"{product} Time_Start {ordinal}")
        stop = (
            exact_decimal(tokens[stop_index], f"{product} Time_Stop {ordinal}")
            if stop_index is not None
            else start + Decimal(1)
        )
        if stop <= start:
            raise JoinError(
                f"{product} record {ordinal} has non-positive interval "
                f"[{start}, {stop})"
            )
        values = dict(zip(fields, tokens, strict=True))
        records.append(
            SourceRecord(
                product=product,
                source_id=record_id(observed_sha256, ordinal),
                ordinal=ordinal,
                start=start,
                stop=stop,
                raw_line=raw,
                values=values,
            )
        )
    if any(
        right.start < left.start
        for left, right in zip(records, records[1:], strict=False)
    ):
        raise JoinError(f"{product} Time_Start is not nondecreasing")
    return IcarttSource(
        product=product,
        path=path,
        payload_sha256=observed_sha256,
        header_lines=header_lines,
        fields=fields,
        missing_values=missing_values,
        records=tuple(records),
    )


def v1_payload_records(v1_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    payloads = v1_manifest.get("payloads")
    if not isinstance(payloads, list):
        raise JoinError("sealed v1 payload inventory is malformed")
    result: dict[str, Mapping[str, Any]] = {}
    for item in payloads:
        if not isinstance(item, dict) or not isinstance(
            item.get("archive_filename"), str
        ):
            raise JoinError("sealed v1 payload record is malformed")
        result[str(item["archive_filename"])] = item
    return result


def verify_contract_and_roots(contract_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("scope") != "source-record-preserving-join-only":
        raise JoinError("execution contract has the wrong scope")
    roots = contract["roots"]
    frozen = contract["frozen_hashes"]
    v1 = Path(roots["sealed_v1"])
    v2 = Path(roots["sealed_v2"])
    required = {
        v1 / "ACQUISITION_SEAL.json": frozen["v1_seal"],
        v1 / "tier_f_acquisition_manifest.json": frozen["v1_manifest"],
        v2 / "AUTHORITY_ACQUISITION_SEAL.json": frozen["v2_seal"],
        v2 / "tier_f_authority_acquisition_manifest.json": frozen["v2_manifest"],
        v2 / "acquisition_contract.yml": frozen["v2_contract"],
        v2 / "audits/authority_semantic_audit.json": frozen["v2_semantic_audit"],
        v2 / "audits/r12_ooxml_audit.json": frozen["v2_r12_audit"],
    }
    for path, expected_hash in required.items():
        if not path.is_file():
            raise JoinError(f"required frozen artifact is absent: {path}")
        observed = sha256_file(path)
        if observed != expected_hash:
            raise JoinError(
                f"frozen artifact hash changed for {path}: "
                f"expected {expected_hash}, got {observed}"
            )
    semantic = json.loads(
        (v2 / "audits/authority_semantic_audit.json").read_text(encoding="utf-8")
    )
    if (
        semantic.get("status") != "PASS"
        or semantic.get("FSU_to_Holmes", {}).get("status") != "PASS"
        or semantic.get("R9_to_R12", {}).get("status") != "PASS"
    ):
        raise JoinError("accepted v2 semantic audit is not a full PASS")
    return contract


def source_paths_and_hashes(
    contract: Mapping[str, Any],
) -> tuple[dict[str, Path], dict[str, str], Mapping[str, Any]]:
    v1_root = Path(contract["roots"]["sealed_v1"])
    v2_root = Path(contract["roots"]["sealed_v2"])
    v1_manifest = json.loads(
        (v1_root / "tier_f_acquisition_manifest.json").read_text(encoding="utf-8")
    )
    records = v1_payload_records(v1_manifest)
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for product in ("mrg01", "AOP", "FSU", "SP2", "AMS"):
        filename = PRODUCT_FILENAMES[product]
        item = records.get(filename)
        if item is None:
            raise JoinError(f"sealed v1 manifest lacks {filename}")
        path = v1_root / str(item["raw_relative_path"])
        paths[product] = path
        hashes[product] = str(item["sha256"])
    paths["R9"] = v2_root / "raw" / PRODUCT_FILENAMES["R9"]
    paths["R12"] = v2_root / "raw" / PRODUCT_FILENAMES["R12"]
    hashes["R9"] = (
        "6f65a48c88f94336e31db114803fa81587a3789504e20fea72e1ea21b23a40f9"
    )
    hashes["R12"] = (
        "4ab01547551d6ba9dc22feed3bbea4ffec58727c50f6ee92774320149c87815b"
    )
    for product, path in paths.items():
        if not path.is_file() or sha256_file(path) != hashes[product]:
            raise JoinError(f"{product} frozen payload is absent or changed")
    return paths, hashes, v1_manifest


def r12_source_records(
    path: Path, payload_hash: str
) -> tuple[dict[str, Any], tuple[SourceRecord, ...], list[dict[str, Any]]]:
    payload = path.read_bytes()
    audit, rows = audit_r12(payload)
    records: list[SourceRecord] = []
    for item in rows:
        worksheet_row = int(item["worksheet_row"])
        start = Decimal(int(item["start"]))
        stop = Decimal(int(item["end"]) + 1)
        raw = canonical_json_bytes(item)
        values = {key: "" if value is None else str(value) for key, value in item.items()}
        records.append(
            SourceRecord(
                product="R12",
                source_id=f"{payload_hash}:worksheet-row-{worksheet_row}",
                ordinal=worksheet_row,
                start=start,
                stop=stop,
                raw_line=raw,
                values=values,
                worksheet_row=worksheet_row,
            )
        )
    return audit, tuple(records), rows


def overlaps(left: SourceRecord, right: SourceRecord) -> bool:
    return left.start < right.stop and right.start < left.stop


def overlap_bounds(
    carrier: SourceRecord, source: SourceRecord
) -> tuple[Decimal, Decimal, Decimal]:
    start = max(carrier.start, source.start)
    stop = min(carrier.stop, source.stop)
    duration = stop - start
    if duration <= 0:
        raise JoinError("non-positive overlap reached the link writer")
    return start, stop, duration


def format_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def temporal_links(
    carriers: Sequence[SourceRecord],
    sources: Sequence[SourceRecord],
) -> dict[str, list[SourceRecord]]:
    result = {carrier.source_id: [] for carrier in carriers}
    source_index = 0
    active: list[SourceRecord] = []
    ordered = sorted(sources, key=lambda item: (item.start, item.stop, item.ordinal))
    for carrier in carriers:
        active = [source for source in active if source.stop > carrier.start]
        while source_index < len(ordered) and ordered[source_index].start < carrier.stop:
            candidate = ordered[source_index]
            if candidate.stop > carrier.start:
                active.append(candidate)
            source_index += 1
        matches = [source for source in active if overlaps(carrier, source)]
        result[carrier.source_id] = sorted(matches, key=lambda item: item.ordinal)
    return result


def sentinel_counts(source: IcarttSource) -> dict[str, int]:
    counts = {"missing": 0, "ULOD": 0, "LLOD": 0}
    for record in source.records:
        for field, value in record.values.items():
            number = value.strip()
            declared_missing = source.missing_values.get(field)
            if declared_missing is not None and exact_decimal(
                number, f"{source.product} {field}"
            ) == exact_decimal(
                declared_missing,
                f"{source.product} declared missing value for {field}",
            ):
                counts["missing"] += 1
            elif exact_decimal(number, f"{source.product} {field}") == Decimal(
                "-7777"
            ):
                counts["ULOD"] += 1
            elif exact_decimal(number, f"{source.product} {field}") == Decimal(
                "-8888"
            ):
                counts["LLOD"] += 1
    return counts


def carrier_records(path: Path, expected_hash: str) -> IcarttSource:
    observed_sha256 = sha256_file(path)
    if observed_sha256 != expected_hash:
        raise JoinError(
            f"mrg01 payload hash changed: expected {expected_hash}, "
            f"got {observed_sha256}"
        )
    header_lines, fields, missing_values, rows = iter_icartt_rows(path)
    if len(missing_values) != len(fields) - 1:
        raise JoinError(
            "mrg01 lacks a complete ICARTT missing-value declaration"
        )
    indices = {
        field: _field_lookup(fields, field) for field in NAVIGATION_FIELDS
    }
    records: list[SourceRecord] = []
    for ordinal, raw, tokens in rows:
        values = {field: tokens[index] for field, index in indices.items()}
        start = exact_decimal(values["Time_Start"], f"mrg01 Time_Start {ordinal}")
        stop = exact_decimal(values["Time_Stop"], f"mrg01 Time_Stop {ordinal}")
        if stop <= start:
            raise JoinError(
                f"mrg01 record {ordinal} has non-positive interval "
                f"[{start}, {stop})"
            )
        records.append(
            SourceRecord(
                product="mrg01",
                source_id=record_id(observed_sha256, ordinal),
                ordinal=ordinal,
                start=start,
                stop=stop,
                raw_line=raw,
                values=values,
            )
        )
    return IcarttSource(
        product="mrg01",
        path=path,
        payload_sha256=observed_sha256,
        header_lines=header_lines,
        fields=tuple(NAVIGATION_FIELDS),
        missing_values={
            field: missing_values[field]
            for field in NAVIGATION_FIELDS
            if field in missing_values
        },
        records=tuple(records),
    )


def selected_value(record: SourceRecord, field: str) -> str:
    matches = [
        value
        for key, value in record.values.items()
        if key.casefold() == field.casefold()
    ]
    if len(matches) != 1:
        raise JoinError(
            f"{record.product} record {record.ordinal} lacks unique field {field}"
        )
    return matches[0]


def write_source_inventory(
    path: Path,
    products: Mapping[str, Sequence[SourceRecord]],
    payload_hashes: Mapping[str, str],
) -> int:
    fields = (
        "product",
        "payload_sha256",
        "source_record_id",
        "data_record_ordinal",
        "worksheet_row",
        "time_start_raw",
        "time_stop_raw",
        "raw_record_bytes",
        "raw_record_sha256",
    )
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for product in ("mrg01", "R9", "R12", "AOP", "FSU", "SP2", "AMS"):
            for record in products[product]:
                writer.writerow(
                    {
                        "product": product,
                        "payload_sha256": payload_hashes[product],
                        "source_record_id": record.source_id,
                        "data_record_ordinal": (
                            "" if record.worksheet_row is not None else record.ordinal
                        ),
                        "worksheet_row": record.worksheet_row or "",
                        "time_start_raw": format_decimal(record.start),
                        "time_stop_raw": format_decimal(record.stop),
                        "raw_record_bytes": len(record.raw_line),
                        "raw_record_sha256": record.raw_sha256,
                    }
                )
                count += 1
    return count


def write_links(
    path: Path,
    carriers: Sequence[SourceRecord],
    links: Mapping[str, Mapping[str, Sequence[SourceRecord]]],
) -> tuple[int, dict[str, int], dict[str, int]]:
    fields = (
        "carrier_source_record_id",
        "carrier_ordinal",
        "carrier_time_start",
        "carrier_time_stop",
        "product",
        "source_record_id",
        "source_ordinal",
        "source_worksheet_row",
        "source_time_start",
        "source_time_stop",
        "overlap_start",
        "overlap_stop",
        "overlap_seconds",
    )
    counts = {product: 0 for product in LINK_PRODUCTS}
    unique = {product: set() for product in LINK_PRODUCTS}
    total = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for carrier in carriers:
            for product in LINK_PRODUCTS:
                for source in links[carrier.source_id][product]:
                    start, stop, duration = overlap_bounds(carrier, source)
                    writer.writerow(
                        {
                            "carrier_source_record_id": carrier.source_id,
                            "carrier_ordinal": carrier.ordinal,
                            "carrier_time_start": format_decimal(carrier.start),
                            "carrier_time_stop": format_decimal(carrier.stop),
                            "product": product,
                            "source_record_id": source.source_id,
                            "source_ordinal": (
                                "" if source.worksheet_row is not None else source.ordinal
                            ),
                            "source_worksheet_row": source.worksheet_row or "",
                            "source_time_start": format_decimal(source.start),
                            "source_time_stop": format_decimal(source.stop),
                            "overlap_start": format_decimal(start),
                            "overlap_stop": format_decimal(stop),
                            "overlap_seconds": format_decimal(duration),
                        }
                    )
                    counts[product] += 1
                    unique[product].add(source.source_id)
                    total += 1
    return total, counts, {key: len(value) for key, value in unique.items()}


def prefixed_fields(prefix: str, fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"{prefix}__{field}" for field in fields)


def write_carrier_join(
    path: Path,
    carriers: Sequence[SourceRecord],
    sources: Mapping[str, IcarttSource],
    links: Mapping[str, Mapping[str, Sequence[SourceRecord]]],
) -> int:
    r9_fields = sources["R9"].fields
    aop_fields = sources["AOP"].fields
    fsu_fields = sources["FSU"].fields
    sp2_fields = sources["SP2"].fields
    base_fields = (
        "carrier_source_record_id",
        "carrier_ordinal",
        "carrier_raw_record_bytes",
        "carrier_raw_record_sha256",
        *NAVIGATION_FIELDS,
        "raw_lane_joined",
        "non_age_lane_joined",
        "nominal_age_lane_joined",
        "age_uncertainty_lane_joined",
    )
    r12_fields = (
        "r12__source_record_id",
        "r12__worksheet_row",
        "r12__fire_name",
        "r12__fire_id_raw",
        "r12__fire_id",
        "r12__start_raw",
        "r12__end_raw",
        "r12__transect_type_raw",
        "r12__transect_number_raw",
        "r12__transect_number",
        "r12__plume_id_raw",
        "r12__plume_id",
        "r12__mean_wind_age_raw",
    )
    tail_fields = (
        "ams__source_record_count",
        "ams__source_record_ids",
        "ams__overlap_seconds",
    )
    fieldnames = (
        *base_fields,
        *prefixed_fields("r9", r9_fields),
        "r9__source_record_id",
        *r12_fields,
        *prefixed_fields("aop", aop_fields),
        "aop__source_record_id",
        *prefixed_fields("fsu", fsu_fields),
        "fsu__source_record_id",
        *prefixed_fields("sp2", sp2_fields),
        "sp2__source_record_id",
        *tail_fields,
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for carrier in carriers:
            per_product = links[carrier.source_id]
            exact: dict[str, SourceRecord] = {}
            for product in EXACT_ONE_SECOND_PRODUCTS:
                matches = per_product[product]
                if len(matches) != 1:
                    raise JoinError(
                        f"carrier {carrier.ordinal} has {len(matches)} {product} "
                        "records; exact one-second mapping requires one"
                    )
                exact[product] = matches[0]
            r12_matches = per_product["R12"]
            if len(r12_matches) > 1:
                raise JoinError(f"carrier {carrier.ordinal} maps to multiple R12 rows")
            row: dict[str, Any] = {
                "carrier_source_record_id": carrier.source_id,
                "carrier_ordinal": carrier.ordinal,
                "carrier_raw_record_bytes": len(carrier.raw_line),
                "carrier_raw_record_sha256": carrier.raw_sha256,
                "raw_lane_joined": "True",
                "non_age_lane_joined": "True",
                "nominal_age_lane_joined": "True",
                "age_uncertainty_lane_joined": "True",
            }
            for field in NAVIGATION_FIELDS:
                row[field] = selected_value(carrier, field)
            for product, prefix in (
                ("R9", "r9"),
                ("AOP", "aop"),
                ("FSU", "fsu"),
                ("SP2", "sp2"),
            ):
                source = exact[product]
                for field, value in source.values.items():
                    row[f"{prefix}__{field}"] = value
                row[f"{prefix}__source_record_id"] = source.source_id
            if r12_matches:
                source = r12_matches[0]
                row.update(
                    {
                        "r12__source_record_id": source.source_id,
                        "r12__worksheet_row": source.worksheet_row,
                        "r12__fire_name": source.values["fire_name"],
                        "r12__fire_id_raw": source.values["fire_id_raw"],
                        "r12__fire_id": source.values["fire_id"],
                        "r12__start_raw": source.values["start_raw"],
                        "r12__end_raw": source.values["end_raw"],
                        "r12__transect_type_raw": source.values["transect_type_raw"],
                        "r12__transect_number_raw": source.values[
                            "transect_number_raw"
                        ],
                        "r12__transect_number": source.values["transect_number"],
                        "r12__plume_id_raw": source.values["plume_id_raw"],
                        "r12__plume_id": source.values["plume_id"],
                        "r12__mean_wind_age_raw": source.values[
                            "mean_wind_age_raw"
                        ],
                    }
                )
            ams = per_product["AMS"]
            row["ams__source_record_count"] = len(ams)
            row["ams__source_record_ids"] = ";".join(item.source_id for item in ams)
            row["ams__overlap_seconds"] = ";".join(
                format_decimal(overlap_bounds(carrier, item)[2]) for item in ams
            )
            writer.writerow(row)
    return len(carriers)


def validate_r12_links(
    carriers: Sequence[SourceRecord],
    links: Mapping[str, Mapping[str, Sequence[SourceRecord]]],
) -> dict[str, Any]:
    mapped_carriers = 0
    lexical_mismatches: list[dict[str, Any]] = []
    mapped_rows: set[int] = set()
    for carrier in carriers:
        r9 = links[carrier.source_id]["R9"][0]
        r12 = links[carrier.source_id]["R12"]
        smoke = exact_decimal(
            selected_value(r9, "smoke_flag"), "R9 smoke_flag"
        ) == 1
        if smoke != bool(r12):
            raise JoinError(
                f"carrier {carrier.ordinal}: R9 smoke/R12 interval presence differs"
            )
        if not r12:
            continue
        mapped_carriers += 1
        row = r12[0]
        mapped_rows.add(int(row.worksheet_row or -1))
        comparisons = (
            ("fire_id", "fire_id"),
            ("transect_number", "transect_number"),
            ("transect_plume_number", "plume_id"),
        )
        for r9_field, r12_field in comparisons:
            direct = selected_value(r9, r9_field).strip()
            authority = row.values[r12_field].strip()
            try:
                direct_decimal = exact_decimal(direct, r9_field).normalize()
                authority_decimal = exact_decimal(authority, r12_field).normalize()
            except JoinError:
                equal = direct == authority
            else:
                equal = direct_decimal == authority_decimal
            if not equal:
                lexical_mismatches.append(
                    {
                        "carrier_ordinal": carrier.ordinal,
                        "field": r9_field,
                        "R9": direct,
                        "R12": authority,
                    }
                )
    if lexical_mismatches:
        raise JoinError(f"R9/R12 identifier mismatches: {lexical_mismatches[:10]}")
    return {
        "status": "PASS",
        "mapped_carrier_records": mapped_carriers,
        "mapped_R12_records": len(mapped_rows),
        "lexical_identifier_mismatch_count": 0,
    }


def validate_expected(
    contract: Mapping[str, Any],
    products: Mapping[str, Sequence[SourceRecord]],
    link_counts: Mapping[str, int],
    unique_linked: Mapping[str, int],
) -> dict[str, Any]:
    expected = contract["expected"]
    key_map = {
        "mrg01": "carrier_records",
        "R9": "r9_records",
        "AOP": "aop_records",
        "FSU": "fsu_records",
        "SP2": "sp2_records",
        "AMS": "ams_records",
        "R12": "r12_august6_records",
    }
    observed_counts = {product: len(records) for product, records in products.items()}
    for product, key in key_map.items():
        if observed_counts[product] != int(expected[key]):
            raise JoinError(
                f"{product} record count changed: expected {expected[key]}, "
                f"got {observed_counts[product]}"
            )
    carriers = products["mrg01"]
    if (
        int(carriers[0].start) != int(expected["carrier_first_time"])
        or int(carriers[-1].start) != int(expected["carrier_last_time"])
    ):
        raise JoinError("carrier endpoint times changed")
    carrier_count = len(carriers)
    for product in EXACT_ONE_SECOND_PRODUCTS:
        if link_counts[product] != carrier_count or unique_linked[product] != carrier_count:
            raise JoinError(
                f"{product} exact mapping changed: links={link_counts[product]}, "
                f"unique={unique_linked[product]}, carriers={carrier_count}"
            )
    if link_counts["R12"] != 5253 or unique_linked["R12"] != 25:
        raise JoinError("R12 interval mapping no longer gives 5253 carrier/25 source rows")
    if unique_linked["AMS"] != len(products["AMS"]):
        raise JoinError("at least one AMS source record was not linked to the carrier")
    return {
        "status": "PASS",
        "record_counts": observed_counts,
        "link_counts": dict(link_counts),
        "unique_linked_source_records": dict(unique_linked),
    }


def artifact_inventory(output_dir: Path, names: Iterable[str]) -> list[dict[str, Any]]:
    result = []
    for name in sorted(names):
        path = output_dir / name
        result.append(
            {
                "relative_path": name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return result


def build_join(contract_path: Path, output_dir: Path, command: Sequence[str]) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    output_dir = output_dir.resolve()
    contract = verify_contract_and_roots(contract_path)
    if output_dir.exists():
        raise JoinError(f"refusing to overwrite existing output root: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)

    paths, payload_hashes, v1_manifest = source_paths_and_hashes(contract)
    v1_root = Path(contract["roots"]["sealed_v1"])
    v2_root = Path(contract["roots"]["sealed_v2"])

    try:
        sources = {
            "R9": load_icartt_source(
                "R9", paths["R9"], expected_sha256=payload_hashes["R9"],
                explicit_stop=False,
            ),
            "AOP": load_icartt_source(
                "AOP", paths["AOP"], expected_sha256=payload_hashes["AOP"],
                explicit_stop=False,
            ),
            "FSU": load_icartt_source(
                "FSU", paths["FSU"], expected_sha256=payload_hashes["FSU"],
                explicit_stop=False,
            ),
            "SP2": load_icartt_source(
                "SP2", paths["SP2"], expected_sha256=payload_hashes["SP2"],
                explicit_stop=False,
            ),
            "AMS": load_icartt_source(
                "AMS", paths["AMS"], expected_sha256=payload_hashes["AMS"],
                explicit_stop=True,
            ),
        }
        carriers_source = carrier_records(paths["mrg01"], payload_hashes["mrg01"])
        r12_audit, r12_records, r12_rows = r12_source_records(
            paths["R12"], payload_hashes["R12"]
        )

        r9_payload = paths["R9"].read_bytes()
        r9_audit, r9_records_for_audit, r9_intervals = audit_r9(r9_payload)
        mirror_audit = audit_r9_mrg01_mirrors(
            r9_records_for_audit,
            v1_root=v1_root,
            v1_manifest=v1_manifest,
        )
        interval_audit = compare_r9_r12_intervals(r9_intervals, r12_rows)
        if any(
            result.get("status") != "PASS"
            for result in (r9_audit, r12_audit, interval_audit)
        ) or mirror_audit.get("status") != "PASS":
            raise JoinError("independent authority/protected-field audit did not pass")

        products: dict[str, Sequence[SourceRecord]] = {
            "mrg01": carriers_source.records,
            "R9": sources["R9"].records,
            "R12": r12_records,
            "AOP": sources["AOP"].records,
            "FSU": sources["FSU"].records,
            "SP2": sources["SP2"].records,
            "AMS": sources["AMS"].records,
        }
        links: dict[str, dict[str, Sequence[SourceRecord]]] = {
            carrier.source_id: {} for carrier in carriers_source.records
        }
        for product in LINK_PRODUCTS:
            linked = temporal_links(carriers_source.records, products[product])
            for carrier in carriers_source.records:
                links[carrier.source_id][product] = linked[carrier.source_id]

        inventory_count = write_source_inventory(
            output_dir / SOURCE_INVENTORY_NAME, products, payload_hashes
        )
        total_links, link_counts, unique_linked = write_links(
            output_dir / LINKS_NAME, carriers_source.records, links
        )
        joined_rows = write_carrier_join(
            output_dir / JOIN_NAME, carriers_source.records, sources, links
        )
        expected_audit = validate_expected(
            contract, products, link_counts, unique_linked
        )
        r12_link_audit = validate_r12_links(carriers_source.records, links)
        validation = {
            "status": "PASS",
            "scope": "Phase-2-source-record-preserving-join-only",
            "contract_id": contract["id"],
            "mapping": contract["mapping"],
            "expected": expected_audit,
            "source_inventory_records": inventory_count,
            "carrier_source_links": total_links,
            "carrier_join_rows": joined_rows,
            "protected_carrier": {
                "status": "PASS",
                "payload_sha256": payload_hashes["mrg01"],
                "raw_record_hashes_recorded": joined_rows,
                "R9_mirror_audit": mirror_audit["status"],
                "unexplained_R9_mirror_mismatches": 0,
            },
            "R9_R12": r12_link_audit,
            "sentinel_token_counts": {
                product: sentinel_counts(source)
                for product, source in sorted(sources.items())
            },
            "lanes": {
                "raw_source_record_preserving": "PASS",
                "non_age": "PASS",
                "nominal_age": "PASS",
                "C_age_uncertainty": "PASS",
            },
            "stopped_before": contract["stops_before"],
        }
        write_json(output_dir / VALIDATION_NAME, validation)

        run_manifest = {
            "schema_version": 1,
            "id": contract["id"],
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "PASS",
            "scope": contract["scope"],
            "command": list(command),
            "working_directory": str(Path.cwd()),
            "output_root": str(output_dir),
            "python": {
                "executable": sys.executable,
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
                "required_argon_path_present": Path(
                    contract["python"]["required_argon_path"]
                ).exists(),
                "euler_exception": contract["python"]["exception_reason"],
            },
            "contract": {
                "path": str(contract_path),
                "sha256": sha256_file(contract_path),
            },
            "implementation": {
                "path": str(SCRIPT_PATH),
                "sha256": sha256_file(SCRIPT_PATH),
            },
            "inputs": [
                {
                    "product": product,
                    "path": str(paths[product]),
                    "bytes": paths[product].stat().st_size,
                    "sha256": payload_hashes[product],
                }
                for product in ("mrg01", "R9", "R12", "AOP", "FSU", "SP2", "AMS")
            ],
            "frozen_roots": {
                "v1": str(v1_root),
                "v2": str(v2_root),
                "modified": False,
            },
            "mapping": contract["mapping"],
            "validation": validation,
        }
        write_json(output_dir / RUN_MANIFEST_NAME, run_manifest)

        artifact_names = (
            SOURCE_INVENTORY_NAME,
            LINKS_NAME,
            JOIN_NAME,
            VALIDATION_NAME,
            RUN_MANIFEST_NAME,
        )
        artifacts = artifact_inventory(output_dir, artifact_names)
        artifact_manifest = {
            "schema_version": 1,
            "id": contract["id"],
            "status": "PASS",
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "input_payloads_modified": False,
        }
        write_json(output_dir / ARTIFACT_MANIFEST_NAME, artifact_manifest)
        seal = {
            "schema_version": 1,
            "id": contract["id"],
            "status": "SEALED-PASS",
            "sealed_utc": datetime.now(timezone.utc).isoformat(),
            "artifact_manifest_sha256": sha256_file(
                output_dir / ARTIFACT_MANIFEST_NAME
            ),
            "run_manifest_sha256": sha256_file(output_dir / RUN_MANIFEST_NAME),
            "validation_sha256": sha256_file(output_dir / VALIDATION_NAME),
            "input_payloads_modified": False,
            "later_phases_released": False,
        }
        write_json(output_dir / SEAL_NAME, seal)
        return {
            "status": "SEALED-PASS",
            "output_root": str(output_dir),
            "carrier_rows": joined_rows,
            "links": total_links,
            "artifact_manifest_sha256": seal["artifact_manifest_sha256"],
            "seal_sha256": sha256_file(output_dir / SEAL_NAME),
        }
    except Exception as error:
        failure = {
            "status": "FAILED-CLOSED",
            "error_type": type(error).__name__,
            "error": str(error),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "seal_written": False,
        }
        write_json(output_dir / "FAILED_CLOSED.json", failure)
        raise


def compare_reproductions(primary: Path, reproduction: Path) -> dict[str, Any]:
    required = (SOURCE_INVENTORY_NAME, LINKS_NAME, JOIN_NAME, VALIDATION_NAME)
    comparisons = []
    for name in required:
        left = primary / name
        right = reproduction / name
        if not left.is_file() or not right.is_file():
            raise JoinError(f"reproduction comparison is missing {name}")
        left_hash = sha256_file(left)
        right_hash = sha256_file(right)
        comparisons.append(
            {
                "relative_path": name,
                "primary_sha256": left_hash,
                "reproduction_sha256": right_hash,
                "identical": left_hash == right_hash,
            }
        )
    if not all(item["identical"] for item in comparisons):
        raise JoinError("primary/reproduction deterministic artifacts differ")
    return {"status": "PASS", "comparisons": comparisons}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compare-primary", type=Path)
    parser.add_argument("--compare-reproduction", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    args = parser.parse_args(argv)
    build_mode = args.output_dir is not None
    compare_mode = (
        args.compare_primary is not None
        or args.compare_reproduction is not None
        or args.comparison_output is not None
    )
    if build_mode == compare_mode:
        parser.error(
            "choose either --output-dir or the complete reproduction-comparison set"
        )
    if compare_mode and not all(
        value is not None
        for value in (
            args.compare_primary,
            args.compare_reproduction,
            args.comparison_output,
        )
    ):
        parser.error("reproduction comparison requires all three comparison options")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output_dir is not None:
        result = build_join(
            args.contract,
            args.output_dir,
            [sys.executable, str(SCRIPT_PATH), *(sys.argv[1:] if argv is None else argv)],
        )
    else:
        assert args.compare_primary is not None
        assert args.compare_reproduction is not None
        assert args.comparison_output is not None
        result = compare_reproductions(
            args.compare_primary.resolve(), args.compare_reproduction.resolve()
        )
        output = args.comparison_output.resolve()
        if output.exists():
            raise JoinError(f"refusing to overwrite comparison output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        write_json(output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (JoinError, AcquisitionError) as error:
        print(f"FAILED-CLOSED: {error}", file=sys.stderr)
        raise SystemExit(2) from error
