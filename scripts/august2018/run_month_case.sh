#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --no-requeue
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=6G
#SBATCH --time=240:00:00
set -euo pipefail
ROOT="${BRC_AUGUST_ROOT:?Set BRC_AUGUST_ROOT to the installed staging root}"
PY="${BRC_PYTHON:-python3}"
CASE="${1:?case required}"
[[ "$CASE" == BRC_147_GFAS_FIXED30_L15_20260921 || "$CASE" == BRC_148_GFAS_NATIVE3D_20260921 ]] || exit 2
[[ -n "${SLURM_JOB_ID:-}" ]] || exit 2
case "$(hostname -s)" in *login*) exit 2;; esac
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-16}"
export OMP_STACKSIZE=512M
ulimit -s unlimited
cd "$ROOT"
"$PY" verify_acceptance.py
"$PY" preflight_restart_gate.py "$CASE" > "$CASE/prelaunch.json"
cd "$CASE"
{ hostname; scontrol show job "$SLURM_JOB_ID"; printf 'OMP_NUM_THREADS=%s\nOMP_STACKSIZE=%s\n' "$OMP_NUM_THREADS" "$OMP_STACKSIZE"; } > allocation.txt
date -u +%FT%TZ > start_utc.txt
printf '%s\n' "$SLURM_JOB_ID" > job_id.txt
set +e
/usr/bin/time -v ./gcclassic > GC.log 2> timing.log
STATUS=$?
set -e
printf '%s\n' "$STATUS" > model_exit_code.txt
date -u +%FT%TZ > end_utc.txt
[[ "$STATUS" == 0 ]] || exit "$STATUS"
"$PY" "$ROOT/audit_month_case.py" "$CASE" > month_audit.json
