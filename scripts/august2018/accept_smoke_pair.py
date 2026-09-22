"""Freeze smoke acceptance only after independent review of these exact reports."""
from pathlib import Path
import argparse
import datetime
import json
from workflow_common import ROOT, CASES, DATES, FREEZE, ACCEPTANCE, require, sha, load, write_new, verify_hashes


def accept(independent, root=ROOT):
    require(not (root / ACCEPTANCE).exists(), 'Acceptance already exists')
    freeze = load(root / FREEZE)
    verdict = load(independent)
    require(verdict['status'] == 'PASS' and verdict['scope'] == 'final_harmonized_smoke_pair', 'Independent gate failed')
    require(independent.parent.resolve() == root, 'Independent report must be inside staging root')
    reports = {independent.name: sha(independent)}
    for version, case in zip(('147', '148'), CASES):
        p = root / f'audit_{version}_smoke.json'
        d = load(p)
        require(d['status'] == 'PASS', f'Smoke failed: {version}')
        require(verdict['main_reports_sha256'][p.name] == sha(p), 'Stale independent verdict')
        info = freeze['cases'][case]
        require(d['case'] == case + '_SMOKE1H_20260922', 'Wrong smoke case')
        require(d['configuration_sha256'] == info['configs'][d['case']], 'Stale smoke configuration')
        verify_hashes(root / d['case'], d['configuration_sha256'])
        require(d['audit_script_sha256'] == sha(root / 'audit_restart_smoke.py'), 'Stale audit script')
        verify_hashes(root / d['case'], d['output_sha256'])
        reports[p.name] = sha(p)
        prepath = root / f'preflight_{version}_month.json'
        pre = load(prepath)
        require(pre['status'] == 'PASS' and pre['case'] == case, 'Month preflight failed')
        require(pre['freeze_sha256'] == sha(root / FREEZE) and pre['configuration_sha256'] == info['configs'][case], 'Stale month preflight')
        verify_hashes(root / case, pre['configuration_sha256'])
        reports[prepath.name] = sha(prepath)
    tools = load(root / 'WORKFLOW_TOOLS.json')['sha256']
    verify_hashes(root, tools)
    files = list(tools) + ['WORKFLOW_TOOLS.json', FREEZE, 'OPTICAL_INPUT_FREEZE_20260922.json', 'inputs/GFAS/v2026-06/download_manifest.json']
    for case in CASES:
        schedules = sorted((root / case).glob('Planeflight.dat.*'))
        require({p.name for p in schedules} == {'Planeflight.dat.' + d for d in DATES}, 'Wrong schedule dates')
        files.extend(str(p.relative_to(root)) for p in schedules)
    result = {'status': 'PASS', 'independent_auditor': 'PASS', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'reports_sha256': reports, 'tools_and_inputs_sha256': {n: sha(root / n) for n in files}, 'scope': 'One-hour engineering/restart gate only; version/injection confounded; organic-equivalent optics not science-qualified.'}
    write_new(root / ACCEPTANCE, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('independent_report', type=Path)
    args = parser.parse_args()
    print(json.dumps(accept((ROOT / args.independent_report).resolve()), indent=2))


if __name__ == '__main__':
    main()
