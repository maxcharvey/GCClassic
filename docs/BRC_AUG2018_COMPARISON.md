# August 2018 end-to-end GFAS comparison

This is a requested closeness/sensitivity comparison, not a matched control
that isolates a GEOS-Chem version effect. Both cases use 2x2.5/47L MERRA2,
Cloud-J/RRTMG, inherited BrC scheme 4 and the current organic-copy optics.
The frozen 14.7 reference uses GFAS 30% FT injection over 15 levels above PBL;
14.8 uses the native GFAS variable-height profile. No parameter is promoted.

Local staging root:
`runs/validation/BRC_147_148_GFAS_AUG2018_20260921` under the BrC project.
Case names are `BRC_147_GFAS_FIXED30_L15_20260921` and
`BRC_148_GFAS_NATIVE3D_20260921`.

## Launch gate

The month is **not launched**. The archived Aug-1 GEOS restart lacks PBRCPOA,
FFOCPI and FFOCPO in both configurations, plus MDL in 14.8; it originated in
a GFED simulation. A user choice between explicit cold initialization and
July spinups is required. Then freeze matching executables/restarts, complete
independent run-steward review, and qualify a separately staged one-hour case
before launching the month. Do not overwrite the archived restart or treat
the optional HEMCO restart as interchangeable with a GEOS restart.

The 32 staged native GFAS files (August plus Sep-1) pass CO profile QC and
all configured gas/aerosol source-header checks. Required MERRA2 files and all
20 existing WE-CAN schedule days are available. Monthly broad HISTORY output
and daily BrC/RRTMG output pass cadence checks. Detailed source/config/input
records and preserved draft corrections live in the staging root.

## Paired flight-track profiles

After both month runs finish, run the following from the staging root with
the integration wrapper's `scripts/compare_planeflight_profiles.py`:

```bash
python /path/to/GCClassic/scripts/compare_planeflight_profiles.py \
  BRC_147_GFAS_FIXED30_L15_20260921/OutputDir \
  BRC_148_GFAS_NATIVE3D_20260921/OutputDir \
  --left-schedule-dir BRC_147_GFAS_FIXED30_L15_20260921 \
  --right-schedule-dir BRC_148_GFAS_NATIVE3D_20260921 \
  --fields OCPI,OCPO,BCPI,BCPO,FSOAP,FSOAS,NPBRCPOA,PBRCPOA,DBRCPOA,BRCSOA,WTC,FFOCPI,FFOCPO,CO \
  --pressure-bins 200,300,400,500,600,700,800,900,1000,1100 \
  --expected-dates 20180801,20180802,20180803,20180804,20180806,20180807,20180808,20180809,20180810,20180813,20180814,20180815,20180816,20180820,20180821,20180823,20180824,20180826,20180827,20180828
```

Capture stdout as a new JSON artifact; never overwrite a completed analysis.
The full explicit date list is important: discovery alone cannot detect a
flight day absent from both output directories. The parser requires every
requested named field in both headers and all scheduled points in both logs.
It reports paired 14.8-minus-14.7 medians/quartiles and counts per pressure bin,
with log/schedule hashes and excluded-pressure counts. Concentrations remain
in native named-species **molecules/cm3**, pressure in **hPa**; there is no
implicit conversion to mass, volume mixing ratio, AAOD or a grid-column profile.

Preserve the intentional August-26 21:40–21:53 UTC sampling gap; do not fill or
interpolate it. Any other missing day/point, duplicate key, differing schedule,
coordinate mismatch or invalid concentration is a failed analysis gate, not
a sample to silently discard. Compare first-day behavior separately from
later flights because initialization effects may be important.

The implementation's archived-sample self-test used the *same* completed
14.7 output on both sides (149 Aug-1 points). Its zero differences test parser
plumbing only; they provide no evidence of model-version agreement.
