#!/usr/bin/env python3
"""Fetch the authoritative FIREX-AQ DC-8 1 Hz SP2 files from NASA.

The downloader discovers the current archive filenames from the official
FIREX-AQ DC-8 archive page, restricts them to the frozen science-flight dates,
and writes an atomic, hash-sealed source manifest. Existing files are never
overwritten: an existing byte-identical file is reused, while any mismatch
fails closed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any
import urllib.request


ARCHIVE_PAGE = "https://www-air.larc.nasa.gov/cgi-bin/ArcView/firexaq?DC8=1"
ARCHIVE_ORIGIN = "https://www-air.larc.nasa.gov"
EXPECTED_FLIGHT_DATES = [
    "20190722", "20190724", "20190725", "20190729", "20190730",
    "20190802", "20190803", "20190806", "20190807", "20190808",
    "20190812", "20190813", "20190815", "20190816", "20190819",
    "20190821", "20190823", "20190826", "20190829", "20190830",
    "20190831", "20190903", "20190905",
]
SP2_LINK = re.compile(
    r'<a href="([^"]+)">'
    r"(FIREXAQ-SP2-BC-1HZ_DC8_(2019\d{4})_R\d+(?:_L\d+)?\.ict)"
    r"</a>",
    flags=re.IGNORECASE,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_sources(page: str) -> dict[str, dict[str, str]]:
    matches: dict[str, list[dict[str, str]]] = {}
    for href, filename, date in SP2_LINK.findall(page):
        matches.setdefault(date, []).append({
            "filename": filename,
            "url": ARCHIVE_ORIGIN + href,
        })

    selected: dict[str, dict[str, str]] = {}
    for date in EXPECTED_FLIGHT_DATES:
        candidates = matches.get(date, [])
        if len(candidates) != 1:
            names = [item["filename"] for item in candidates]
            raise ValueError(
                f"{date}: expected exactly one SP2 source, found {len(candidates)} "
                f"({names})"
            )
        selected[date] = candidates[0]
    return selected


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gc-plume-transport-firex-aq-provenance/1"},
    )
    with urllib.request.urlopen(request) as response:
        return response.read()


def stage_file(url: str, destination: Path) -> str:
    payload = fetch_bytes(url)
    payload_hash = hashlib.sha256(payload).hexdigest()
    if destination.exists():
        existing_hash = sha256(destination)
        if existing_hash != payload_hash:
            raise FileExistsError(
                f"refusing to overwrite {destination}: existing SHA-256 "
                f"{existing_hash} != archive SHA-256 {payload_hash}"
            )
        return existing_hash

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
    return payload_hash


def build_manifest(output_dir: Path) -> dict[str, Any]:
    page_bytes = fetch_bytes(ARCHIVE_PAGE)
    page = page_bytes.decode("latin1")
    sources = discover_sources(page)
    records = []
    for date in EXPECTED_FLIGHT_DATES:
        source = sources[date]
        destination = output_dir / source["filename"]
        digest = stage_file(source["url"], destination)
        records.append({
            "date": date,
            "filename": source["filename"],
            "url": source["url"],
            "bytes": destination.stat().st_size,
            "sha256": digest,
        })
    return {
        "schema_version": 1,
        "dataset": "FIREXAQ-SP2-BC-1HZ",
        "archive_page": ARCHIVE_PAGE,
        "archive_page_sha256": hashlib.sha256(page_bytes).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "flight_dates": EXPECTED_FLIGHT_DATES,
        "files": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--manifest-name",
        default="firex_aq_sp2_1hz_source_manifest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
