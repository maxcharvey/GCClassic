# GCClassic plume-transport operator-isolation tooling

This directory builds the Stage-1 source-only smoke case and the subsequent
TPCORE operator-isolation case recorded in the project vault manifests. It
generates normalized 3-D HEMCO source-rate fields; GCClassic's native
`mixing_mod::DO_TEND` applies those fields. There is no direct write to the
GEOS-Chem tracer state.

The reproducible order is:

1. Generate a stock 4 x 5, 72-level, MERRA-2 TransportTracers run directory
   with `src/GEOS-Chem/run/GCClassic/createRunDir.sh`.
2. Run `generate_source.py` with the checked manifest.
3. Run `prepare_run.py` to install the focused configs and zero-initialized
   plume restart.
4. Audit the run directory, compile, and execute it in a Slurm allocation.
5. Run `validate_source.py` before the model, followed by `validate_run.py`
   for V0 or `validate_tpcore.py` for the TPCORE case.

The tags are inert and have no removal. These are numerical operator tests,
not physical fire-plume or BrC experiments.

## FIREX-AQ dry absorption operator oracle

`dry_absorption_operator.py` defines the pure arithmetic for the PLUME-028
output-only diagnostic. It converts dry extinction and dry single-scattering
albedo to layer absorption, reports ambient-volume `Mm-1`, interpolates
absorption itself to exact wavelengths, checks labelled component closure, and
calculates qualified 405--664 nm AAE.

The optional reference-volume conversion requires numeric reference
temperature and pressure arguments. It has no STP defaults because the
FIREX-AQ AOP R2 header labels fields as STP without defining that numeric
state. For the FIREX-AQ comparison, callers must explicitly supply 273 K and
1013 mbar from Zeng et al. (2022), which analyzes the same 405/532/664 nm PAS
measurements. These constants are not inferred from the separate SP2 product.

## FIREX-AQ interval-aware SP2 correction

The Argon `FIREX-AQ2` custom merge used minute-aligned 60 s intervals, while
the R3 carrier uses half-minute-offset 60 s intervals. The historical
`obs_data/withAMS` files copied the `FIREX-AQ2` BC values by row position,
which attached them to carrier intervals shifted by 30 s and coerced mixed
dilution states into a binary field.

The correction workflow is:

```bash
python plume_transport/fetch_firex_aq_sp2.py --output-dir "$raw_sp2_dir"
python plume_transport/prepare_firex_aq_bc_merge.py \
  --baseline-dir "$with_ams_backup_dir" \
  --sp2-dir "$raw_sp2_dir" \
  --output-dir "$corrected_dir"
python plume_transport/validate_firex_aq_bc_merge.py \
  --merge-manifest "$corrected_dir/firex_aq_bc_merge_manifest.json" \
  --source-manifest "$raw_sp2_dir/firex_aq_sp2_1hz_source_manifest.json" \
  --aq2-dir "$firex_aq2_dir" \
  --output "$corrected_dir/firex_aq_bc_merge_validation.json"
```

The merger uses each R3 row's explicit half-open `time_bnds`, averages only
valid direct 1 Hz SP2 mass samples, retains a dilution fraction and mixed-state
flag, and asserts that every non-BC variable is unchanged. It writes a new
versioned directory and refuses to overwrite existing data.

## FIREX-AQ interval-aware AOP correction

The official R3 NetCDF carrier cannot be used as the optical authority. Direct
comparison against the final `firexaq-AOP-optical` R2 ICARTT files found R3
intervals with a finite `abs_dry_664` value even when the direct product had no
valid 664 nm absorption samples in that interval. The SP2 correction correctly
preserved this pre-existing R3 value, so this is a separate upstream optical
collocation defect rather than a regression in the BC repair.

`fetch_firex_aq_aop.py` seals the 23 final R2 direct products.
`prepare_firex_aq_aop_merge.py` then averages each of the three absorption
bands independently onto the corrected carrier's explicit half-open
`time_bnds`. It replaces only `abs_dry_405`, `abs_dry_532`, and
`abs_dry_664`, adds a per-band valid 1 Hz sample count, and verifies all other
variables—including corrected BC—remain unchanged.

The resulting versioned carrier is the minimum accepted input to
`firex_plume_age.py`. The plume-age command fails closed on the legacy optical
carrier unless its explicit diagnostic-only override is used. It retains
finite negative absorption, qualifies AAE only for strictly positive endpoint
pairs, and does not substitute general smoke age where corrected smoke age is
missing.

