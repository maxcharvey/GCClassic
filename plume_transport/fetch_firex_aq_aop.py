#!/usr/bin/env python3
"""Fetch the final FIREX-AQ DC-8 AOP R2 products from NASA."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request

from fetch_firex_aq_sp2 import (
    ARCHIVE_ORIGIN,
    ARCHIVE_PAGE,
    EXPECTED_FLIGHT_DATES,
    fetch_bytes,
    sha256,
)


AOP_LINK = re.compile(
    r'<a href="([^"]+)">'
    r"(firexaq-AOP-optical_DC8_(2019\d{4})_R2\.ict)"
    r"</a>",
    flags=re.IGNORECASE,
)


def discover_sources(page: str) -> dict[str, dict[str, str]]:
    matches: dict[str, list[dict[str, str]]] = {}
    for href, filename, date in AOP_LINK.findall(page):
        matches.setdefault(date, []).append(
            {"filename": filename, "url": ARCHIVE_ORIGIN + href}
        )
    selected = {}
    for date in EXPECTED_FLIGHT_DATES:
        candidates = matches.get(date, [])
        if len(candidates) != 1:
            raise ValueError(
                f"{date}: expected one AOP R2 source, found {len(candidates)}"
            )
        selected[date] = candidates[0]
    return selected


def stage_file(url: str, destination: Path) -> str:
    payload = fetch_bytes(url)
    digest = hashlib.sha256(payload).hexdigest()
    if destination.exists():
        existing = sha256(destination)
        if existing != digest:
            raise FileExistsError(
                f"refusing to overwrite {destination}: {existing} != {digest}"
            )
        return existing
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".part",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
    temporary.replace(destination)
    return digest


def build_manifest(output_dir: Path) -> dict:
    page_bytes = fetch_bytes(ARCHIVE_PAGE)
    sources = discover_sources(page_bytes.decode("latin1"))
    records = []
    for date in EXPECTED_FLIGHT_DATES:
        source = sources[date]
        destination = output_dir / source["filename"]
        digest = stage_file(source["url"], destination)
        records.append(
            {
                "date": date,
                "filename": source["filename"],
                "url": source["url"],
                "bytes": destination.stat().st_size,
                "sha256": digest,
            }
        )
    return {
        "schema_version": 1,
        "dataset": "firexaq-AOP-optical R2",
        "archive_page": ARCHIVE_PAGE,
        "archive_page_sha256": hashlib.sha256(page_bytes).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "flight_dates": EXPECTED_FLIGHT_DATES,
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--manifest-name", default="firex_aq_aop_r2_source_manifest.json"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / args.manifest_name
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite {manifest_path}")
    manifest = build_manifest(args.output_dir)
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
