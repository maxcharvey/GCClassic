#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --no-requeue
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=8G
#SBATCH --time=01:00:00
set -euo pipefail
cd "${BRC_AUGUST_ROOT:?Set BRC_AUGUST_ROOT to the installed staging root}"
PY="${BRC_PYTHON:-python3}"
"$PY" verify_acceptance.py
"$PY" analyze_august_pair.py
