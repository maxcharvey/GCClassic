#!/usr/bin/env bash
# Build-independent, fresh 20-minute controls for the output-only QCK sizing
# diagnostic. Run only from an interactive Slurm compute-node shell.
set -euo pipefail

repository=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-gcclassic
run_root=/cluster/work/climate/mharvey/ModelDevlopment/BrC/plume-transport-runs
template="$run_root/stage1-tpcore-qck-bottom-microclosure-v2-runtime-contract-retry6-150s-8thread"
model_binary="$repository/build_qck_corrected_trajectory_sizing/bin/gcclassic"
expected_model_sha256=b21ea5858d1e2d96959223dd60e6cedccb84ecc5fead9baec96a0aa339183255

off8=stage1-qck-sizing-control-20190101-20m-off-8thread-v1
on1=stage1-qck-sizing-control-20190101-20m-on-1thread-v1
on8=stage1-qck-sizing-control-20190101-20m-on-8thread-v1
repeat8=stage1-qck-sizing-control-20190101-20m-on-8thread-repeat1-v1

host_name="$(hostname -s)"
case "$host_name" in
  eu-login-*)
    printf 'refusing to execute QCK sizing controls on login host: %s\n' \
      "$host_name" >&2
    exit 2
    ;;
esac

if [[ "$(sha256sum "$model_binary" | cut -d ' ' -f 1)" != \
      "$expected_model_sha256" ]]; then
  printf 'fresh QCK sizing executable differs from expected SHA-256\n' >&2
  exit 2
fi
if ldd "$model_binary" | rg -q 'not found'; then
  printf 'fresh QCK sizing executable has an unresolved shared library\n' >&2
  exit 2
fi

prepare_case() {
  local case_name=$1
  local run_directory="$run_root/$case_name"
  if [[ -e "$run_directory" ]]; then
    printf 'fresh control directory already exists: %s\n' "$run_directory" >&2
    exit 2
  fi
  mkdir -p "$run_directory/OutputDir" "$run_directory/Restarts"
  cp -a \
    "$template/.gitignore" \
    "$template/HEMCO_Config.rc" \
    "$template/HEMCO_Config.rc.gmao_metfields" \
    "$template/HEMCO_Diagn.rc" \
    "$template/HISTORY.rc" \
    "$template/PlumeSource.20190101_0000z.nc" \
    "$template/geoschem_config.yml" \
    "$template/species_database.yml" \
    "$run_directory/"
  cp -a "$template/Restarts/GEOSChem.Restart.20190101_0000z.nc4" \
    "$run_directory/Restarts/"
  ln -s "$model_binary" "$run_directory/gcclassic"
  ln -s "$repository" "$run_directory/CodeDir"
}

run_case() {
  local case_name=$1
  local threads=$2
  local sizing=$3
  local run_id=$4
  local run_directory="$run_root/$case_name"

  unset \
    GC_QCK_BOTTOM_SURVEY \
    GC_QCK_BOTTOM_SURVEY_RUN_ID \
    GC_QCK_BOTTOM_SURVEY_FILE \
    GC_QCK_BOTTOM_SIZING_DIAGNOSTICS
  export GC_QCK_BOTTOM_MICROCLOSURE_EVENT_MAX_KG=10
  export GC_QCK_BOTTOM_MICROCLOSURE_CALL_MAX_KG=10
  export GC_QCK_BOTTOM_MICROCLOSURE_RUN_MAX_KG=10
  export GC_PLUME_TPCORE_BUDGETS=1
  export GC_PLUME_TPCORE_BUDGET_RUN_ID="$run_id"
  export GC_PLUME_TPCORE_BUDGET_MANIFEST_ID=qck-sizing-control-v1
  export GC_PLUME_TPCORE_BUDGET_FILE=./OutputDir/plume_tpcore_budget_v2.csv
  export GC_PLUME_TPCORE_CELL_DIAGNOSTICS=1
  export GC_PLUME_TPCORE_CELL_DIAG_FILE=./OutputDir/plume_tpcore_cell_events_v3.csv
  export GC_PLUME_TPCORE_DONOR_DIAGNOSTICS=1
  export GC_PLUME_TPCORE_DONOR_DIAG_FILE=./OutputDir/plume_tpcore_donor_events_v3.csv
  export OMP_NUM_THREADS="$threads"
  export OMP_STACKSIZE=500m
  export OMP_PROC_BIND=spread
  export OMP_PLACES=cores
  if [[ "$sizing" == 1 ]]; then
    export GC_QCK_BOTTOM_SIZING_DIAGNOSTICS=1
  fi

  printf 'running %s with OMP_NUM_THREADS=%s sizing=%s\n' \
    "$case_name" "$threads" "$sizing"
  (
    cd "$run_directory"
    set +e
    /usr/bin/time -v -o gcclassic.time.log \
      ./gcclassic > gcclassic.log 2>&1
    model_status=$?
    set -e
    printf '%s\n' "$model_status" > OutputDir/model_exit_code.txt
    if [[ "$model_status" -ne 0 ]]; then
      exit "$model_status"
    fi
  )

  rg -q 'E N D   O F   G E O S -- C H E M' "$run_directory/gcclassic.log"
  test -f "$run_directory/Restarts/GEOSChem.Restart.20190101_0020z.nc4"
  test -f "$run_directory/Restarts/HEMCO_restart.201901010020.nc"
  if [[ "$sizing" == 1 ]]; then
    python "$repository/plume_transport/validate_qck_sizing_summary.py" \
      "$run_directory/gcclassic.log" \
      --event-max-kg 10 --call-max-kg 10 --run-max-kg 10 \
      --output "$run_directory/OutputDir/qck_sizing_summary_validation.json" \
      > "$run_directory/OutputDir/qck_sizing_summary_validation.stdout.json"
  elif rg -q '^QCK_BOTTOM_SIZING_' "$run_directory/gcclassic.log"; then
    printf 'disabled control unexpectedly emitted a sizing summary\n' >&2
    exit 2
  fi
  if find "$run_directory" -name 'qck_bottom_survey_v1.csv' -print -quit | \
       rg -q .; then
    printf 'native survey artifact appeared in sizing control\n' >&2
    exit 2
  fi
}

