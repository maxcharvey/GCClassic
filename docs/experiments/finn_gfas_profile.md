# FINN mass with a prepared GFAS vertical profile

Experimental branch `feature/finn-gfas-profile-14.8`, based on integration/brc-14.8.0 (e110bb7). This is a controlled injection sensitivity, not an observationally qualified default.

Enable FINNv25 and extension165, disable all competing fire inventories including GFAS112, set `FINNV25_GFAS_PROFILE: true`, and set the legacy FINN fraction/levels to zero. Fullchem and aerosol templates include the new options and auxiliary rows, default off. `scripts/configure_finn_profile.py RUN_DIR --auxiliary PATH --timezone-hours HOURS_FILE` adapts an existing run's FINN block and writes a backup. Check inventory configuration before use. The prepared input path may include HEMCO date tokens.

`cofire_3d` is remapped layer by layer and placed on levels1–36 by upstream HEMCO. Normalize its model-column fluxes to weights; multiply every evaluated FINN species column, including CO, by those weights. FINN's units, diurnal factors, BrC proxy ratios and molecular-weight correction remain unchanged. Do not apply the FINN diurnal factor to the auxiliary shape again. The online code neither reads raw height nor computes plume rise. The installed GFAS profile's generator/forest correction remains independently unverified.

A present zero-reference column invokes `FINNv25_profile_fallback`: `pbl` (normalized FRAC_OF_PBL; default), `surface`, or `error`. Fallback is needed only where FINN emits. Missing files/variables and invalid evaluated reference data are fatal; HEMCO's recognized missing-value convention becomes zero support. Source fields must be finite and nonnegative. Stable normalization and a deterministic rounding-residual assignment preserve each FINN column to floating-point precision.

Manual two-dimensional HEMCO metrics, all kg/m2/s and per configured species, are `FINNProfileSource_NAME`, `FINNProfileFallback_NAME`, `FINNProfileTerrain_NAME` (zero for this method), and `FINNProfileAbovePBL_NAME`. Source independently evaluates universal scaling on a copy of FINN input; other metrics use actual post-scaling emissions. Metrics overlap and are not a partition. Normal extension165 three-dimensional emission diagnostics must be enabled alongside these metrics for independent closure checks. Metrics are updated with zeros on source-free calls, preventing stale fluxes.

This is model-grid profile transfer, not individual fire matching. FINN uses local fire dates whereas GFAS daily means use UTC days; same-date matching is a stated approximation. Assess adjacent GFAS-day offsets before physical validation (stage shifted auxiliary files labelled with the model date and retain both dates in metadata). Prepared profiles inherit preprocessing and possible forest corrections; comparing them with unscaled height reconstructions changes more than distribution shape.

Build with the established GNU12 Release/fullchem/OpenMP/RRTMG-off configuration. `tests/finn_profile/run.sh ABSOLUTE_BUILD_DIR` compiles strict pure-kernel tests. Run it and full-model validation inside a compute allocation. Unit/source closure does not establish transport conservation or observational realism. The prior FT-retention transport issue is independent.

HEMCO limits base-emission rows to 255 characters before comment removal. Use short run-local symlinks for long FINN and auxiliary input paths; the configuration helper rejects auxiliary rows that exceed this limit.

## WE-CAN monthly sensitivity

Daily FINNv2.5 rows must use `RF`, including ordinary and BrC proxy rows in
both injected and surface modes. In this HEMCO version `EF` sets a read-once
flag: the annual file's initialization-day slice remains cached throughout
the run. `EFY` does not set that read-once flag, but exact-hour matching rejects
a non-midnight startup against a daily00UTC record. The auxiliary GFAS
reference therefore uses `RFY` (required, simulation-year daily range), selecting
the same daily mean throughout its UTC day without interpolation. Original
GFAS emission rows and archived midnight precision controls are unchanged.
Preflight must validate one correctly dated00UTC record in every required file. The helper rejects stale FINN templates; the
injection extension also rejects effective read-once NetCDF containers.

