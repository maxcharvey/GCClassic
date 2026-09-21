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
separate approval and full mapping validation. Cloud-J/RRTMG compilation is
in progress, not yet runtime qualification of these new commits.

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
for core issue #20's diagnostic closure, not physical/global mass validation.
Schemes 0–4 and the 24-hour case require separate completed-output audits.

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

August staging is deliberately not launch-ready: the archived August-1
restart lacks PBRCPOA, FFOCPI and FFOCPO, and complete transported-species
coverage still needs checking. Identical cold initialization versus a spinup
is awaiting the user's choice. The legacy shared-injection configuration
must retain its complete gas/aerosol mapping and residual-OC partition.
Broad HISTORY output is monthly (`00000100 000000`), with daily RRTMG and
BrCDiagnostics (`00000001 000000`); `00010000` would incorrectly mean a year.
