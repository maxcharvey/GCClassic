# FINN/GFAS height scaling: bachelor sensitivity experiment

Branch: `feature/finn-gfas-height-scale-14.8`, starting from the accepted
FINN/GFAS refresh-fix wrapper `6581a43b`, GEOS-Chem `653318269`, HEMCO `c508376`.
The accepted production checkout and active campaign runs remain separate.
Science gate: CONSISTENT for an exploratory height sensitivity, not a
physically calibrated correction or a new default.

## Method and scope

Set `FINNv25_GFAS_height_scale` under extension 165 to **0.8, 1.0, or 1.2**.
The default is 1.0 and a missing option also selects 1.0. Any finite positive
factor is supported, subject to the model-top guard. Nonidentity factors
require `FINNV25_GFAS_PROFILE: true` in the configuration helper.

The existing prepared `cofire_3d` reference is read/mapped by HEMCO and
normalized on the model grid exactly as in the accepted hybrid. Supported
profiles then undergo `z_new = factor * z_old`, in metres above the **current
model surface**, using cumulative `HcoState%Grid%BXHEIGHT_M` layer depths.
Those values are layer thicknesses, not MSL altitudes; terrain is not
subtracted. Each source bin is assumed uniform per unit height. Its mass is
conservatively distributed by overlap between its scaled height interval and
the receiving model layers. The transformed weights are applied to all
unchanged FINN species columns using the existing conservative allocation.

This scales both centre and width of a model-grid representation of the
installed GFAS profile. It does not reconstruct the continuous Gaussian,
rerun PRM/IS4FIRES, edit MAMI/APT, or add another forest correction. Existing
producer/mask/datum uncertainties (ISSUE-035) and local-date/UTC-day pairing
remain. Coarse receiving layers can obscure a 20% displacement; diagnose
actual allocated heights rather than claiming exact 20% changes in binned
moments or fraction above PBL.

Factor 1.0 bypasses remapping, including geometry checks, retaining accepted
weights bitwise. Zero-reference support classification and its prescribed
`legacy_65_35_l15` fallback are untouched by every factor. No emission mass,
species/proxy ratio, input file/date selection, diurnal timing, meteorology,
chemistry or GFAS extension112 behavior is changed. Profiles are evaluated
against current model-layer depths at every existing prepare call.

Positive fraction shifted above the model top is **fatal**, with the column,
status and overflow fraction reported. No mass is clipped or renormalized
back into the domain. Invalid factors, nonfinite/negative weights and invalid
layer geometry also fail. Only bounded floating-point residue is assigned to
the largest receiving bin. Missing required input remains a hard error.

## Configuration

For a copy of an already accepted WE-CAN/FIREX hybrid, use the **height-only**
mode. It changes one option, preserves custom inventory paths and the existing
fallback, and creates `HEMCO_Config.rc.before_height_scale`:

```sh
python scripts/configure_finn_profile.py COPIED_HYBRID_RUN_DIRECTORY \
  --height-scale-only --height-scale 0.8
```

For a separately staged hybrid run with a verified hour-valued TIMEZONES file:

```sh
python scripts/configure_finn_profile.py NEW_RUN_DIRECTORY \
  --auxiliary './GFAS/$YYYY/$MM/GFAS-smoke-$YYYY$MM$DD.nc' \
  --fallback legacy_65_35_l15 --height-scale 0.8
```

Use `--height-scale 1.2` for the higher case and 1.0 for baseline. The helper
backs up HEMCO_Config.rc and rejects overwriting an earlier backup. Rebuild
from this branch; an old accepted executable ignores the new option and must
not be used for scaled cases. Manually editing only the new factor in an
already accepted hybrid layout retains all its other settings.

## File cascade and validation

- HEMCO: pure `FINN_Scale_Height` kernel plus option/prepare integration in
  `hcox_finn_profile_mod.F90`. No new source files or CMake changes.
