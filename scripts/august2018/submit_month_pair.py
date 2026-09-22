"""Explicitly submit the accepted pair once; persist partial submission evidence."""
from pathlib import Path
import argparse
import datetime
import getpass
import json
import os
import subprocess
from workflow_common import ROOT, CASES, require, write_new, verify_acceptance


def submit(root=ROOT, partition=None, account=None, legacy_hours=240, native_hours=192):
    require(legacy_hours > 0 and native_hours > 0, 'Wall limits must be positive')
    record = root / 'MONTH_SUBMISSION_20260922.json'
    require(not record.exists(), 'Submission record exists; inspect it rather than resubmit')
    verify_acceptance(root)
    queue = subprocess.check_output(['squeue', '-h', '-u', getpass.getuser(), '-o', '%j'], text=True)
    names = ['BRC147_AUG2018', 'BRC148_AUG2018', 'BRC_AUG_ANALYSIS']
    require(not any(n in queue.splitlines() for n in names), 'Duplicate job in queue')
    data = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'status': 'SUBMITTING', 'jobs': {}, 'resources': {'cpus_per_task': 16, 'memory_gib': 96, 'legacy_wall_hours': legacy_hours, 'native_wall_hours': native_hours}, 'claim': 'Submitted jobs are not completed results.'}
    # Exclusive creation also prevents two simultaneous submitters.
    write_new(record, data)
    env = dict(os.environ, BRC_AUGUST_ROOT=str(root.resolve()))
    extra = ([f'--partition={partition}'] if partition else []) + ([f'--account={account}'] if account else [])

    def save():
        tmp = record.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data, indent=2) + '\n')
        tmp.replace(record)

    def launch(label, args):
        command = ['sbatch', '--parsable', *extra, *args]
        try:
            result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True)
            require(result.returncode == 0, result.stderr or result.stdout)
            lines = result.stdout.strip().splitlines()
            job = lines[-1].split(';')[0] if lines else ''
            require(job.isdigit(), f'Unrecognized sbatch response; inspect scheduler before retry: {result.stdout}')
        except Exception as exc:
            data['status'] = 'SUBMISSION_FAILED'
            data['error'] = {'label': label, 'command': command, 'detail': str(exc)}
            save()
            raise
        data['jobs'][label] = {'job_id': job, 'command': command, 'stderr': result.stderr}
        save()
        return job

    ids = []
    for version, case, hours, name in zip(('147', '148'), CASES, (legacy_hours, native_hours), names):
        ids.append(launch(version, [f'--time={hours}:00:00', f'--job-name={name}', f'--output={root}/month_{version}_%j.out', f'--error={root}/month_{version}_%j.err', str(root / 'run_month_case.sh'), case]))
    launch('analysis', [f'--dependency=afterok:{ids[0]}:{ids[1]}', '--kill-on-invalid-dep=yes', f'--job-name={names[2]}', f'--output={root}/analysis_%j.out', f'--error={root}/analysis_%j.err', str(root / 'run_month_analysis.sh')])
    data['status'] = 'SUBMITTED'
    save()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--submit', required=True, action='store_true', help='Explicitly execute sbatch after independent qualification')
    parser.add_argument('--partition')
    parser.add_argument('--account')
    parser.add_argument('--legacy-hours', type=int, default=240)
    parser.add_argument('--native-hours', type=int, default=192)
    args = parser.parse_args()
    print(json.dumps(submit(partition=args.partition, account=args.account, legacy_hours=args.legacy_hours, native_hours=args.native_hours), indent=2))


if __name__ == '__main__':
    main()