for case_name in "$off8" "$on1" "$on8" "$repeat8"; do
  prepare_case "$case_name"
done

ulimit -s unlimited
run_case "$off8" 8 0 qck-sizing-state-neutral-8thread
run_case "$on1" 1 1 qck-sizing-on-1thread
run_case "$on8" 8 1 qck-sizing-state-neutral-8thread
run_case "$repeat8" 8 1 qck-sizing-on-8thread-repeat1

off8_directory="$run_root/$off8"
on1_directory="$run_root/$on1"
on8_directory="$run_root/$on8"
repeat8_directory="$run_root/$repeat8"

# With identical thread count and ledger provenance, enabling the sizing
# diagnostic must leave the model endpoint and existing ledgers byte-identical.
cmp \
  "$off8_directory/Restarts/GEOSChem.Restart.20190101_0020z.nc4" \
  "$on8_directory/Restarts/GEOSChem.Restart.20190101_0020z.nc4"
cmp \
  "$off8_directory/Restarts/HEMCO_restart.201901010020.nc" \
  "$on8_directory/Restarts/HEMCO_restart.201901010020.nc"
for ledger in \
  plume_tpcore_budget_v2.csv \
  plume_tpcore_cell_events_v3.csv \
  plume_tpcore_donor_events_v3.csv; do
  cmp "$off8_directory/OutputDir/$ledger" "$on8_directory/OutputDir/$ledger"
done

# The existing normalized ledgers and the new summary must also agree across
# one and eight threads. A repeated eight-thread run checks repeatability.
python "$repository/plume_transport/compare_tpcore_budget_threads.py" \
  "$on1_directory/OutputDir/plume_tpcore_budget_v2.csv" \
  "$on8_directory/OutputDir/plume_tpcore_budget_v2.csv" \
  --relative-tolerance 1e-12 --absolute-tolerance-kg 1e-12 \
  --report "$on8_directory/OutputDir/qck_sizing_budget_thread_comparison.json" \
  > "$on8_directory/OutputDir/qck_sizing_budget_thread_comparison.stdout.json"
python "$repository/plume_transport/compare_tpcore_cell_diagnostics_threads.py" \
  "$on1_directory/OutputDir/plume_tpcore_cell_events_v3.csv" \
  "$on8_directory/OutputDir/plume_tpcore_cell_events_v3.csv" \
  --relative-tolerance 1e-12 --absolute-tolerance-kg 1e-12 \
  --report "$on8_directory/OutputDir/qck_sizing_cell_thread_comparison.json" \
  > "$on8_directory/OutputDir/qck_sizing_cell_thread_comparison.stdout.json"
python "$repository/plume_transport/compare_tpcore_donor_diagnostics_threads.py" \
  "$on1_directory/OutputDir/plume_tpcore_donor_events_v3.csv" \
  "$on8_directory/OutputDir/plume_tpcore_donor_events_v3.csv" \
  --relative-tolerance 1e-12 --absolute-tolerance 1e-12 \
  --report "$on8_directory/OutputDir/qck_sizing_donor_thread_comparison.json" \
  > "$on8_directory/OutputDir/qck_sizing_donor_thread_comparison.stdout.json"
python "$repository/plume_transport/validate_qck_sizing_summary.py" \
  "$on1_directory/gcclassic.log" \
  --event-max-kg 10 --call-max-kg 10 --run-max-kg 10 \
  --compare-log "$on8_directory/gcclassic.log" \
  --output "$on8_directory/OutputDir/qck_sizing_1t_8t_comparison.json" \
  > "$on8_directory/OutputDir/qck_sizing_1t_8t_comparison.stdout.json"
python "$repository/plume_transport/validate_qck_sizing_summary.py" \
  "$on8_directory/gcclassic.log" \
  --event-max-kg 10 --call-max-kg 10 --run-max-kg 10 \
  --compare-log "$repeat8_directory/gcclassic.log" \
  --output "$repeat8_directory/OutputDir/qck_sizing_8t_repeat_comparison.json" \
  > "$repeat8_directory/OutputDir/qck_sizing_8t_repeat_comparison.stdout.json"

cmp \
  "$on8_directory/Restarts/GEOSChem.Restart.20190101_0020z.nc4" \
  "$repeat8_directory/Restarts/GEOSChem.Restart.20190101_0020z.nc4"

printf 'QCK sizing controls passed on %s with executable %s\n' \
  "$host_name" "$expected_model_sha256"