The direct AOP R2 header still does not define numeric standard temperature
and pressure. The comparison contract supplies 273 K and 1013 mbar from the
peer-reviewed same-instrument FIREX-AQ analysis
<https://doi.org/10.5194/acp-22-8009-2022>; the archive metadata deficiency
remains documented.

`firex_model_match.py` prepares the model side.
It performs deterministic nearest-time, cyclic-longitude, latitude-centre,
and geometric layer-centre matching; retains every offset and rejection
reason; and leaves rejected values missing. Geometric altitude uses
`Met_PHIS` plus cumulative `Met_BXHEIGHT`. Its optional reference-volume
conversion has no defaults and remains unusable until numeric AOP reference
pressure and temperature are supplied explicitly.

## FIREX GEOS-Chem HISTORY-time ingestion

`firex_history_time.py` supplies the model times passed to the matcher. It is
read-only and decodes each file's CF `time` coordinate as `minutes since` its
own Gregorian reference; it never infers a record time from a timestamped
filename. Unsupported units, calendars, nonfinite values, duplicated records,
and cadence/endpoint mismatches fail closed.

For the first daily exact-band segment, validate the 71+1 rollover timeline
before collocation:

```bash
python plume_transport/validate_firex_history_time.py \
  "$rundir/OutputDir/GEOSChem.FirexExact.20190801_0010z.nc4" \
  "$rundir/OutputDir/GEOSChem.FirexExact.20190802_0000z.nc4" \
  --expected-records 72 --cadence-minutes 20 \
  --expected-first 2019-08-01T00:20:00Z \
  --expected-last 2019-08-02T00:00:00Z \
  --output "$rundir/OutputDir/firex_exact_history_time_validation.json"
```

The resulting decoded timestamps—not filenames—are the `model_time` input to
`firex_model_match.py`. The validator writes only its optional JSON report;
it never changes NetCDF output or model metadata.

## Generic QCK_BOTTOM prevalence survey

`GC_QCK_BOTTOM_SURVEY=1` enables a general, species-independent survey ledger.
In this mode Qckxyz preflights each negative bottom cell with the conservative
full-column policy, records its feasibility and mass scale, and then applies
the historical native immediate-donor correction.  This lets diagnostic runs
continue along baseline behavior without weakening the default conservative
remedy.  The survey is default-off and requires:

```bash
export GC_QCK_BOTTOM_SURVEY=1
export GC_QCK_BOTTOM_SURVEY_RUN_ID=my-survey-control
export GC_QCK_BOTTOM_SURVEY_FILE=./OutputDir/qck_bottom_survey_v1.csv
```

Validate and summarize a completed ledger with:

```bash
python plume_transport/validate_qck_bottom_survey.py \
  "$rundir/OutputDir/qck_bottom_survey_v1.csv" \
  "$rundir/geoschem_config.yml" \
  --report "$rundir/OutputDir/qck_bottom_survey_validation.json"
```

## Deferred-QCK full-PBL diagnostic

The completed PBL operator-isolation case uses survey mode to preserve and
measure historical QCK behavior. It requires four controls: PBL off/on at one
and eight threads, each with C0--C6 checkpoints. Validate the source-subtracted
PBL boundary, exact thread equality, inactive downstream boundaries, and QCK
contamination with:

```bash
python plume_transport/validate_pbl_ab.py \
  "$pbl_off_1" "$pbl_off_8" "$pbl_on_1" "$pbl_on_8" \
  --report "$pbl_on_1/OutputDir/pbl_ab_validation.json"
```

The validator's passing status is intentionally
`diagnostic_pass_with_deferred_qck_bias`; it never grants scientific
acceptance.

## Deferred-QCK convection diagnostic

With full PBL mixing held on, validate convection off/on at one/eight threads
across the clean C3-to-C4 boundary using:

```bash
python plume_transport/validate_convection_ab.py \
  "$conv_off_1" "$conv_off_8" "$conv_on_1" "$conv_on_8" \
  --report "$conv_on_1/OutputDir/convection_ab_validation.json"
```

The validator requires an exactly zero off boundary, global and per-column
conservation in the on arm, exact thread checkpoint arrays, inactive C4-to-C6
boundaries, and validated QCK summaries. A fixture with no material convection
response is labeled inconclusive rather than passed.

The checked case manifest is
`~/CharvBrain/project-vaults/gc-plume-transport/manifests/stage1-v0-source-only.yml`.
For a newly generated stock run directory, prepare and validate the controlled
inputs from the repository root with:

```bash
python plume_transport/generate_source.py "$manifest" \
  "$rundir/PlumeSource.20190101_0000z.nc" \
  --summary "$rundir/plume_source_summary.json"
python plume_transport/prepare_run.py "$manifest" "$rundir" \
  --code-directory src/GEOS-Chem
python plume_transport/validate_source.py "$manifest" \
  "$rundir/PlumeSource.20190101_0000z.nc" \
  --report "$rundir/plume_source_validation.json"
python plume_transport/validate_run.py "$manifest" \
  "$rundir/Restarts/GEOSChem.Restart.20190101_0020z.nc4" \
  --report "$rundir/run_validation.json"
```

`prepare_run.py` is idempotent: it restores the stock TransportTracers HEMCO
configuration before applying the frozen case changes, and it produces a
deterministic zero-initialized restart.

For `stage1-tpcore-ledger-v1`, `prepare_run.py` selects the transport-on
configuration from the manifest and adds `BudgetTransportFull`. Run the model
with the structured checkpoints explicitly enabled:

```bash
export GC_PLUME_CHECKPOINTS=1
export GC_PLUME_CHECKPOINT_DIR="$rundir/OutputDir/PlumeCheckpoints"
export GC_PLUME_CHECKPOINT_RUN_ID=stage1-tpcore-only-20190101
./gcclassic
```

The checkpoint writer saves float64 3-D plume mass and contemporaneous dry-air
mass/pressure at C0--C6. It uses `NOCLOBBER`, so the checkpoint directory must
be empty before a run; this prevents evidence from two executions being mixed.

## PLUME-012 Phase-A TPCORE causality diagnostic

The paired Phase-A manifests are in the project vault:

- `manifests/stage1-tpcore-causality-1thread.yml`
- `manifests/stage1-tpcore-causality-8thread.yml`

They inherit the frozen V2 source/operator configuration and only add a
runtime-gated `plume-tpcore-budget-v1` CSV ledger. The ledger records every
plume tag at `TPCORE_ENTRY`, `PRE_QCKXYZ`, `POST_QCKXYZ`, and
`TPCORE_EXIT_POST_RESET`. It includes global plume/dry-air mass, boundary
deltas, negative-state statistics, and the actual Qckxyz correction-event
count. No tracer tendency, source, operator ordering, or `LFILL` setting is
changed.

Use the corresponding manifest environment exactly (in addition to the
checkpoint environment):

```bash
export GC_PLUME_TPCORE_BUDGETS=1
export GC_PLUME_TPCORE_BUDGET_RUN_ID=stage1-tpcore-causality-1thread-20190101
export GC_PLUME_TPCORE_BUDGET_MANIFEST_ID=PLUME-012-phase-a-v1
export GC_PLUME_TPCORE_BUDGET_FILE=./OutputDir/plume_tpcore_budget_v1.csv
```

Validate each completed control without treating the known transport mass gain
as a science pass/fail result:

```bash
python plume_transport/validate_tpcore_budget.py "$manifest" \
  --report "$rundir/tpcore_budget_validation.json"
```

The report requires all ordered boundary records, reconciles entry/exit with+C0/C1, and applies the frozen V2 normalized column-L1 `BudgetTransportFull`+to checkpoint transport check. It reports the global budget residual rather+than treating cancellation-prone diagnostic global sums as exact equality, and+writes `first_nonconserving_boundary` for each tag. After both controls pass+their individual diagnostic checks, compare them using the frozen tolerances in
the manifest:

```bash
python plume_transport/compare_tpcore_budget_threads.py \
  "$one_thread_ledger" "$eight_thread_ledger" \
  --relative-tolerance 1e-9 --absolute-tolerance-kg 1e-9 \
  --report "$comparison_report"
```

The short child manifests are resolved against the frozen V2 manifest by
`manifest_utils.py`; `prepare_run.py` supports this inheritance directly.
Before any build or run, copy the parent V2 source field byte-for-byte into
each new run directory, regenerate/check the zero restart, and run the
GEOS-Chem run-directory audit.

## PLUME-012 Phase-B v2 diagnostic staging

The Phase-B source patch retains the Phase-A `plume-tpcore-budget-v1` parser
for completed evidence and adds `plume-tpcore-budget-v2` for future LFILL A/B
controls. V2 adds `qckxyz_invoked` and emits six ordered boundaries per tag:
`TPCORE_ENTRY`, `PRE_QCKXYZ`, `POST_QCKXYZ`,
`PRE_QPTR_NEGATIVE_FLOOR`, `POST_QPTR_NEGATIVE_FLOOR`, and
`TPCORE_EXIT_POST_RESET`. The pre-floor record follows the polar-copy step;
the post-floor record isolates the existing `q_ptr < 0 -> 1e-26` adjustment.

