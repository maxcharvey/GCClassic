#!/usr/bin/env bash
set -euo pipefail
ROOT="${BRC_AUGUST_ROOT:?Set BRC_AUGUST_ROOT to the installed staging root}"
PY="${BRC_PYTHON:-python3}"
[[ -n "${SLURM_JOB_ID:-}" ]] || { echo 'No allocation'; exit 2; }
case "$(hostname -s)" in *login*) echo 'Refusing model on login node'; exit 2;; esac
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
export OMP_STACKSIZE=512M
ulimit -s unlimited
cd "$ROOT"
{ hostname; scontrol show job "$SLURM_JOB_ID"; printf "OMP_NUM_THREADS=%s\nOMP_STACKSIZE=%s\n" "$OMP_NUM_THREADS" "$OMP_STACKSIZE"; } > smoke_allocation.txt
if [[ "$#" -eq 0 ]]; then
 set -- BRC_147_GFAS_FIXED30_L15_20260921_SMOKE1H_20260922 BRC_148_GFAS_NATIVE3D_20260921_SMOKE1H_20260922
fi
for CASE in "$@"; do
 [[ "$CASE" == BRC_147_GFAS_FIXED30_L15_20260921_SMOKE1H_20260922 || "$CASE" == BRC_148_GFAS_NATIVE3D_20260921_SMOKE1H_20260922 ]] || { echo "Not a smoke case: $CASE" >&2; exit 2; }
 "$PY" "$ROOT/preflight_restart_gate.py" "$CASE" > "$ROOT/$CASE/prelaunch.json"
 cd "$ROOT/$CASE"
 date -u +%FT%TZ > start_utc.txt
 set +e
 /usr/bin/time -v ./gcclassic > GC.log 2> timing.log
 STATUS=$?
 set -e
 printf '%s\n' "$STATUS" > model_exit_code.txt
 date -u +%FT%TZ > end_utc.txt
 echo "$CASE MODEL_EXIT:$STATUS"
 [[ "$STATUS" == 0 ]] || exit "$STATUS"
 cd "$ROOT"
done
