#!/usr/bin/env bash
set -euo pipefail
source /cluster/home/mharvey/gcclassic.gnu12.env
test -n "${SLURM_JOB_ID:-}"
case "$(hostname)" in eu-login-*|login*) exit 2;; esac
phase=$(realpath -- "$1")
cd "$phase"
test ! -e STARTED_UTC
sha256sum -c SOURCES.sha256 --quiet > SOURCE_PRECHECK.log
sha256sum -c INPUTS.sha256 --quiet > INPUT_PRECHECK.log
model_guard=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_NATIVE_INTEGRATION_20261005/native_wetdep/MODEL_SOURCE.sha256
sha256sum -c "$model_guard" --quiet > MODEL_PRECHECK.log
date -u +%FT%TZ > STARTED_UTC
hostname > HOST.txt
printf '%s\n' "$SLURM_JOB_ID" > JOB_ID.txt
scripts=$phase/captured_source
frozen=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_NATIVE_INTEGRATION_20261005/first_country_candidate
for variant in OPT SAN; do
 mkdir "$phase/$variant"
 cd "$phase/$variant"
 flags=(-O2 -Wall -Wextra -Werror -ffp-contract=off)
 if [ "$variant" = SAN ]; then
  flags=(-O1 -g -Wall -Wextra -Werror -ffp-contract=off -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie)
 fi
 gcc -std=c11 "${flags[@]}" -I"$scripts" -I"$frozen" "$scripts/country_pbl.c" "$scripts/probe.c" "$frozen/signed_cg_pbl_kernel.c" -Wl,--wrap=calloc -lm -o probe > COMPILE.log 2>&1
 ./probe > OUTPUT.log 2> STDERR.log
done
cd "$phase"
cmp OPT/OUTPUT.log SAN/OUTPUT.log
PYTHONDONTWRITEBYTECODE=1 /cluster/home/mharvey/.venvs/gc-plume-transport-py312/bin/python "$scripts/audit.py" OPT/OUTPUT.log SAN/OUTPUT.log > AUDIT.json
sha256sum OPT/probe SAN/probe > BINARY.sha256
sha256sum -c SOURCES.sha256 --quiet > SOURCE_POSTCHECK.log
sha256sum -c INPUTS.sha256 --quiet > INPUT_POSTCHECK.log
sha256sum -c "$model_guard" --quiet > MODEL_POSTCHECK.log
date -u +%FT%TZ > FINISHED_UTC
