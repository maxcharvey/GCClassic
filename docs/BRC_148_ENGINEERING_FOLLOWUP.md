# Engineering follow-up — 2026-09-21

Scope: retain current organic-copy optics and chemistry; validate outstanding
engineering issues, add FAST-JX compatibility and existing-inventory coverage.
No new optical constants or parameter promotion. The August 2018 GFAS
14.7/14.8 comparison is an end-to-end configuration comparison, not an
attribution experiment. It uses the established 2x2.5/47L MERRA2 grid and
WE-CAN flight sampling; legacy 30% FT is a requested sensitivity.

## FAST-JX source review

Core commits `3c6973d` and `0fff6bd` add the missing fullchem input path and
fix dry DBRC routing into Fast-JX's online optical-table solver. Mapping a
dry MIEDX record alone is insufficient: the solver reads the online LUT by
the aerosol/RH slot populated in `fjx_interface_mod`. DBRC now selects RH
slot 1; other aerosols retain their ambient RH slot. No optical table edits.

Independent cascade review (main agent, not implementer): PASS. Dimensions
unchanged (AN=67, NRHAER=11, NRH=5); per-aerosol stride remains NRH; new
IR_OPT is assigned in-loop and OpenMP-private; no new compound array guards,
diagnostics, species, or database entries. Existing module build ordering
supplies the pure RH selector. Tests cover all 11 bins and five RH values,
and organic mapping against the actual Fast-JX NAA=56 table header.
Pure Fortran map/RH-selector tests pass on the allocated compute node.
Fullchem FAST-JX configure is blocked by the upstream Hg-only build guard.
The legacy input bundle also has only 166 J2J entries (JVN_=167), whereas
current fullchem requires entries through 177. Its spectral input format is
not interchangeable with Cloud-J v8. Do not remove the guard, copy the newer
data blindly, or claim issue #25 closed from this source fix. Cloud-J remains
the August comparison backend; an experimental FAST-JX data adaptation needs
separate approval and full mapping validation. The Cloud-J/RRTMG Release build
has passed. The fresh binary also passes the paired QFED2 runtime test below;
this does not qualify the disabled FAST-JX backend.

## Acceptance workflows

`prepare_brc_engineering_matrix.py` stages seven independent cases from the
archived published executable: positive GFED injection, schemes 0–4, and a
24-hour RRTMG smoke. The same executable/config/restart hashes are checked.
The rate checks require instantaneous diagnostics, not products of separately
averaged lifetimes and rates. Scheme 2 retains its existing finite 1e8-second
cap above 1 km; only scheme 0 is an exact zero-bleaching control.

The first staging at 2019-07-01 01:00 failed during model meteorology
initialization: canonical NEXTDAY I3 reads requested 01:00 from next day's
three-hourly MERRA2 file. The failed attempt is preserved. A new matrix uses
the original 00:00 cold restart on the meteorological time grid; six-hour
scheme runs exercise newly emitted BrC. This is not a spun-up science test.

The original runner used `--dry-run`, copied from a stale source comment;
the actual accepted switch is `--dryrun`. The unrecognized switch initiated
normal model execution. A subsequently interrupted midnight attempt is
preserved in `attempt01_bad_dryrun_flag`; no scientific output from it is used.
The runner now requires the explicit dry-run banner and rejects any NetCDF
output before normal execution. Five regressions cover this CLI contract.

The corrected midnight positive-injection case completed successfully:
`BRC_BASE_GFED_ONLINE_INJECTION_20260921`, executable SHA256
`aaba4936a6c12710f6400f6961dd3491173e6263e1f5cc66cefa3c92713cc962`.
All nine fire profile/column pairs and BrC proxy ratios pass the 2e-6 relative
gate; PBRCPOA's column error is 2.24e-7. Its above-level-1 fraction is 0.8923
(this is NOT an above-PBL fraction). Independent review accepts the result
for inventory profile/column closure, not physical/global mass validation.
The standard BioBurn names were still missing from the shipped templates;
these have now been added for all four proxies, with inventory-selector
instructions and an exact-pair static regression. A separate fresh one-hour
GFED case using binary `30377e1d` completed normally; all eight standard aliases
are finite, positive and exactly equal to the existing fire profile/column
fields. Maximum profile-sum error is 2.57e-7, including positive elevated PBRC.
The [alias audit](validation/2026-09-21/bioburn_aliases.json) and independent
output review pass, satisfying issue #20's Classic/fullchem acceptance.

