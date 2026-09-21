# Open-issue audit for the 14.8 BrC integration

Audit date: 2026-09-21. Branch: `integration/brc-14.8.0` in GCClassic,
GEOS-Chem, HEMCO and Cloud-J. Scope: all open issues in the four
`maxcharvey` development forks, including their comments and linked context.
The initial audit covered 28: GCClassic 6, GEOS-Chem 20, Cloud-J 2, HEMCO 0.
Eleven were closed after the first published validation phase. Three more
were closed after the follow-up: core #17 and #20, and wrapper #7. Fourteen
remain open (core 10, wrapper 3, Cloud-J 1, HEMCO 0). The later
[engineering follow-up](BRC_148_ENGINEERING_FOLLOWUP.md) records additional
acceptance evidence separately, without relabeling earlier run snapshots.

**Accounted for does not mean scientifically completed.** This branch is
an engineering integration, with organic-equivalent placeholder optics.
No issues are automatically closed. The research extensions and physical
qualification gates below must not be advertised as finished.

## Follow-up design and acceptance

Science-advisor review: CONSISTENT for the bounded engineering corrections;
no parameter, emission split, physical optical table or chemistry mechanism
is promoted. See the existing [integration contract](BRC_14.8_INTEGRATION.md).

File cascade, before implementation:

- GEOS-Chem `GeosCore/brc_species_mod.F90`: pure required-species validator;
  wire into `ChemBrC` before allocation or chemistry and add to CMake.
  Only FSOAS, BRCSOA and WTC are chemically required; optional pathways
  remain optional. The online aerosol map can impose additional requirements.
- GEOS-Chem `brc_mod.F90`, `aerosol_mod.F90`, `cldj_interface_mod.F90`:
  correct the one-day darkening comment and distinguish online dedicated
  tables from the default organic tables and the separate Cloud-J mapping.
- GEOS-Chem implementation tests: all eight required-species presence
  combinations, negative IDs, and static error-path regression.
- GCClassic `scripts/check_brc_provenance.py`, JSON template and unit tests:
  require forcing definitions, full source pins, input hashes and explicit
  qualification evidence; never infer physical AAOD from separate means.
- GCClassic `scripts/check_brc_submodule_contract.py` and unit tests:
  verify recursive gitlinks, clean sources, fork URLs and optional remote tips.
- GCClassic CI, integration guide and this ledger: expose the new checks
  and distinguish completed engineering from pending validation/research.
- Follow-up diagnostic-only scope: add paired 2-D columns to the existing
  3-D FSOAP/NPBRC/PBRC/DBRC totals in both Classic HEMCO templates (CESM
  inherits its maintained symlink); exercise GFED paired columns in the new
  smoke run and generalize the fire-output auditor's inventory dispatch.
  This adds output only, not an emission split or injection change.
- Runtime-discovered follow-up: surface GFED supplies a 2-D emission array,
  which HEMCO does not promote into requested 3-D inventory diagnostics.
  Repair only `HEMCO/src/Extensions/hcox_gfed_mod.F90`: allocate its existing
  3-D buffer in both modes, apply the already tested zero-control surface
  profile, and always deliver the 3-D array. Extend the helper and wiring
  tests, preserve the failed diagnostic fixture and run a new retry. Science
  review: CONSISTENT; no physical mass/split/injection-parameter change.

Acceptance: independent Fortran cascade review before compute-node builds;
new and existing regression tests; incremental RRTMG-on/off compilation;
publish submodules before the wrapper and verify a fresh recursive clone.
Existing completed model cases are preserved, not rerun or retroactively
relabeled as tests of newer source. No dimension, stride, OpenMP loop,
species database, diagnostic registration or physics changes are planned.

## Issue-by-issue ledger

"Implemented" below describes engineering acceptance, not calibrated
absorption or forcing. "Partial" and "pending" explicitly remain open work.
Existing four-case smoke evidence is at the core `85907636a` snapshot;
new checks are recorded separately below.

### GCClassic (6)

