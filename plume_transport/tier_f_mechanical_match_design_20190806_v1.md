# FIREX-AQ Tier-F mechanical matcher revalidation — 2019-08-06 v1

## Scope

Re-run the already accepted GEOS-Chem nearest-neighbour matcher on the direct
one-second Tier-F carrier population. This is a mechanical revalidation only:
it does not select observations using AOP, smoke, age, BC, agreement, or any
other science field.

## Frozen inputs and row authority

- The accepted Phase-2 `carrier_join.csv`, SHA-256
  `cb6e7c10129fd23578be5ff175d4956a41ffc0b8892de20b782ec55dad81c911`.
- Exactly 27,096 carrier rows in original ordinal order.
- UTC is `2019-08-06T00:00:00 + Time_Start seconds`; values above 86,400
  retain their August 7 rollover.
- `Time_Start` is integral and `Time_Stop = Time_Start + 1` for every row.
- Horizontal navigation is `Latitude` and `Longitude`.
- Vertical navigation is `MSL_GPS_Altitude`, matching the accepted Tier-E
  NetCDF `alt:SourceVarName`.
- The three accepted exact-band HISTORY files and their frozen hashes in the
  machine contract.

Every input hash is checked before use. Inputs remain read-only.

## Frozen matcher

Reuse, without modification:

- native-CF HISTORY time decoding;
- nearest model time;
- nearest latitude centre and cyclic nearest longitude centre;
- nearest geometric layer centre built from `Met_BXHEIGHT` and `Met_PHIS`;
- 600 s time and 1000 m vertical rejection limits; and
- half-grid audit limits of 1 degree latitude and 1.25 degrees longitude.

All rows are retained. A rejected row carries an explicit reason and no
sampled model absorption. There is no nearest-fill, interpolation, averaging,
agreement-dependent rematching, or post-midnight clipping.

## Model fields and arithmetic

Sample total, BC, BrC, OA, dust, and other dry absorption at 405, 532, and
664 nm, plus model pressure and temperature. Convert accepted ambient-volume
absorption to dry AOP reference volume at exactly 273 K and 1013 hPa using
the accepted operator.

For both ambient and AOP-reference states, require finite nonnegative sampled
values and

`Tot = BC + BrC + OA + Dust + Other`

within `rtol=1e-6`, `atol=1e-8 Mm-1`. Closure failure stops the gate; it never
changes a match.

## Outputs and acceptance

- `tier_f_mechanical_matches.csv`: one row per carrier second with stable
  carrier identity, navigation, match indices/offsets/provenance, and sampled
  model fields.
- `tier_f_mechanical_match_summary.json`: frozen provenance, record inventory,
  rejection counts, offset maxima, and closure diagnostics.
- `tier_f_mechanical_match_validation.json`: independent structural,
  provenance, bound, finiteness, nonnegativity, and closure audit.

Acceptance requires 27,096 ordered output rows, exact frozen hashes, explicit
accounting of every match result, all accepted offsets within the frozen
limits, zero model-field/closure failures, a zero-exit wrapper, sealed
artifacts, and independent results audit. It does not require the historical
85-row Tier-E count or claim that every Tier-F row must be accepted.

As an implementation regression anchor, the wrapper also reruns the accepted
85-row Tier-E collocation with its frozen carrier and arguments and requires
the summary and row CSV to reproduce the accepted SHA-256 values exactly.
Those 85 rows never select, reject, or rematch a Tier-F carrier row.

## Stop boundary

This gate stops before exclusions, cloud/RH screening, dilution state,
cohorts, clusters, uncertainty/support inventories, statistics, scientific
interpretation, model changes or runs, and day eight.
