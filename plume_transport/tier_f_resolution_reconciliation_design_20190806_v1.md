# FIREX-AQ Tier-F 60-second resolution reconciliation — 2019-08-06 v1

## Scope

This gate mechanically reaggregates the complete sealed direct AOP R2 and SP2
R4 source inventories onto the accepted corrected Tier-E NetCDF's 452 explicit
half-open `time_bnds` intervals. It then reconciles the rebuilt values, counts,
and SP2 dilution states against the existing Tier-E fields.

It does not modify either carrier, promote Tier E, match model output, build
cohorts, calculate scientific statistics, interpret the observations, alter
model source/configuration, or execute GEOS-Chem.

## Frozen inputs

- Accepted Phase-2 primary join:
  `stage1-firex-aq-tier-f-phase2-join-20190806-retry1`.
- Complete sealed AOP and SP2 payloads recorded in the Phase-2 source
  inventory, including records that do not link to an mrg01 carrier second.
- Accepted corrected Tier-E August 6 NetCDF, SHA-256
  `a5aee10424c31d719053614d64c745dec159edfaa7e1556981d87271c1b0a54b`.
- Frozen v1 and v2 acquisition seals and the accepted Phase-2 seal.

Every hash is verified before data are read. Inputs are read-only.

## Time and coverage contract

1. Decode the Tier-E `time_bnds` units exactly and require 452 contiguous,
   non-overlapping, 60-second intervals.
2. Assign a direct source record only when
   `target_start <= Time_Start < target_stop`.
3. Do not nearest-fill, interpolate, duplicate a record, or fall back between
   product families.
4. Classify every AOP and SP2 source record as:
   `tier_e_inside_linked`, `tier_e_inside_unlinked`,
   `tier_e_outside_linked`, or `tier_e_outside_unlinked`.
5. Require all 27,097 records per product to appear once in the accounting.

The complete direct inventory is required rather than only `carrier_join.csv`.
Both products contain one terminal record at `Time_Start=92090` inside the
final Tier-E interval `[92070,92130)` but outside the mrg01 carrier domain.
The SP2 terminal record is valid (`37.68 ng std m-3`, dilution flag `0`).
Dropping it would create a false final-bin discrepancy.

## AOP aggregation

Aggregate `abs_dry_405`, `abs_dry_532`, and `abs_dry_664` independently.
A value is valid when finite and unequal by exact decimal value to the
variable-declared missing value, `-8888` LLOD, or `-7777` ULOD. Finite
negative absorption remains valid.

For each band and interval, retain the ordered source-record IDs, valid count,
float64 arithmetic mean, and the historical Tier-E representation: the
chronological float64 mean cast once to float32. No cross-band complete-case
mask is used.

## SP2 aggregation

For every interval:

- `n_mass_valid` counts distinct finite mass records excluding the
  variable-declared missing value, `-8888`, and `-7777`;
- `n_undiluted` counts jointly valid mass/flag records with flag `0`;
- `n_diluted` counts jointly valid mass/flag records with flag `1`;
- `n_flag_valid = n_undiluted + n_diluted`;
- mass is the chronological float64 mean cast once to float32;
- dilution fraction is `n_diluted / n_flag_valid`, cast once to float32;
- state is `undiluted`, `diluted`, `mixed`, or `missing`; and
- the historical binary flag is `0`/`1` only for pure states and `-127`
  otherwise, with mixed flag `1` only for mixed intervals.

The dilution fraction is source-record occupancy, not a physical dilution
magnitude or correction.

## Reconciliation gate

The pass/fail comparisons cover all 452 intervals:

- valid sample counts are exact integers;
- SP2 undiluted/diluted-derived state, binary flag, and mixed flag are exact;
- missing versus missing is a semantic exact match; and
- every finite reaggregated and Tier-E float32 value has the identical IEEE-754
  bit pattern.

Float64 residuals and float32 ULP distances are reported diagnostically.
They do not create a tolerance or override the exact gate.

## Outputs

- `source_to_60s_bins.csv`: complete AOP/SP2 source accounting and link state.
- `reaggregated_60s.csv`: 452-bin rebuilt and Tier-E values, counts, states,
  equality flags, residuals, and ULP diagnostics.
- `reconciliation.json`: input, coverage, field, and global gate results.
- `run_manifest.json`, `ARTIFACT_MANIFEST.json`, and
  `RESOLUTION_RECONCILIATION_SEAL.json`.

The run is repeated into a fresh root. The three deterministic result files
must be byte-identical before independent results audit.

## Stop boundary

Acceptance releases only the resolution gate. It stops before model matching,
reference-state model conversion, exclusions, cohorts, clusters, support
inventories, statistics, interpretation, model work, and day eight.