The transport template contains one
`__PLUME_TPCORE_FILL_NEGATIVE_VALUES__` token. `prepare_run.py` replaces it
with the manifest's checked boolean and parses the rendered YAML before it is
written. Do not hand-edit an alternate transport template or a prepared run
directory. The Phase-B execution result is recorded separately in the project
vault; this repository note does not authorize another run or a production
configuration change.

## PLUME-012 Phase-D0 donor inventory

The completed Phase-D0 manifests are
`stage1-tpcore-donor-inventory-1thread.yml` and
`stage1-tpcore-donor-inventory-8thread.yml` in the project vault. They add the
runtime-gated `plume-tpcore-donor-events-v1` CSV as a companion to the v1 cell
event ledger. It records full-column state only for `QCK_BOTTOM` events after
native top/interior Qck handling and immediately before the native bottom
correction; it never changes the correction or tracer state.

The donor gate requires the cell gate. Use the manifest environment exactly:

```bash
export GC_PLUME_TPCORE_CELL_DIAGNOSTICS=1
export GC_PLUME_TPCORE_CELL_DIAG_FILE=./OutputDir/plume_tpcore_cell_events.csv
export GC_PLUME_TPCORE_DONOR_DIAGNOSTICS=1
export GC_PLUME_TPCORE_DONOR_DIAG_FILE=./OutputDir/plume_tpcore_donor_events.csv
```

After the existing budget and cell validations pass, validate and compare the
donor files with the frozen tolerances:

```bash
python plume_transport/validate_tpcore_donor_diagnostics.py \
  "$cell_ledger" "$donor_ledger" --report "$donor_report"
python plume_transport/compare_tpcore_donor_diagnostics_threads.py \
  "$one_thread_donor_ledger" "$eight_thread_donor_ledger" \
  --relative-tolerance 1e-9 --absolute-tolerance 1e-9 \
  --report "$comparison_report"
```

The validator distinguishes a strictly nonnegative full-column residual from a
roundoff-limited residual that is feasible within the declared tolerance. A
materially unfillable column remains a separate failure/flag design case; this
diagnostic does not implement a donor redistribution. Child manifests that set
`source.reuse_v0_generated_source: true` must receive the frozen source as a
byte-for-byte copy. `generate_source.py` intentionally rejects regeneration of
that input because its case metadata would change the source hash.

For the operator-off V0 case, `validate_run.py` treats the integrated HEMCO and
GEOS-Chem Budget diagnostics as the conservation ledgers. The burden and layer
profile reconstructed from the end restart are reported separately: the plume
mixing ratios are not pressure-rescaled when transport is disabled, while the
restart's `Met_DELPDRY` is archived at the interval endpoint. This endpoint
exception must not be inherited by later operator-enabled cases.

## PLUME-012 QCK_BOTTOM remediation staging

The staged v1 remedy moves QCK_BOTTOM to qck_positivity_mod.F90. It first
validates all eligible donors above a negative bottom cell, then withdraws from
nearest to farthest only when the entire column can close exactly or within its
declared numerical tolerance. An immediate donor that is sufficient retains
the native result. A materially unfillable column or materially negative donor
stops before normal model output; it is never silently converted into tracer
mass.

The default-off qck_bottom_regression CMake target covers interior
conservation, immediate and farther-column donors, a declared roundoff
closure, an unfillable column, and a negative-donor precondition. It has been
staged only. No build, allocation, executable test, or GCClassic run is
authorized by this source note.

Runtime-gated cell and donor ledgers now emit v2 records for future approved
remediation controls. Their v1 parsers remain available for the frozen D0
evidence. V2 preserves the immediate-donor measurement and adds the correction
policy, outcome, donor count, full-column withdrawal, declared roundoff
closure, and tolerance.

## FIREX-AQ optical observation contract

`validate_firex_aq_inventory.py` is a read-only, fail-closed validator for the
frozen FIREX-AQ logical inventory. With only `--manifest` it validates the
exact 405/532/664 nm contract, 23-flight R3 merge list, and derived-product
stops. With `--data-dir` it additionally verifies ICARTT filenames/headers and
emits byte size and SHA-256 provenance; it never transforms science rows. An
`STP` label does not pass by itself: authoritative numeric standard
temperature and pressure values are required.