All five six-hour scheme cases completed normally with identical executable,
restart and configurations apart from `bleach_scheme`. The
[scheme audit](validation/2026-09-21/scheme_matrix.json) and independent review
pass: zero transfer in scheme 0; one-day lifetime in scheme 1; both existing
lifetime regimes in scheme 2; bounded spatially varying, distinguishable
schemes 3/4. Every acknowledged dry-run and model log reports its selection.
This satisfies issue #17's engineering gate, not parameter promotion. The
separate 24-hour radiation case also completed normally. Its four exact
six-hour snapshots pass the [day audit](validation/2026-09-21/day_smoke.json)
and independent review: active FFOC concentrations/conversion; finite positive
BrC AOD and BRC/BRCT/PM/DU optics at all three wavelengths; distinct PM/BrC
masks and finite radiation fluxes. Together with the earlier one-hour
RRTMG-on/off builds and runs, this satisfies wrapper issue #7's engineering
matrix. The day uses archived binary `aaba4936`; the later fresh-binary GFED
and QFED one-hour runs are recorded separately, not relabeled as day tests.

The first day auditor incorrectly requested HISTORY placeholders `WL1/2/3`
as netCDF field names. The actual output expands these to `527.1nm`, `550nm`,
and `693.5nm`. The failed audit is preserved, output was not changed, and a
new full four-snapshot synthetic regression checks both the correct names and
rejection of placeholders/duplicate times. All three AOD wavelengths are now
required, not only the first.

## Existing fire inventories

See [selection and diagnostic instructions](BRC_FIRE_INVENTORIES.md).
QFED2 now has a default-off harmonized BrC proxy option. The paired one-hour
proxy-off/on runs completed normally using fresh Cloud-J/RRTMG executable
SHA256 `30377e1d0823f99a1d6a2806a23954ab16eccc7555495076dfe28e510e52ed8d`
(wrapper build origin `f30a54a`, core `b34f550`, HEMCO `c06052a`, Cloud-J
`f78dca8`). Both cases keep BrC chemistry enabled, the same inputs and QFED's
existing vertical partition; only the proxy switch differs. CO/BC are exactly
unchanged, OC partition closure is 9.62e-8, and profile/proxy errors are below
2.83e-7 (gate 2e-6). The [paired audit](validation/2026-09-21/qfed_pair.json),
[BrC/RRTMG audit](validation/2026-09-21/qfed_brc_smoke.json), and independent
finite-field review pass. This is not an inventory-attribution experiment or
total fire-carbon budget. FINNv2.5 has source/static support but no new runtime
qualification because its configured canonical input data are absent locally.

## August 2018 comparison staging

`prepare_brc_fastjx_smoke.py` stages a separate one-hour FAST-JX case with
JValues. It does not copy a Cloud-J executable or submit a run. Both workflows
require independent preflight and compute-node execution.

`stage_gfas_month.py` downloads unmodified official native GFAS v2026-06
daily files into a new private directory, including the next-month boundary.
URL, ETag, size and SHA256 are recorded; numeric profile QC is separate.
August 2018 plus September 1: 32 files / 320,046,373 bytes staged. This does
not yet establish that the month-long model runs are ready or completed.
All 32 files have passed native CO profile/column numeric QC, including
finite/nonnegative values and nonzero elevated emissions.

August staging is deliberately not launch-ready. Full transported-species
coverage finds 274/277 fields for 14.7 and 274/278 for 14.8 in the archived
August-1 restart. Both lack PBRCPOA, FFOCPI and FFOCPO; 14.8 also lacks MDL.
Explicit cold initialization versus a July spinup is awaiting the user's
choice; no derived restart or month-long run has been created. The archived
restart originated in a GFED run, which is another comparison caveat.

The 14.7 draft was repaired to retain all 31 legacy GFAS mapping rows
(30 targets, including both PRPE source fields), residual OC and complete gas
chemistry inputs. All 23 distinct source variables were verified in every one
of the 32 native daily files; units/shapes and numerical scalar identities
pass. Original partial drafts are preserved. The legacy GFAS shared-injection
extension is resolved by name, set to 30% FT over 15 levels, and cannot also
emit from the direct surface block. The 14.8 case uses native variable-height
GFAS. Both keep the existing optics and use Cloud-J/RRTMG and scheme 4.

