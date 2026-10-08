#!/usr/bin/env bash
set -euo pipefail
source /cluster/home/mharvey/gcclassic.gnu12.env
test -n "${SLURM_JOB_ID:-}"
case "$(hostname)" in eu-login-*|login*) exit 2;; esac
bridge_dir=$(cd -- "$(dirname -- "$0")" && pwd)
phase=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_BRIDGE_20261007
previous=/cluster/work/climate/mharvey/ModelDevlopment/BrC/runs/investigations/BRC_ORIGIN_NATIVE_INTEGRATION_20261005
cd "$phase"
test ! -e RECEIPTS_STARTED_UTC
sha256sum -c RECEIPT_SOURCES.sha256 --quiet > RECEIPT_SOURCE_PRECHECK.log
sha256sum -c REUSED_NATIVE_OUTPUTS.sha256 --quiet > REUSED_PRECHECK.log
date -u +%FT%TZ > RECEIPTS_STARTED_UTC
ulimit -s unlimited
/cluster/home/mharvey/.venvs/gc-plume-transport-py312/bin/python "$bridge_dir/prepare_receipts.py" OPT/OUTPUT.log > RECEIPT_INPUT.txt
sha256sum RECEIPT_INPUT.txt > RECEIPT_INPUT.sha256
for variant in OPT SAN; do
 flags=(-std=c11 -Wall -Wextra -Werror -ffp-contract=off)
 if [ "$variant" = OPT ]; then flags+=(-O2); else flags+=(-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie); fi
 gcc "${flags[@]}" -I"$previous/continuation2000_stable_receipt" "$bridge_dir/stable_receipt.c" -lm -o "stable_$variant" > "STABLE_${variant}_COMPILE.log" 2>&1
 ./"stable_$variant" < RECEIPT_INPUT.txt > "STABLE_$variant.log" 2> "STABLE_$variant.stderr"
done
cmp STABLE_OPT.log STABLE_SAN.log
/cluster/home/mharvey/.venvs/gc-plume-transport-py312/bin/python "$bridge_dir/audit_v2.py" "$phase" "$previous" > AUDIT_V2.json
/cluster/home/mharvey/.venvs/gc-plume-transport-py312/bin/python "$bridge_dir/kl_witness.py" "$phase" > KL_WITNESS.json
sha256sum -c REUSED_NATIVE_OUTPUTS.sha256 --quiet > REUSED_POSTCHECK.log
sha256sum -c RECEIPT_INPUT.sha256 --quiet > RECEIPT_INPUT_POSTCHECK.log
sha256sum -c RECEIPT_SOURCES.sha256 --quiet > RECEIPT_SOURCE_POSTCHECK.log
sha256sum -c SOURCES.sha256 --quiet > SOURCE_POSTCHECK.log
sha256sum -c INPUTS.sha256 --quiet > INPUT_POSTCHECK.log
sha256sum -c "$previous/native_wetdep/MODEL_SOURCE.sha256" --quiet > MODEL_POSTCHECK.log
sha256sum OPT/fixture_bridge SAN/fixture_bridge stable_OPT stable_SAN > BINARY.sha256
date -u +%FT%TZ > RECEIPTS_FINISHED_UTC
