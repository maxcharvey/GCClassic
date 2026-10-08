#!/usr/bin/env bash
# Run the sealed PLUME-012 wet-deposition retry1 matrix only from an
# interactive Slurm allocation.  Each model invocation remains a direct
# ./gcclassic call through the manifest-derived launcher; no Slurm run step is
# used for the executable itself.
set -euo pipefail

repository=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-gcclassic
vault=/cluster/home/mharvey/CharvBrain/project-vaults/gc-plume-transport
run_root=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-runs
build_directory="$repository/build_plume_qck_v2_runtime_contract_retry6"
qck_helper="$build_directory/bin/qck_bottom_regression"
model_binary="$build_directory/bin/gcclassic"
lmod_init=/cluster/software/stacks/2024-06/spack/opt/spack/linux-ubuntu22.04-x86_64_v3/gcc-12.2.0/lmod-8.7.24-ou4i7x2rgiaysly4vgawaga6muhkdye4/lmod/lmod/init/bash
expected_qck_helper_sha256=8f92114cbd13056aa9147631482b9d7037d5564c36b3b4acea3bb7751c5c7e18
expected_model_sha256=8db226f870dc9b8ef711ef48b7f2d5b7e9a7d71d9543169e0d71c7e71fa95ccb

host_name="$(hostname -s)"
case "$host_name" in
  eu-login-*)
    printf 'refusing to execute wet-deposition matrix on login host: %s\n' "$host_name" >&2
    exit 2
    ;;
esac

if [[ ! -f "$lmod_init" ]]; then
  printf 'required module initialization is absent: %s\n' "$lmod_init" >&2
  exit 2
fi
# The compute-node SSH session starts with the system Python and no NetCDF
# runtime paths.  Load only the already-used toolchain modules in this process.
source "$lmod_init"
module load stack/2024-06 gcc/12.2.0 openmpi/4.1.6 netcdf-c/4.9.2 netcdf-fortran/4.6.1 python/3.11.6
runtime_python="$(command -v python3)"
"$runtime_python" -c 'import h5py, numpy, yaml'

for required_path in "$qck_helper" "$model_binary"; do
  if [[ ! -x "$required_path" ]]; then
    printf 'required executable is absent or not executable: %s\n' "$required_path" >&2
    exit 2
  fi
done

actual_qck_helper_sha256="$(sha256sum "$qck_helper" | cut -d ' ' -f 1)"
actual_model_sha256="$(sha256sum "$model_binary" | cut -d ' ' -f 1)"
if [[ "$actual_qck_helper_sha256" != "$expected_qck_helper_sha256" ]]; then
  printf 'QCK helper SHA-256 differs from sealed runtime contract\n' >&2
  exit 2
fi
if [[ "$actual_model_sha256" != "$expected_model_sha256" ]]; then
  printf 'GCClassic SHA-256 differs from sealed runtime contract\n' >&2
  exit 2
fi
for required_binary in "$qck_helper" "$model_binary"; do
  if ldd "$required_binary" | grep -q 'not found'; then
    printf 'required shared library is unavailable for: %s\n' "$required_binary" >&2
    exit 2
  fi
done

printf 'compute host: %s\n' "$host_name"
printf 'running sealed QCK helper directly on compute node\n'
"$qck_helper"

for case_name in \
  stage1-qck-v2-wetdep-retry1-600s-off-1thread \
  stage1-qck-v2-wetdep-retry1-600s-off-8thread \
  stage1-qck-v2-wetdep-retry1-600s-on-1thread \
  stage1-qck-v2-wetdep-retry1-600s-on-8thread; do
  manifest="$vault/manifests/$case_name.yml"
  run_directory="$run_root/$case_name"
  printf 'launching %s from its resolved child manifest\n' "$case_name"
  "$runtime_python" "$repository/plume_transport/run_manifest_case.py" "$manifest" "$run_directory"
done

printf 'wet-deposition retry1 matrix completed on %s\n' "$host_name"
