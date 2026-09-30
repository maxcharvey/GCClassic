#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out=${1:?usage: run.sh BUILD_DIRECTORY}
mkdir -p "$out"
cd "$out"
gfortran -cpp -O0 -g -fcheck=all -ffpe-trap=zero,overflow -Wall -Wextra \
  -J "$out" -I "$out" \
  "$root/src/HEMCO/src/Shared/Headers/hco_precision_mod.F90" \
  "$root/src/HEMCO/src/Extensions/hcox_finn_profile_kernel_mod.F90" \
  "$root/tests/finn_profile/test_profile.F90" -o test_profile
./test_profile