| Issue | Status and evidence | Remaining acceptance |
| --- | --- | --- |
| [#5 Parameter promotion gate](https://github.com/maxcharvey/GCClassic/issues/5) | Gate retained: no parameter promotion; science records require parameter-review evidence. | Physical values still need regime-specific review; not a completed calibration. |
| [#6 Submodule pins](https://github.com/maxcharvey/GCClassic/issues/6) | Exact gitlinks and fork URLs recorded; recursive clean/pin checker and CI added. | Publication is accepted only after remote-tip and fresh-clone checks below. |
| [#7 Combined validation matrix](https://github.com/maxcharvey/GCClassic/issues/7) | Acceptance PASS: prior one-hour RRTMG-on/off tests plus completed 14.8 24-hour case, four snapshots, active FFOC, finite BrC AOD/fluxes, shifted dust bins and distinct PM/BRC masks. [Day audit](validation/2026-09-21/day_smoke.json). | FAST-JX/fullchem and physical forcing interpretation remain separate open work. Exact per-run source/executable pins are retained; older 14.7 tests are not 14.8 acceptance. |
| [#8 Forcing metadata](https://github.com/maxcharvey/GCClassic/issues/8) | Implemented JSON template, fail-closed checker, tests and required run workflow in `BRC_FORCING_PROVENANCE.md`. | Analysts must supply true definitions and approved evidence; schema validation cannot grant scientific approval. Historical cases keep their original records. |
| [#9 Inventory sensitivity gate](https://github.com/maxcharvey/GCClassic/issues/9) | GFED/GFAS wiring tested; metadata requires inventory-review evidence before science use. | A harmonized inventory/scaling sensitivity and attribution analysis remain pending; the two cold-start smokes are not that analysis. |
| [#10 offAOD/AERONET parity](https://github.com/maxcharvey/GCClassic/issues/10) | Dry-DBRC and wavelength mappings documented and numerically tested online. | 14.8 offline parity with agreed tolerances, RH/operator mapping, AERONET AAOD/AAE/SSA validation remain pending. |

### GEOS-Chem (20)

| Issue | Status and evidence | Remaining acceptance |
| --- | --- | --- |
| [#11 PBRC online AOD](https://github.com/maxcharvey/geos-chem/issues/11) | Dedicated PBRC carrier/bin, optical routing, metadata and finite nonzero runtime AOD implemented. | Physical PBRC LUT qualification is shared with #12. |
| [#12 Real BrC/dBrC optics](https://github.com/maxcharvey/geos-chem/issues/12) | Partial: separate WB/PB/DB table routing and validation exist, default `organic` is portable. | Qualified size/RI/RH/spectral tables and matched Cloud-J records are missing; do not use placeholders for physical forcing claims. |
| [#13 Bleaching defaults](https://github.com/maxcharvey/geos-chem/issues/13) | Partial: runtime selection, bounds and viscosity-aware inherited scheme present. | Global/default promotion and regime-specific persistence validation remain blocked by scientific review. |
| [#14 Expanded RRTMG bins](https://github.com/maxcharvey/geos-chem/issues/14) | Implemented 22-slot mapping, retained seven dust bins, dry DBRC optics and RRTMG runtime. | Physical optical qualification is separate. |
| [#15 BrC masks/HISTORY](https://github.com/maxcharvey/geos-chem/issues/15) | Implemented BRC/BSOA/NPBR/WTC/FSOA/PBRC/DBRC/BRCT masks and HISTORY names; runtime BrC diagnostics pass. | Harmonized physical forcing assessment remains pending. |
| [#16 FFOC integration](https://github.com/maxcharvey/geos-chem/issues/16) | Tracers/CEDS/conversion implemented; original one-hour BrC-on endpoint restarts have nonzero FFOCPI/FFOCPO, BrC-off zeros. Follow-up archives concentrations/conversion directly. | Full source-to-burden budget and no-double-counting one-box test remain pending; a nonzero tracer is not budget closure. |
| [#17 Runtime bleaching switch](https://github.com/maxcharvey/geos-chem/issues/17) | Acceptance PASS: five same-executable 14.8 six-hour cases 0–4; acknowledged dry-runs and runtime selection, expected instantaneous lifetime/rate/transfer behavior. [Audit](validation/2026-09-21/scheme_matrix.json). | No parameter/default promotion; the separate 24-hour radiation gate belongs to wrapper #7. |
| [#18 DBRC dry RRTMG depth](https://github.com/maxcharvey/geos-chem/issues/18) | Implemented dry extinction/SSA/asymmetry at RH=0; nonzero DBRC radiation AOD; no-RRTMG dry-AOD parity. | DBRC physical optics remain unqualified. PBRC is a distinct wet carrier in the current design, not silently reassigned to dry DBRC. |
| [#19 Species metadata](https://github.com/maxcharvey/geos-chem/issues/19) | Split-bin MW/density/optics metadata present and finite outputs verified. | DBRC `Is_HygroGrowth: true` is a documented diagnostic-registration accommodation: its actual mass/optics remain dry. Replacing that accommodation needs a separate registration design. |
| [#20 PBRC emission diagnostics](https://github.com/maxcharvey/geos-chem/issues/20) | Acceptance PASS: eight standard BioBurn/BioBurn3D names added to fullchem/aerosol templates. Fresh one-hour GFED positive-injection run verifies nonzero elevated PBRC and all pairs close within 2.57e-7. [Audit](validation/2026-09-21/bioburn_aliases.json). | Selectors must follow the inventory as documented in the fire guide. Aerosol-only/CESM runtime remains outside this Classic/fullchem test. |
| [#21 BrC HISTORY](https://github.com/maxcharvey/geos-chem/issues/21) | Implemented enabled BrCDiagnostics and split AOD/RRTMG/FFOC template fields; archived BrC fields are finite. | Long-run output cadence must be reset from smoke-test settings. |
| [#22 Mass basis](https://github.com/maxcharvey/geos-chem/issues/22) | Partial: carbon-basis family diagnostics normalize FSOAS/1.8; PM remains OM; FFOC aggregated only once. | One-box/restart budget closure and additive DBRC / SOAP–FSOAP source-overlap qualification remain open. GFAS column closure does not prove total fire-carbon closure. |
| [#23 Reduced species](https://github.com/maxcharvey/geos-chem/issues/23) | Fixed: missing FSOAS/BRCSOA/WTC now returns a named configuration error before allocation/chemistry, instead of silently disabling all BrC. All eight presence combinations and negative IDs tested. | Fullchem aerosol mapping independently requires its canonical bins; this fix does not claim arbitrary reduced mechanisms are supported. |
| [#24 Stale comments](https://github.com/maxcharvey/geos-chem/issues/24) | Fixed the stale 0.25-day comment to the actual one-day value; qualified dedicated online LUT descriptions and separate Cloud-J record mapping. | No parameter change. |
| [#25 FASTJX compatibility](https://github.com/maxcharvey/geos-chem/issues/25) | Source uses NRHAER; organic mapping tests and dry-DBRC online RH-slot correction now pass. Fullchem input-path gap repaired. | Remains open: upstream Hg-only build guard, legacy photolysis capacities/mapping and incompatible newer spectral format prevent fullchem build/runtime qualification. Cloud-J tests do not qualify FASTJX. |
| [#26 AAOD/AAE diagnostics](https://github.com/maxcharvey/geos-chem/issues/26) | Partial: simultaneous RRTMG AOD/SSA are available; provenance rejects derivation from separate time averages. | Stable class-resolved AAOD/AAE products, wavelength-pair regression and qualified physical tables remain to implement/validate. No absorption product is claimed here. |
| [#27 d-BrC/tar balls](https://github.com/maxcharvey/geos-chem/issues/27) | Research/design pending; dry persistent DBRC tracer is an engineering carrier. | Approve species identity, source partition, aging, hygroscopicity, optical parameters and campaign validation; a global fraction is not authorized by the science registry. |
| [#28 BrN/N:C](https://github.com/maxcharvey/geos-chem/issues/28) | Research/design pending. | Choose tracer vs diagnostic vs optical modifier, predictor and observation operator before implementation. |
| [#29 IVOC/SVOC](https://github.com/maxcharvey/geos-chem/issues/29) | Research/design pending. | Inventory/yield mapping, precursor mass basis and OA/OM:OC closure must precede the new chemistry sensitivity. |
| [#30 NO3/aqueous browning](https://github.com/maxcharvey/geos-chem/issues/30) | Research/design pending. Existing N2O5/OA treatment is not this pathway. | Approve precursor/product chemistry, humid/nighttime regime gates and validation before implementation. |

### Cloud-J (2), HEMCO (0)

| Issue | Status and evidence | Remaining acceptance |
| --- | --- | --- |
| [Cloud-J #1 Dimensions](https://github.com/maxcharvey/Cloud-J/issues/1) | Immediate dimensional fix implemented: AN_=67 matches 10+11*5+2 and A_=74 holds dedicated records. | Header-driven dimensions and an upstream PR remain maintenance work; no upstream PR is created by this publication. |
| [Cloud-J #2 PBRC/dBrC optics](https://github.com/maxcharvey/Cloud-J/issues/2) | Organic-mode mapping runs successfully; dedicated WB/PB/DB mapping fails closed without validated records 64–74. | Current v2025-01 data do not supply those qualified records. Generate/qualify tables and run dedicated optical/photolysis validation. |

HEMCO has no open issues in the fork. Its official 3.13 native GFAS
variable-height pathway is retained and exercised by the 14.8 GFAS smoke,
including elevated emissions and paired profile/column closure.

## Follow-up verification record

Core correction snapshot: `d45ab34f08cea5c80938ec8d0abda7dcc0a09496`.
Initial HEMCO: `8195cd9a01cda6f93540329b2f4c19dc3ffc2554`.
Cloud-J: `f78dca88e8767f9885e98a2889e89233ddeedf54`.

Independent Fortran cascade review: PASS. The new helper's nine cases and
static wiring checks pass. Full regression/build/runtime and publication
results are appended after verification, not assumed from this source review.

The first follow-up model run exited 0 and its BrC audit passed. FFOC
concentrations/conversion and dust masks were finite/nonzero, and the four
all-source BrC profile/column pairs closed exactly. All 53 Aerosols and 24
BrCDiagnostics datasets were exactly equal to the earlier GFED/RRTMG run.
However, eight of nine GFED inventory-specific profile/column pairs failed:
surface GFED passed `Array2D`, while HEMCO only fills 3-D diagnostics when
given `Array3D`. Its counter advanced despite the unfilled array, allowing
stale storage to be written (in this fixture, every profile resembled FSOAP).
These failed fire profiles must not be used for emissions analysis.

The bounded HEMCO repair always delivers a 3-D GFED profile. The zero/zero
control copies the original surface flux into layer 1 and zeros other
levels without reading PBL fields. Positive-injection behavior is unchanged;
the helper also rejects negative/nonfinite source flux. The cost is one
3-D grid buffer per GFED instance, now allocated in surface mode as well.
No generic HEMCO diagnostics or native GFAS implementation was changed.
The failed fixture is retained and a separately named retry verifies closure.

Final retry: `BRC_BASE_GFED_ONLINE_ISSUES_RETRY_20260921`, 2019-07-01
00:00–01:00 UTC, global 4x5/47-level fullchem, organic-equivalent optics.
Runtime wrapper `4cd98fbdc248b379b1130a6f83a66173f3a4fd23`, core
`d45ab34f08cea5c80938ec8d0abda7dcc0a09496`, HEMCO
`c06052a2c8d91593ffdf2a383bb47b42bb0ba43f`, Cloud-J
`f78dca88e8767f9885e98a2889e89233ddeedf54`.
Executable SHA-256:
`aaba4936a6c12710f6400f6961dd3491173e6263e1f5cc66cefa3c92713cc962`.

- Model exit 0 and normal end; BrC smoke audit PASS.
- All nine GFED inventory profile/column pairs agree exactly; all four
  all-source BrC profile/column pairs also agree exactly. Proxy-ratio
  maximum relative error is 2.061e-7 (gate 2e-6).
- FFOCPI, FFOCPO and their conversion diagnostic are finite/nonzero.
  Dust AOD/SSA at all three wavelengths and the BASE/PM/DU/BRC/BRCT
  radiation diagnostics are finite, with distinct mask results.
- Aerosols (53 datasets), BrCDiagnostics (24), SpeciesConc (17), RRTMG
  (55), StateMet (19), and final restart (417) are exactly array-equal to
  the first fixture: 585 datasets. The fix changes the faulty fire-profile
  output, not the tested concentrations or radiation.
- 50 wrapper tests PASS; six core implementation checks PASS; updated
  HEMCO CTest 2/2 PASS including real zero-control application with a null
  extension state. Final RRTMG-on/off Release builds PASS. The final
  inventory-label-only auditor correction also passes its eight tests.
- Source/config/optical-table provenance checks PASS before and after
  the run. Allocation 14797431 was released, COMPLETED 0:0 (34m33s).

Full local evidence, including the failed fixture, retry, issue snapshot,
build logs, JSON audits and `MANIFEST.md`, is under
`runs/validation/BRC_1480_ISSUE_AUDIT_20260921` in the BrC project run root.
The native GFAS source is unchanged by the GFED repair; its earlier
variable-height runtime evidence is retained, and the current auditor also
passes against that existing GFAS output (not a new GFAS model rerun).

Publication procedure: push the three modified submodules first, then the
wrapper. Verify remote tips with `check_brc_submodule_contract.py --remote`
and repeat the check in a fresh recursive clone. The final documentation
commit may follow the runtime wrapper pin above; do not relabel that run.

Publication verification succeeded for wrapper `ec79d987` and the final
submodule pins above: remote-tip checks and a fresh recursive clone both
PASS, and all 50 wrapper tests pass in that clone. GitHub Actions then
exposed a test-fixture portability bug: clones do not inherit repository-local
Git author identity, so two negative contract tests could not create their
intentional drift commits. Configure identity inside every temporary clone;
the 11 contract tests pass with system/global Git configuration disabled.
This follow-up changes only the test harness, not model code or run evidence.
