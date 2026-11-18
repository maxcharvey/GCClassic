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
# Both provenance tracers have all native dry/wet diagnostic fields.
for spc in PWTC SWTC FOCPI FOCPO; do
    for kind in DryDep DryDepVel WetLossConv WetLossLS; do
        rg -q "${kind}_${spc}" "$fixture/HISTORY.rc"
    done
done
# Derived WTC is not a physical deposition/process-budget species.
! rg -q "'(DryDep|DryDepVel|WetLossConv|WetLossLS|Budget[A-Za-z]+Full)_WTC'" "$fixture/HISTORY.rc"
# DBRCPOA is dry-deposited and retains non-wet operator budgets only.
for kind in DryDep DryDepVel BudgetEmisDryDepFull BudgetTransportFull; do
    rg -q "${kind}_DBRCPOA" "$fixture/HISTORY.rc"
done
! rg -q "'(WetLossConv|WetLossConvFrac|WetLossLS|BudgetWetDepFull)_DBRCPOA'" "$fixture/HISTORY.rc"
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
perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/HISTORY.rc" --monthly
rg -q 'BrCDryDep.frequency: 00000100 000000' "$fixture/HISTORY.rc"
rg -q 'BrCWetLoss.duration: 00000100 000000' "$fixture/HISTORY.rc"
cp "$fixture/HISTORY.rc" "$fixture/saved"
if perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/HISTORY.rc" --monthly --short-test-hourly 2> "$fixture/error"; then exit 1; fi
cmp "$fixture/saved" "$fixture/HISTORY.rc"
printf 'PASS: monthly, incompatible flags, daily default, explicit hourly, idempotence, backup, precursor exclusions, atomic refusal\n'
# BC must remain physically last when active, including repeated helper calls.
cat > "$fixture/bc" <<'EOF'
COLLECTIONS: 'Restart',
             'BoundaryConditions',
::
Restart.mode: 'instantaneous'
::
BoundaryConditions.template: '%y4%m2%d2_%h2%n2z.nc4',
BoundaryConditions.mode: 'instantaneous'
BoundaryConditions.fields: 'SpeciesBC_?ADV?',
::
EOF
perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/bc"
cp "$fixture/bc" "$fixture/bc.first"
perl "$script_dir/configure_brc_deposition.pl" --history "$fixture/bc"
cmp "$fixture/bc.first" "$fixture/bc"
perl -0ne 'exit(!/# END managed BrC deposition\nBoundaryConditions\.template:/)' "$fixture/bc"
printf 'PASS: BoundaryConditions definition remains physically last\n'
