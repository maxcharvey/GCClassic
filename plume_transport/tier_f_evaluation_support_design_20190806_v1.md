# FIREX-AQ Tier-F exclusion and evaluation-support inventories — 2019-08-06 v1

## Scope

This gate applies the already approved v2 membership and minimum-support
rules to the accepted 27,096-row Phase-2 carrier and mechanical match. It
publishes row membership, an exclusion cascade, lexical cluster inventories,
uncertainty/context completeness, and support eligibility only.

It does not calculate observation/model summaries, residual metrics,
correlations, bootstrap intervals, age trends, or scientific interpretations.
It does not rematch rows or run GEOS-Chem.

## Frozen input boundary

Every input is read-only and SHA-256 checked before use:

- accepted Phase-2 carrier, links, and seal;
- accepted Tier-F mechanical rows, summary, validation, and seal;
- direct AMS R3 payload for the already linked AMS source-record metadata; and
- accepted v2 ancillary semantic audit proving the Holmes crosswalk and
  R9/R12 lexical contract.

The carrier and mechanical tables must contain the same 27,096 source IDs in
the same ordinal order. All 35 mechanical rejections remain in the output.

## Token states

Direct ICARTT numeric tokens are classified independently as `valid`,
`missing`, `LLOD`, `ULOD`, or `invalid`. A valid token is a finite exact
decimal unequal to the variable-declared missing token, `-8888`, or `-7777`.
Finite negative AOP absorption is valid. Missing low-signal AOP precision is
not an exclusion.

For linked AMS source records, retain source-record IDs and classify OA,
OA precision, OA detection limit, cloud flag, and size-distribution flag.
This gate does not average overlapping AMS values. SP2 dilution state and its
20%/40% record-level uncertainty label are retained only for valid rBC plus a
binary flag.

## Fixed exclusion cascade

The ordered, non-reordering cascade is:

1. all source-preserved carrier rows;
2. exact direct R9 plus R12 regime/fire/plume/transect metadata;
3. direct R9 `smoke_flag == 1`;
4. finite carrier latitude, longitude, and MSL altitude;
5. accepted frozen mechanical match;
6. valid direct AOP 405 nm absorption;
7. valid direct AOP 532 nm absorption;
8. valid direct AOP 664 nm absorption; and
9. primary exclusion of exact lexical fire IDs `10.1` and `10.2`.

Stage 8 before the special-fire exclusion is `C_abs_all`; stage 9 is
`C_abs_primary`. The special-fire rows remain a named sensitivity and are
never silently discarded.

Derived memberships inherit `C_abs`:

- `C_aae`: observed and model 405/664 nm totals are strictly positive.
- `C_age_nominal`: finite nonnegative FSU `smoke_age`, method code 1--7, and
  exact R9/R12 fire, plume, and transect identities.
- `C_age_uncertainty`: nominal age plus finite nonnegative
  `smoke_age_unc`, accepted Holmes crosswalk, and an explicit stable/crossing
  state for the frozen half-open age bins.
- `C_context`: explicit SP2 and AMS valid/censor/missing states with retained
  QC/uncertainty metadata; age is not required.

Every membership is emitted for both all-fire and primary variants where
applicable. No membership depends on model/observation agreement.

## Age and cluster inventories

Direct FSU `smoke_age` and `smoke_age_unc` are in seconds. Convert each exact
decimal token to hours by division by exactly `3600` before binning or
constructing the envelope; retain both second and hour values in row
provenance. Age bins are `[0,0.5)`, `[0.5,1)`, `[1,2)`, `[2,4)`, `[4,8)`,
and `[8,infinity)` hours. The closed, untruncated
`[smoke_age_hours-smoke_age_unc_hours,
smoke_age_hours+smoke_age_unc_hours]` envelope is stable only when wholly
inside the nominal half-open bin; upper-bound equality and a negative lower
endpoint are crossing.

Top-level cluster IDs are lexical strings:

`2019-08-06|<R9/R12 exact fire ID>|<R12 exact plume ID>`

with exact transect ID nested below. No identifier passes through
floating-point normalization.

## Support inventory

For each cohort/endpoint and each applicable frozen age bin, publish only:

- rows and distinct observation source records;
- unique model states, exact fires, plumes, transects, and top-level clusters;
- nonzero-variation flags; and
- eligibility under the frozen minimum-support table.

Eligibility labels are `eligible` or
`inconclusive_insufficient_independent_support`. The 80% age stability flag is
reported separately as `eligible` or
`inconclusive_age_boundary_uncertainty`. No below-gate threshold is relaxed,
and bins are never merged.

## Outputs and stop boundary

- `row_membership.csv`
- `exclusion_cascade.csv`
- `cluster_inventory.csv`
- `uncertainty_completeness.csv`
- `support_inventory.csv`
- `evaluation_support_summary.json`
- `run_manifest.json`, artifact manifest, and seal

Acceptance requires complete row accounting, exact input pins, deterministic
reproduction, internal aggregation agreement, and independent mechanical
validation. Statistics, bootstrap execution, interpretation, model changes,
and day eight remain closed.
