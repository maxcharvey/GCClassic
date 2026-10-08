#!/usr/bin/env bash
#SBATCH --job-name=firex-tierf-phase2-join
#SBATCH --partition=normal.4h
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=16G
#SBATCH --time=02:00:00
#SBATCH --output=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-runs/slurm-firex-tierf-phase2-join-%j.out
#SBATCH --error=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-runs/slurm-firex-tierf-phase2-join-%j.err

set -euo pipefail

workspace=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-gcclassic
code_dir="$workspace/plume_transport"
run_root=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-runs
primary="$run_root/stage1-firex-aq-tier-f-phase2-join-20190806-v1"
reproduction="$run_root/stage1-firex-aq-tier-f-phase2-join-20190806-reproduction1"
comparison="$run_root/stage1-firex-aq-tier-f-phase2-join-20190806-reproduction1-comparison.json"
python_exe=/cluster/software/stacks/2024-06/spack/opt/spack/linux-ubuntu22.04-x86_64_v3/gcc-12.2.0/python-3.11.6-ukhwpjnwzzzizek3pgr75zkbhxros5fq/bin/python3.11
contract="$code_dir/phase2_tier_f_join_contract_20190806_v1.json"
joiner="$code_dir/firex_tier_f_phase2_join.py"
checksums="$code_dir/phase2_tier_f_join_execution_20190806_v1.sha256"
profile_manifest=/cluster/home/mharvey/CharvBrain/project-vaults/gc-plume-transport/manifests/stage1-v0-source-only.yml

test -n "${SLURM_JOB_ID:-}"
test "$(hostname -s)" != "eu-login-11"
test -x "$python_exe"
test ! -e "$primary"
test ! -e "$reproduction"
test ! -e "$comparison"

cd "$workspace"
sha256sum -c "$checksums"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="/home/mharvey/PythonScripts:$code_dir"

"$python_exe" -m pytest -q -p no:cacheprovider \
  "$code_dir/test_firex_tier_f_phase2_join.py"

"$python_exe" -m pytest -q -p no:cacheprovider \
  "$code_dir" --ignore="$code_dir/test_profiles.py"

"$python_exe" "$code_dir/test_profiles.py" "$profile_manifest" -q

"$python_exe" "$joiner" \
  --contract "$contract" \
  --output-dir "$primary"

"$python_exe" "$joiner" \
  --contract "$contract" \
  --output-dir "$reproduction"

"$python_exe" "$joiner" \
  --compare-primary "$primary" \
  --compare-reproduction "$reproduction" \
  --comparison-output "$comparison"

test -f "$primary/PHASE2_JOIN_SEAL.json"
test -f "$reproduction/PHASE2_JOIN_SEAL.json"
test -f "$comparison"

echo "PHASE2_OVERNIGHT_STATUS=PASS"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "PRIMARY=$primary"
echo "REPRODUCTION=$reproduction"
echo "COMPARISON=$comparison"