The isolated 14.7 reference was first frozen at wrapper `c2bbfe2`
(manifest-only child of `25a81c2`) and core `c72cbb3`. Its build-optimized local
derivative is wrapper `390be1fb7c952924d9b3d536d650a1a34ae0d41d`, core
`64209100986ad45144b3966cbb7899a5e05d431a`; HEMCO `17d31b9`, Cloud-J
`f33a1b0`, HETP `2a99b24`, and KPP `eeee895` are unchanged. Only
`GeosRad/CMakeLists.txt` differs from the base core: the exact 14.8 GNU
Release/RelWithDebInfo per-source `-O1 -fno-unroll-loops` workaround for the
two large RRTMG coefficient initializer files, plus Release-only `-g0` for
those same files to suppress pathological debug-information generation.
The extra `-g0` does not apply to Debug or RelWithDebInfo. No Fortran,
coefficient values or science parameters changed; bitwise equivalence to the
previous build is not claimed. The original O3 and intermediate O1-with-debug
build attempts were interrupted and their logs preserved. This is a local
independent source copy, not a mutable donor
symlink; the original 14.7 worktree is untouched. The final configure and
Cloud-J/RRTMG Release build pass. One-hour runtime qualification remains
pending the restart-initialization choice and independent run-steward gate.

Broad HISTORY output is monthly (`00000100 000000`), with daily RRTMG and
BrCDiagnostics (`00000001 000000`); `00010000` would incorrectly mean a year.
Both corrected HISTORY files pass calendar-aware cadence checks. Planeflight
uses the existing 20 August WE-CAN sampling dates and 40 requested fields,
including the shared BrC/FFOC/CO/BC/OC and meteorological diagnostics. Retain
the known August-26 sampling gap. Profile comparisons must match sampled
timestamps/locations/pressures; they cannot isolate a version effect from the
different injection schemes or eliminate initialization effects.

Independent availability review finds all six configured MERRA2 families
(`A1`, `I3`, `A3dyn`, `A3mstE`, `A3mstC`, `A3cld`) for all 31 August days and
the September-1 boundary. All 20 planeflight symlink targets resolve. This
does not replace the final run-steward review of the executable and restart.

## Regression record

The final wrapper unit suite passes 86 tests. QFED parsed effective-row and
numeric-chain checks, static wiring, and both standard BioBurn diagnostic
template tests pass. These checks supplement the model outputs above; none
changes optical tables or grants physical calibration of the current proxies.

The new `compare_planeflight_profiles.py` validates full input-schedule key
coverage, timestamps and coordinates (including longitude normalization),
identical schedule hashes, named chemical fields, finite/nonnegative values,
and paired pressure-bin summaries. It rejects nonportable `TRA_*` fields and
does not assign chemical units to met/AOD outputs. Nine synthetic tests pass;
a self-pair of 149 existing August-1 legacy samples also passes with zero
differences. That self-test is explicitly NOT a 14.7/14.8 result. See the
[August analysis contract](BRC_AUG2018_COMPARISON.md) for the eventual command.

## Publication and issue state

Code-tested/published wrapper `49f77cbaeafa5cc6b98d21fdafcbfef845cda8c1`
pins core `1f49bbaddffd43dbfec7a4ec1087b13a2c6ced33`; HEMCO `c06052a`,
Cloud-J `f78dca8`, and HETP `df2f942` are unchanged. All seven GCC 10–16
[CI jobs passed](https://github.com/maxcharvey/GCClassic/actions/runs/35659916703).
A completed fresh recursive clone passes the clean/exact/remote-tip contract
and all 86 wrapper tests. The original shared-filesystem checkout twice hit
the checker's 30-second recursive-status timeout; these failed checks are
retained and are not represented as successful local checks. An initial
incomplete fresh-clone attempt is also retained separately from the completed
clone's PASS.

Core #17/#20 and GCClassic #7 are closed with linked evidence. Fourteen issues
remain open; FAST-JX #25 has a published partial-progress/blocker comment.
No new physical optics, chemistry pathways or parameter promotions are claimed.
