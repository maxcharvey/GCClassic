#!/usr/bin/env bash
set -euo pipefail
source /cluster/home/mharvey/gcclassic.gnu12.env
test -n "${SLURM_JOB_ID:-}"
case "$(hostname)" in eu-login-*|login*) exit 2;; esac
bridge_dir=$(cd -- "$(dirname -- "$0")" && pwd)
phase=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_BRIDGE_20261007
previous=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_NATIVE_INTEGRATION_20261005
frozen=$previous/first_country_candidate
old=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_COUPLED_20261003
cd "$phase"
test ! -e STARTED_UTC
sha256sum -c SOURCES.sha256 --quiet > SOURCE_PRECHECK.log
sha256sum -c INPUTS.sha256 --quiet > INPUT_PRECHECK.log
sha256sum -c "$previous/native_wetdep/MODEL_SOURCE.sha256" --quiet > MODEL_PRECHECK_COMPUTE.log
date -u +%FT%TZ > STARTED_UTC
hostname > HOST.txt
ulimit -s unlimited
for variant in OPT SAN; do
 mkdir "$variant"
 cd "$variant"
 flags=(-Wall -Wextra -Werror -ffp-contract=off)
 if [ "$variant" = OPT ]; then
  flags+=(-O2)
  fflags=(-O2 -fcheck=all -ffp-contract=off)
 else
  flags+=(-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie)
  fflags=(-O1 -g -fcheck=all -ffp-contract=off -fsanitize=address,undefined -fno-pie)
 fi
 gfortran "${fflags[@]}" -c "$bridge_dir/country_bridge_iso.F90" "$bridge_dir/iso_probe.F90" > FORTRAN_COMPILE.log 2>&1
 gcc -std=c11 "${flags[@]}" -I"$bridge_dir" -I"$frozen" -c "$bridge_dir/country_bridge.c" "$bridge_dir/fixture_bridge.c" "$frozen/signed_cg_pbl_kernel.c" "$frozen/pressure_cg_map.c" "$frozen/pressure_cg_incoming.c" "$frozen/entropy_newton_laplacian.c" "$frozen/positive_laplacian_linear.c" "$frozen/entropy_newton_complete.c" "$frozen/guarded_entropy_classifier.c" "$frozen/guarded_entropy.c" > C_COMPILE.log 2>&1
 gfortran "${fflags[@]}" -no-pie ./*.o -Wl,--wrap=malloc -Wl,--wrap=calloc -Wl,--wrap=guarded_entropy -lm -o fixture_bridge > LINK.log 2>&1
 ./fixture_bridge "$old/budget_surface_gross_capture/surface_step000001_20180801_000000.bin" "$old/budget_surface_mixing_capture/mix_step000001_lat0019.bin" "$old/budget_surface_mixing_capture/mix_step000001_lat0028.bin" > OUTPUT.log 2> STDERR.log
 cd "$phase"
done
cmp OPT/OUTPUT.log SAN/OUTPUT.log
"${BRC_BRIDGE_PYTHON:-/cluster/home/mharvey/.venvs/gc-plume-transport-py312/bin/python}" "$bridge_dir/audit.py" "$phase" "$previous" > AUDIT.log
sha256sum OPT/fixture_bridge SAN/fixture_bridge > BINARY.sha256
sha256sum -c SOURCES.sha256 --quiet > SOURCE_POSTCHECK.log
sha256sum -c INPUTS.sha256 --quiet > INPUT_POSTCHECK.log
sha256sum -c "$previous/native_wetdep/MODEL_SOURCE.sha256" --quiet > MODEL_POSTCHECK.log
date -u +%FT%TZ > FINISHED_UTC
