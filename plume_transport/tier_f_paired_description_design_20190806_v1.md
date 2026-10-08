# FIREX-AQ Tier-F supported paired-description execution design v1

Date: 2026-07-28

## Scope and release basis

This gate operationalizes the already approved Tier-F v2 descriptive
evaluation contract for the accepted 2019-08-06 primary cohorts. It changes
no comparison target, cohort, model match, support threshold, or scientific
method. The science gate is therefore not reopened.

The accepted evaluation-support retry3 seal is the sole release authority.
This execution may calculate:

- raw paired points;
- observed, model, and paired-residual median and IQR;
- paired-residual mean bias, MAE, and RMSE; and
- the same applicable summaries for 405--664 nm AAE.

It must not calculate Pearson or Spearman association, any sampling or
measurement interval, bootstrap draws, age-bin summaries, sensitivities,
percentage or ratio errors, normalized bias, logarithmic error, skill scores,
p-values, or scientific interpretation. It must not rematch observations,
change or run GEOS-Chem, or authorize day eight.

## Frozen inputs and identity

The machine contract pins:

1. retry3 `row_membership.csv`;
2. retry3 `support_inventory.csv`;
3. retry3 `ACCEPTANCE_SEAL.json`;
4. the accepted Tier-F mechanical-match row table; and
5. the accepted Phase-2 carrier join.

All three row tables must contain exactly 27,096 rows in identical
`(carrier_source_record_id, carrier_ordinal)` order, with unique compound
keys. The acceptance seal must be `SEALED-AUDIT-PASS`. Input hashes are
checked before values are opened.

Membership is taken only from the sealed retry3 table. Direct observations
and exact AOP source-record IDs are taken only from the Phase-2 carrier.
Matched model values and model-state indices are taken only from the accepted
mechanical table. No input is edited.

## Endpoints and cohorts

The absorption endpoints are:

| Endpoint | Cohort | Observation | Model |
|---|---|---|---|
| 405 nm | `C_abs_primary` | `aop__abs_dry_405` | `model_abs_405_tot_aop_reference_mm1` |
| 532 nm | `C_abs_primary` | `aop__abs_dry_532` | `model_abs_532_tot_aop_reference_mm1` |
| 664 nm | `C_abs_primary` | `aop__abs_dry_664` | `model_abs_664_tot_aop_reference_mm1` |

Absorption units are `Mm-1` at the direct AOP dry state and model
273 K/1013 hPa AOP reference state. Finite negative observations remain
eligible.

AAE uses only `C_aae_primary` and strictly positive observed and model
endpoints:

`AAE_405_664 = -ln(abs_405 / abs_664) / ln(405 / 664)`.

The AAE paired difference is model minus observation. The 532 nm band is an
independent bandwise check and does not enter AAE. A finite negative AAE is
valid (it can arise from positive endpoints with absorption increasing toward
664 nm) and is retained and counted.

## Dependence, weighting, and numerical conventions

The top-level cluster is the sealed lexical
`flight date|fire ID|plume ID`. Let `K` be the number of contributing
clusters and `n_c` the number of endpoint rows in cluster `c`.

The primary cluster-balanced row weight is:

`w_i = 1 / (K * n_c)`.

Thus each contributing cluster has equal total weight and rows within a
cluster share that cluster's weight equally. The secondary row-weighted
description uses `w_i = 1 / N`.

For reproducible weighted quartiles, sort finite `(value, original row
ordinal)` pairs ascending by value and then original ordinal. The weighted
quantile at `q` is the first sorted value whose inclusive cumulative
normalized weight is greater than or equal to `q`. Quartiles use
`q = 0.25, 0.5, 0.75`; IQR is reported as its two endpoints, not only their
difference. To prevent a binary floating-point accumulation from moving an
exact boundary to an adjacent row, cumulative-weight comparisons use exact
decimal representations of the published float64 weights and decimal
quantiles. Metric arithmetic remains NumPy float64.

For either weighting:

- mean bias is the weighted mean of `model - observation`;
- MAE is the weighted mean absolute paired residual; and
- RMSE is the square root of the weighted mean squared paired residual.

Calculations use NumPy float64 after strict finite-token checks, except for
the deterministic cumulative-weight comparison stated above. Output JSON must
reject NaN and infinity. Rows remain in carrier order in the raw-point table.

## Counts and support enforcement

Every endpoint reports:

- qualifying rows;
- finite-negative observations;
- distinct direct AOP source records;
- distinct model states;
- distinct lexical transects, plumes, fires, and top-level clusters.

For absorption and AAE, the sealed support inventory must state point-summary
and mean-error eligibility for the corresponding primary cohort. The
implementation independently rechecks at least 10 rows and 5 model states for
quartiles, and at least 20 rows and 5 model states for mean bias/MAE/RMSE.

Association remains
`inconclusive_insufficient_independent_support`, whole-cluster intervals
remain `inconclusive_insufficient_independent_support`, and age patterns
remain closed. These states are emitted without calculating the blocked
quantities.

## Deterministic artifacts and acceptance

Each fresh no-clobber root writes:

- `paired_points.csv`;
- `paired_summary.csv`;
- `metric_release_status.csv`;
- `paired_description_summary.json`;
- `run_manifest.json`; and
- `ARTIFACT_MANIFEST.json`.

The primary run requires a fresh independent reproduction. Acceptance
requires byte identity for the four deterministic science-facing outputs,
internal artifact-manifest verification, exact cohort/count agreement,
finite outputs, formula recomputation, proof that blocked fields are absent,
focused and ordinary tests, and an independent validation record. A final
acceptance seal may be written only after those checks pass.

The terminal label is bounded to
`accepted-descriptive-August6-paired-description`. It is not model-skill,
campaign, causal, lifetime, optical-component, or production acceptance.
