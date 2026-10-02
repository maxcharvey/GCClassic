#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
printf "COLLECTIONS: 'Restart',\n::\nRestart.mode: 'instantaneous'\n::\n\n\n" > "$fixture/HISTORY.rc"
cp "$fixture/HISTORY.rc" "$fixture/original"
perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/HISTORY.rc"
cmp "$fixture/original" "$fixture/HISTORY.rc.before_brc"
perl -0ne 'exit(!/::\n# BEGIN managed BrC deposition/)' "$fixture/HISTORY.rc"
rg -q 'BrCDryDep.frequency: 00000001 000000' "$fixture/HISTORY.rc"
cp "$fixture/HISTORY.rc" "$fixture/first"
perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/HISTORY.rc"
cmp "$fixture/first" "$fixture/HISTORY.rc"
perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/HISTORY.rc" --short-test-hourly
rg -q 'BrCWetLoss.frequency: 00000000 010000' "$fixture/HISTORY.rc"
! rg -q "'(DryDep|DryDepVel|WetLossConv|WetLossLS)_FSOAP'" "$fixture/HISTORY.rc"
printf 'Invalid declaration\n' > "$fixture/invalid"
cp "$fixture/invalid" "$fixture/saved"
if perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/invalid" 2> "$fixture/error"; then exit 1; fi
cmp "$fixture/saved" "$fixture/invalid"
printf "COLLECTIONS: 'Restart',\n::\nBrCDryDep.fields: 'custom'\n::\n" > "$fixture/conflict"
cp "$fixture/conflict" "$fixture/saved"
if perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/conflict" 2> "$fixture/error"; then exit 1; fi
cmp "$fixture/saved" "$fixture/conflict"
printf 'PASS: daily default, explicit hourly, idempotence, backup, precursor exclusions, atomic refusal\n'
