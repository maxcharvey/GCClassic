# August 2018 GFAS workflow

This is the **named August 2018 comparison recipe**, not a general-purpose
GEOS-Chem launcher. Dates, the two case IDs, 20 flight days, the 3/9 missing
species lists, diagnostic fields, and the 14.7/14.8 differences are deliberate
scientific constraints. Paths, Python interpreter, source checkouts, Slurm
partition/account and wall limits are supplied at deployment. Input files,
executables and generated outputs do not belong in this package.

## Install once, in a new staging root

Dependencies: Python 3.10+, NumPy, netCDF4 and PyYAML. Use the environment that
provides the required NetCDF libraries. Slurm wrappers inherit the compiler and
NetCDF environment; they do not load site-specific modules.

```bash
python scripts/install_august_workflow.py /path/to/new/comparison
export BRC_AUGUST_ROOT=/path/to/new/comparison
export BRC_PYTHON=/path/to/python
cd "$BRC_AUGUST_ROOT"
```

Installation snapshots the workflow plus the existing fire and flight parsers,
and writes `WORKFLOW_TOOLS.json` with content hashes. It refuses existing tools,
frozen workflows and executed runs. Do not install or copy these files over an
active campaign. `BRC_AUGUST_ROOT` is required by shell wrappers and is exported
to Slurm by the submission tool; Python tools also support it for read-only
replay against another root. With the installed layout, Python defaults to its
own directory. Importing a module never submits or prepares a run.

## Input contract and preparation

First stage unused, otherwise complete run directories with these exact names:

- `BRC_147_GFAS_FIXED30_L15_20260921`
- `BRC_148_GFAS_NATIVE3D_20260921`

Both must already target August 1–September 1, 2018, at 2x2.5/47L MERRA2. The
legacy case must contain all 31 GFAS injection rows, fixed 30%/15-level settings;
the native case must select the official variable-height GFAS inventory. The
recipe does not choose donor physics, build executables, stage meteorology, or
create flight schedules. Preserve each binary's actual build-source pins in
`EXECUTABLE_FREEZE.json` (`cases[case].executable_sha256` and
`cases[case].build_sources['geos-chem'].commit`). See the historical evidence in
`docs/validation/2026-09-22/EXECUTABLE_FREEZE.json` for the schema, **not as a
manifest to reuse for another binary**.

Stage all 32 GFAS inputs and their `path`/`sha256` records in
`inputs/GFAS/v2026-06/download_manifest.json` (produced by the existing GFAS
stager), plus the 20 `Planeflight.dat.YYYYMMDD` schedules. Configure valid aerosol
and Cloud-J table directories. The seven base aerosol tables must match byte-for-byte; legacy brc/pbrc/dbrc
tables must equal native org.dat. Native organic mode does not select its
dedicated brc.dat; that file is still frozen against drift. Both configurations
must select the same Cloud-J inputs.
Mutable configs and output directories must be case-local, not symlinks.

```bash
"$BRC_PYTHON" prepare_restart_gate.py \
  --restart /path/to/GEOSChem.Restart.20180801_0000z.nc4 \
  --legacy-source /path/to/legacy/wrapper \
  --native-source /path/to/native/wrapper
```

Preparation reads KPP species from each **binary's recorded core commit**, then
checks the full transported/KPP union, exact restart date/grid and finite
existing fields. Only the precise missing sets permit `EY`: FFOCPI, FFOCPO and
PBRCPOA in both cases, plus MDL/LHMSAQ/LHMSMP/PHMSAQ/PHMSMP/PSO4MP in 14.8.
It never fabricates a restart. Correcting `BackgroundVV` to `Background_VV`
activates the intended initialization values: this is not a cosmetic change.

The recipe preserves backups, repairs the two unsupported legacy `.and.`
guards with nested brackets, writes extension-specific profile/column fire
pairs, sets both radiation dictionaries to 550 nm/all four flux switches
on/1200-second radiation calls, and retains original REAL8 restart precision.
Heating feedback stays off. Broad month diagnostics are monthly; BrC/RRTMG are
daily; separate one-hour copies are hourly. `RESTART_GATE_FREEZE_20260922.json`
and `OPTICAL_INPUT_FREEZE_20260922.json` bind the resulting configs and inputs.
Preparation refuses existing execution/freeze markers. A partial preparation
requires inspection and a new staging copy, not an automatic retry.

