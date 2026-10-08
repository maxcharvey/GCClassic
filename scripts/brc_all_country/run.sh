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
geojson=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/validation/BRC_148_ORIGIN_PROTOTYPE_20261002/geographic/ne_50m_admin_0_countries.geojson
python_bin=/cluster/home/mharvey/.venvs/gc-plume-transport-py312/bin/python
export PYTHONDONTWRITEBYTECODE=1
"$python_bin" "$scripts/country_catalogue.py" "$geojson" "$phase/catalogue" > CATALOGUE_BUILD.log 2> CATALOGUE_BUILD.stderr
"$python_bin" "$scripts/test_catalogue.py" "$geojson" > CATALOGUE_TEST.log 2> CATALOGUE_TEST.stderr
legacy=/cluster/work/climate/mharvey/ModelDevlopment/BrC/worktrees/GCClassic_148_BRC_ORIGIN_COUPLED_20261004/src/HEMCO/src/Extensions/hcox_origin_source_kernel_mod.F90
for bits in 32 64; do
 for variant in OPT SAN; do
  mkdir "$phase/fp${bits}_${variant}"
  cd "$phase/fp${bits}_${variant}"
  printf 'MODULE HCO_PRECISION_MOD\nUSE ISO_FORTRAN_ENV, ONLY: real%s\nINTEGER,PARAMETER :: fp=real%s\nEND MODULE\n' "$bits" "$bits" > precision.F90
  flags=(-O2 -fcheck=all -ffp-contract=off -Wall -Wextra -Werror -Wno-compare-reals)
  if [ "$variant" = SAN ]; then
   flags=(-O1 -g -fcheck=all -ffp-contract=off -Wall -Wextra -Werror -Wno-compare-reals -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie)
  fi
  gfortran "${flags[@]}" precision.F90 "$legacy" "$scripts/all_country_source_mod.F90" "$scripts/source_probe.F90" -o source_probe > COMPILE.log 2>&1
  ./source_probe > OUTPUT.log 2> STDERR.log
 done
 cmp "$phase/fp${bits}_OPT/OUTPUT.log" "$phase/fp${bits}_SAN/OUTPUT.log"
done
cd "$phase"
"$python_bin" "$scripts/audit_source.py" fp32_OPT/OUTPUT.log fp32_SAN/OUTPUT.log fp64_OPT/OUTPUT.log fp64_SAN/OUTPUT.log > SOURCE_AUDIT.json
sha256sum fp{32,64}_{OPT,SAN}/source_probe > BINARY.sha256
sha256sum -c SOURCES.sha256 --quiet > SOURCE_POSTCHECK.log
sha256sum -c INPUTS.sha256 --quiet > INPUT_POSTCHECK.log
sha256sum -c "$model_guard" --quiet > MODEL_POSTCHECK.log
date -u +%FT%TZ > FINISHED_UTC
