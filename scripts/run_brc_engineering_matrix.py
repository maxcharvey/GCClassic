#!/usr/bin/env python3
"""Execute an independently approved issue matrix on an allocated compute host."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess

from prepare_brc_engineering_matrix import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    host = socket.gethostname()
    if 'login' in host or not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('An allocated compute host with SLURM_JOB_ID is required')
    if not (root / 'PREFLIGHT.md').is_file():
        raise RuntimeError('Independent preflight approval is required')
    manifest = json.loads((root / 'matrix_manifest.json').read_text())
    env = dict(os.environ, OMP_NUM_THREADS='8', OMP_STACKSIZE='500M')
    for entry in manifest['cases']:
        run = root / entry['run_id']
        if (run / 'GC.log').exists() or any((run / 'OutputDir').iterdir()):
            raise RuntimeError(f'Refusing to rerun existing output: {run}')
        for name, digest in entry['hashes'].items():
            if sha256(run / name) != digest:
                raise RuntimeError(f'Preflight input changed: {run / name}')
        if sha256(run / manifest['restart_path']) != manifest['restart_sha256']:
            raise RuntimeError(f'Preflight restart changed: {run.name}')
        start = datetime.now(timezone.utc).isoformat()
        print(f'{start} START {run.name}', flush=True)
        with (run / 'dryrun.log').open('x') as log:
            dry = subprocess.run(['./gcclassic', '--dry-run'], cwd=run, env=env,
                                 stdout=log, stderr=subprocess.STDOUT)
        if dry.returncode:
            raise RuntimeError(f'Dry-run failed for {run.name}: {dry.returncode}')
        with (run / 'GC.log').open('x') as log:
            result = subprocess.run(['./gcclassic'], cwd=run, env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
        (run / 'GC.exitcode').write_text(str(result.returncode) + '\n')
        (run / 'execution.json').write_text(json.dumps({
            'start_utc': start, 'end_utc': datetime.now(timezone.utc).isoformat(),
            'host': host, 'job_id': os.environ['SLURM_JOB_ID'],
            'exitcode': result.returncode, 'executable_sha256': sha256(run / 'gcclassic')
        }, indent=2) + '\n')
        print(f'END {run.name} exit={result.returncode}', flush=True)
        if result.returncode:
            raise RuntimeError(f'Model failed for {run.name}')


if __name__ == '__main__':
    main()
