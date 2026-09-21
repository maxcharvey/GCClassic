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
Compile/runtime qualification is pending; do not infer closure from source.

## Acceptance workflows

`prepare_brc_engineering_matrix.py` stages seven independent cases from the
archived published executable: positive GFED injection, schemes 0–4, and a
24-hour RRTMG smoke. The same executable/config/restart hashes are checked.
The rate checks require instantaneous diagnostics, not products of separately
averaged lifetimes and rates. Scheme 2 retains its existing finite 1e8-second
cap above 1 km; only scheme 0 is an exact zero-bleaching control.

The first staging at 2019-07-01 01:00 failed during dry-run meteorology
initialization: canonical NEXTDAY I3 reads requested 01:00 from next day's
three-hourly MERRA2 file. The failed attempt is preserved. A new matrix uses
the original 00:00 cold restart on the meteorological time grid; six-hour
scheme runs exercise newly emitted BrC. This is not a spun-up science test.

`prepare_brc_fastjx_smoke.py` stages a separate one-hour FAST-JX case with
JValues. It does not copy a Cloud-J executable or submit a run. Both workflows
require independent preflight and compute-node execution.

`stage_gfas_month.py` downloads unmodified official native GFAS v2026-06
daily files into a new private directory, including the next-month boundary.
URL, ETag, size and SHA256 are recorded; numeric profile QC is separate.
August 2018 plus September 1: 32 files / 320,046,373 bytes staged. This does
not yet establish that the month-long model runs are ready or completed.