## Qualify before submitting the month

Run independent run-directory review first. On a Slurm **compute node**, inside
a suitable interactive allocation (the reference smokes needed 96 GiB/8 CPUs):

```bash
bash "$BRC_AUGUST_ROOT/run_smoke_pair.sh"
```

The smoke wrapper accepts only the two smoke case IDs and runs a strict
preflight before each executable. It does not run a month case. Release the
interactive allocation when finished. Audit each completed smoke and preflight
each unused month case:

```bash
"$BRC_PYTHON" audit_restart_smoke.py BRC_147_GFAS_FIXED30_L15_20260921_SMOKE1H_20260922 > audit_147_smoke.json
"$BRC_PYTHON" audit_restart_smoke.py BRC_148_GFAS_NATIVE3D_20260921_SMOKE1H_20260922 > audit_148_smoke.json
"$BRC_PYTHON" preflight_restart_gate.py BRC_147_GFAS_FIXED30_L15_20260921 > preflight_147_month.json
"$BRC_PYTHON" preflight_restart_gate.py BRC_148_GFAS_NATIVE3D_20260921 > preflight_148_month.json
```

An independent reviewer must inspect the actual final pair and write a JSON
report inside this root with `status: "PASS"`,
`scope: "final_harmonized_smoke_pair"`, and `main_reports_sha256` containing the
SHA256 of **both current** `audit_147_smoke.json`/`audit_148_smoke.json` reports,
plus their review evidence. A review string alone does not establish acceptance:
the tool verifies those reports against current configs, scripts and outputs.

```bash
"$BRC_PYTHON" accept_smoke_pair.py independent_final_smoke_pair.json
"$BRC_PYTHON" submit_month_pair.py --submit --partition YOUR_PARTITION
```

The month defaults are matched 16 CPUs/96 GiB, with 240-hour legacy and 192-hour
native caps; `--legacy-hours`, `--native-hours` and `--account` can adjust
scheduler settings after resource review. These are conservative limits, not
runtime forecasts. Request memory per CPU, as required on Euler. Modules,
`BRC_PYTHON`, and `BRC_AUGUST_ROOT` propagate to both model jobs and analysis.

Every successful submission is recorded immediately in
`MONTH_SUBMISSION_20260922.json`; any existing record or duplicate queued job
blocks rerunning the submitter. If a later submission fails, keep already issued
job IDs, inspect the record/queue, and submit only the missing job after review.
An ambiguous scheduler response also requires inspection: never assume no job
was created. No force retry or requeue is implemented.

The analysis uses `afterok` on **both** model-plus-audit jobs and cancels if that
dependency becomes invalid. It writes `august_analysis_20260922/` with all-flight,
first-day and later-flight JSON, overall concentration summaries, pressure-bin
CSV and `SUMMARY.md`; `MANIFEST.json` is written last as the completion signal.
Existing output directories are never overwritten.

## Interpretation and native output contracts

A one-hour stop at 01:00 flushes 51 flight points through 00:50; the last nine
scheduled minutes remain unflushed. No points are invented. The month ends at
midnight and must cover all scheduled records on all 20 days, preserving the
known August-26 21:40–21:53 UTC gap. HISTORY does not normally emit `time_bnds`:
check native simulation start/end attributes, interval timestamps, averaging
metadata, cadence and the endpoint restart together. Explicit bounds, if
present, must agree. Float32-written fallback values use relative tolerance
1e-7. The radiation gate requires positive 550 nm AOD **and nonzero signed flux**.

Concentrations remain molecules/cm3 and flight pressure hPa. This comparison
confounds version and injection method, retains initial-condition transients
and original restart precision, and uses unqualified organic-equivalent
optics. It establishes neither isolated version attribution nor physical
forcing/AAOD/AAE acceptance.
