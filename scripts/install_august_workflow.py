#!/usr/bin/env python3
"""Install a versioned August 2018 workflow into an unused staging directory.

Never run this against active/frozen runs. Dates, case names and scientific
allowlists deliberately belong to this campaign; paths and scheduler settings
are supplied at deployment. Large model inputs and executables are not copied.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess


def install(root):
    root = root.resolve()
    source = Path(__file__).resolve().parent
    payload = {p.name: p for p in (source / 'august2018').iterdir() if p.suffix in ('.py', '.sh')}
    for name in ('compare_planeflight_profiles.py', 'audit_fire_output.py'):
        payload['analysis_tools/' + name] = source / name
    if (root / 'WORKFLOW_TOOLS.json').exists() or (root / 'RESTART_GATE_FREEZE_20260922.json').exists() or list(root.glob('*/GC.log')):
        raise ValueError('Existing or executed workflow; use a new staging directory')
    for name in payload:
        if (root / name).exists():
            raise ValueError(f'Refusing to overwrite {root / name}')
    root.mkdir(parents=True, exist_ok=True)
    for name, origin in payload.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    head = subprocess.check_output(['git', '-C', str(source.parent), 'rev-parse', 'HEAD'], text=True).strip()
    record = {'schema': 1, 'recipe': 'August 2018 GFAS fixed30/native3D engineering comparison', 'wrapper_checkout_head': head, 'sha256': {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in sorted(payload)}}
    with (root / 'WORKFLOW_TOOLS.json').open('x') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.root), indent=2))


if __name__ == '__main__':
    main()