Hybrid extension diagnostics accumulate source, column, layers and placement
metrics in HEMCO double precision, then snapshot to the existing float32
output interface. This avoids independent monthly float32 summation drift.
It does not alter emissions, diagnostic update counters, output units or
averaging windows. Other extensions and disabled hybrid diagnostics retain
their original accumulation path. The cellwise source-closure gate remains
`2e-6`. `tests/finn_profile/test_diagnostic_accumulation.F90` exercises the
actual HEMCO routines using captured fields over 2232/2160 updates, repeated
retrieval and subsequent interval reset; this is not a reconstruction of the
historical seasonal timestep sequence.

`stage_wecan_finn_gfas.py --output-root NEW_ROOT --timezone-hours HOURS_FILE` requires a fresh destination.
Use `--season-only` after separate bounded acceptance. Never stage over the original season. Date-refresh acceptance must compare
the selected daily inventory and actual atmospheric source delivery; correct
allocation of a cached wrong date can still pass source closure.

Explicit `--fallback legacy_65_35_l15` uses the existing pressure-weighted fire injection routine with elevated fraction 0.35 and 15 levels, only for FINN-emitting columns without GFAS support. Invalid PBL/pressure or insufficient levels remain fatal. Default PBL fallback, disabled-option behavior and supported profiles are unchanged. This is not a physically validated default.

Use `configure_brc_deposition.pl --monthly` for the 71 parent deposition/process fields. All seasonal diagnostics use monthly means; restarts are monthly instantaneous and PlaneFlight retains point sampling. FSOAP is included in concentration and process budgets but is non-depositing.

Read-only regression tools `scripts/audit_finn_refresh_cases.py` and
`scripts/audit_finn_daily_source.py` check the isolated case suite and native
daily source respectively. The latter requires every complete configured UTC
day, exact hourly start timestamps, the recorded harmonized proxy contract,
and the 2x2.5/47L grid. Its spherical-overlap source oracle has a separate
`5e-5` spatial mass L1 gate for native-coordinate/regridding roundoff; this is
not the `2e-6` cellwise source/layer/column conservation gate. The model-case
audit verifies bitwise precision-only restart equivalence and legacy-fallback
restart equivalence, all39 species, missing-background policy and rejection
of stale read-once configurations. The month-boundary fixture initializes from
a time-relabeled August restart solely to test emissions file/date refresh;
its atmospheric concentrations are not qualified simulation results.

## TIMEZONES input units

The installed Vohra2017 `UTC_OFFSET` field is in minutes. HEMCO's `count`
configuration preserves those numbers, whereas this pinned clock floors them
as hours and accepts only `[-12,+13]`; most nonzero minute offsets therefore
trigger longitude-bin fallback. This is a separate inherited diurnal-phase
issue. `prepare_finn_timezones.py --input RAW_FILE --output NEW_HOURS_FILE`
creates a versioned copy dividing valid offsets by60, preserving fill masks,
all12 monthly dates and coordinates. It records raw/derived SHA256 and
conversion error. The helper CLI rejects minute-valued files before writing
a backup, and the seasonal stager requires a verified hour-valued file.

The existing categorical area/modal remap, floored integer offsets, supported
clock range and longitude fallback remain unchanged. These constraints still
apply to fractional or out-of-range offsets. The phase correction affects
other inventories with local-time scaling as well as FINN; it must be tested
separately from precision-only restart equivalence. Complete UTC-day source
mass is preserved because each fixed daily offset samples all24 mean-one
diurnal coefficients. This does not resolve the FINN local-date/GFAS UTC-day
pairing approximation. `audit_finn_hourly_inputs.py` independently checks the
selected monthly timezone map, clock policy, exact native CO date/phase and
the normalized installed36-layer GFAS profile; producer/height physics remain
unqualified.
