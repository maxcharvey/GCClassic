#!/usr/bin/env python3
"""Download official native GFAS daily files into a new private input directory.

Includes the following month's first day for end-boundary interpolation.
Never overwrites existing inputs. Full numeric QC must run on a compute node.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request


BASE = 'https://geos-chem.s3-us-west-2.amazonaws.com/HEMCO/GFAS/v2026-06'


def fetch(day, root):
    relative = f'{day:%Y/%m}/GFAS-smoke-{day:%Y%m%d}.nc'
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    url = BASE + '/' + relative
    partial = target.with_suffix('.nc.partial')
    if target.exists() or partial.exists():
        raise FileExistsError(target)
    with urllib.request.urlopen(url, timeout=90) as response:
        length = int(response.headers['Content-Length'])
        etag = response.headers.get('ETag')
        with partial.open('xb') as stream:
            shutil.copyfileobj(response, stream)
    if partial.stat().st_size != length:
        raise ValueError(f'Truncated download: {partial}')
    with partial.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    partial.rename(target)
    return {'date': day.isoformat(), 'url': url, 'path': str(target.resolve()),
            'bytes': length, 'etag': etag, 'sha256': digest,
            'numeric_qc': 'PENDING compute-node audit_gfas_input.py'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('year', type=int)
    parser.add_argument('month', type=int)
    parser.add_argument('new_directory', type=Path)
    args = parser.parse_args()
    day = date(args.year, args.month, 1)
    days = [day]
    while True:
        day += timedelta(days=1)
        days.append(day)
        if day.month != args.month:
            break
    args.new_directory.mkdir(parents=True, exist_ok=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(lambda d: fetch(d, args.new_directory), days))
    record = {'product': 'GEOS-Chem GFAS v2026-06 official native 3D product',
              'retrieved_utc': datetime.now(timezone.utc).isoformat(),
              'source_base': BASE, 'transformation': 'none', 'files': files}
    (args.new_directory / 'download_manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'files': len(files), 'bytes': sum(f['bytes'] for f in files),
                      'directory': str(args.new_directory.resolve())}))


if __name__ == '__main__':
    main()