- GEOS-Chem: neutral options in fullchem/aerosol HEMCO templates.
- Wrapper: configuration helper/CLI, strict kernel tests, configuration tests,
  this design/method note, and bounded validation receipts.
- Verify analytic unequal-layer overlaps, independent CDF expectations, 47/72
  levels, surface/top boundaries, sparse/multimodal profiles, positivity,
  closure, invalid inputs and the identity bypass with strict Fortran checks.
- Full-model qualification must compare default/missing-option and explicit
  1.0 against the accepted binary; compare 0.8/1.2 all-species source columns,
  unchanged fallback, layer placement and source closure at the existing
  `2e-6` gate. Preserve native-source oracle `5e-5` where applicable. Boundary
  refresh/seasonal qualification remains a separate launch requirement.

## Seasonal design (not launched by implementation)

WE-CAN: May1–October1 2018; FIREX-AQ: June1–October1 2019. Reuse each accepted
initial restart, inventories, met, diurnal settings, scheme4, global2x2.5/47L,
RRTMGoff and flight sampling. Apply scaling from the original season start,
not a campaign-date continuation. Two new seasonal cases per campaign; reuse
accepted baselines only after regression proves identity. Full seasons retain
monthly broad HISTORY output and may add explicitly scoped placement output.
No seasonal jobs are submitted as part of branch implementation.

Student analysis: supported/fallback FINN mass, emission-weighted height and
spread, above-PBL fraction, matched aircraft CO/OA/BC, vertical plume placement,
surface concentrations and available BrC/optical observations. Use common
flight points and observation-based plume selection. Height sensitivity can
compensate for inventory bias; improved agreement does not establish a better
GFAS height algorithm or demonstrate full-chemistry spinup convergence.

## Bounded implementation acceptance, 14 October 2026

GNU12 Release/fullchem/REAL8/RRTMGoff build passed. Strict kernel tests passed
26 original-profile assertions and 62 height-scaling assertions. Nine
configuration tests and two fire-template tests passed. Height-only edits
were also checked against both actual accepted WE-CAN/FIREX configurations:
after removing the new option, every original byte is retained.

Five matched full-chemistry one-hour runs (2018-08-01 00–01 UTC, 16 threads,
global2x2.5/47L, identical accepted August1 restart) completed normally:
accepted executable, new executable with missing option, explicit1.0,0.8,1.2.
Default and explicit1.0 match accepted HISTORY/HEMCO/endpoint-restart numeric
arrays exactly in **2,838 field comparisons**. All39 FINN species retain
identical source fields and close columns/layers to at most **1.625e-7**, below
the unchanged **2e-6** gate. All195 case/species fallback layer comparisons
match exactly. CO cumulative profile ordering passes; at the 1e-5 displacement
threshold, lower moves453 of840 supported columns and higher moves840 of840.
Compression confined within one model layer can remain invisible in its
emission fractions; expansion can spread a source bin into the next layer.

Receipts and logs:
`runs/validation/BRC_148_FINN_GFAS_HEIGHT_SCALE_20261014/`, including
`HEIGHT_SCALE_ACCEPTANCE.json`, `CONFIGURATION_ACCEPTANCE.json`,
`BUILD_RECEIPT.json`, `STAGING.json`, independent reviews and allocation logs.
Rebuilt binary SHA256:
`b18cb33671db6938af79b6a52aaa7bad807720ef8f820b2759873aa4f5dc3dc4`.
The binary was built before the implementation commits; the compiled Fortran
hashes remain unchanged after committing. Embedded version metadata retains
base/dirty labels; final branch pins are provenance, not an embedded-version
claim. The original accepted binary and production checkout remain intact.
The output checker caps per-variable NetCDF chunk caches at64KiB, so caches
for hundreds of restart/HISTORY fields cannot accumulate without bound.

This qualifies the new operator and neutral default for the stated fixture.
Daily/month-boundary refresh and season-start qualifications are required
before new sensitivity seasons. No new seasonal simulation has been launched.
