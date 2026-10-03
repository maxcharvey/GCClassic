# BrC deposition and country attribution in v14.8

## Implemented: opt-in HISTORY diagnostics

From a generated run directory, run:

```sh
perl /path/to/GCClassic/scripts/configure_brc_deposition.pl --history HISTORY.rc
```

This enables daily averages in three narrow collections: `BrCDryDep`,
`BrCWetLoss`, and `BrCProcessBudget`. For a one-hour engineering test only,
add `--short-test-hourly`. The original configuration is saved once as
`HISTORY.rc.before_brc`. Repeating the command updates only its managed blocks.
Existing unrelated collections are retained. User-authored blocks with conflicting
names cause an error before writing. This is opt-in; generating a new run directory
requires applying it again. It does not change the standard templates or physics.

All six aerosol species PBRCPOA, NPBRCPOA, DBRCPOA, BRCSOA, WTC and FSOAS
already have dry and wet deposition registration. FSOAP is a gas precursor
without deposition flags; do not invent deposition outputs for it.

| Collection | Fields | Native units |
| --- | --- | --- |
| BrCDryDep | DryDep and DryDepVel for six aerosols (12) | molec cm-2 s-1 and cm s-1 |
| BrCWetLoss | WetLossConv, WetLossConvFrac, WetLossLS for six aerosols (18) | kg s-1, dimensionless, kg s-1 |
| BrCProcessBudget | Full-column emissions/dry deposition, chemistry, transport, mixing, convection for seven species; wet deposition for six (41) | kg s-1 |

`BudgetEmisDryDepFull` combines emissions and dry deposition and cannot be
interpreted as a separate deposition sink. Budget names refer to native operator
stages: in the tested Classic case the emissions/dry-deposition increments appear
in `BudgetMixingFull`, while `BudgetEmisDryDepFull` is near roundoff. Do not use
that latter field as an emission denominator; use the matching HEMCO inventory
source diagnostic and explicit deposition fluxes, with operator timing audited.
Convert DryDep to mass with the
species molecular weight and Avogadro constant, then multiply by grid area and
time. WetLoss already expresses mass per grid cell per second: integrate over
levels and time, without multiplying by area again. FSOAS uses organic-matter
mass; BRCSOA and the carbon-bearing POA products use their registered carbon
basis. Apply the configured OMOC conversion before adding family carbon budgets.
FSOAP precursor accounting also needs an explicitly consistent carbon basis.
A deposited absorbing-family mass is not an optical absorption diagnostic.

### Engineering validation (2026-10-02)

One-hour FINNv25 surface-injection test, 2018-08-01 00:00–01:00 UTC,
2 x 2.5 degrees / 47 levels: job 15938175 completed successfully. All 71
requested diagnostic fields are finite; all dry/wet fields are individually
nonzero in this fixture. All 416 numeric restart variables match the completed
parent control exactly. The control used the same seed, executable, meteorology,
emissions and 32 threads; no additional control integration was launched.
The standalone configuration tests pass, including an inactive-block blank-line
regression identified in the first startup attempt (15937351, preserved).
Daily defaults, explicit short-test hourly output, idempotence, original-file
backup and refusal to overwrite conflicting blocks are covered.
Time-averaged files use the interval-start timestamp; they have simulation
start/end attributes but no explicit CF time-bounds variable.
Evidence is under `runs/validation/BRC_148_HISTORY_ORIGIN_20261002` in the BrC
development tree, including `FINAL_REPORT.txt`, array scan receipts, provenance
and SHA256 manifests. This proves diagnostic availability and unchanged parent
evolution for this fixture; it does not validate country attribution or all
injection scenarios.

## Initial USA and Canada design (historical scope; prototype below)

Recommended initial scope: separate USA and Canada biomass-burning cohorts,
with a rest-of-world complement. These defaults follow the injection question;
all-source tagging is a distinct extension. Country membership must include an
explicit decision on Alaska, Hawaii and territories. A bounding rectangle or a
CONUS mask is not a complete USA definition. Arctic north of 66.5 degrees N is
an initial analysis proposal; persist the exact receptor polygon and land/sea
selection in experiment provenance.

Existing local candidates under `ExtData/HEMCO/MASKS/v2018-09` include
`USA_mask.geos.1x1.nc`, `Canada_mask.geos.1x1.nc`, and finer inventory-specific
masks. Their geographic coverage and exclusivity have not been qualified.
HEMCO documentation explains that geographic tags apply to base emissions,
not extension-computed emissions, and binary MASK fields do not preserve
fractional scale factors. See the official
[HEMCO tagging and country examples](https://hemco.readthedocs.io/en/3.8.0/hco-ref-guide/more-examples.html).
The pinned fire extension and chemistry paths therefore require code changes.

### Implementation cascade

1. Prepare mutually exclusive USA/CAN/ROW source allocation at native fire
   inventory resolution. Partition the *emission-weighted* source and conservatively
   regrid each partition. Coarse-grid country area fractions times total emissions
   are an approximation and must be labelled as such. Record masks, hashes,
   coverage, overlaps, boundaries and regridding weights.
2. Branch HEMCO at pinned c06052a; extend `src/Extensions/hcox_gfed_mod.F90`,
   `hcox_gfas_mod.F90`, `hcox_finnv25_mod.F90` and shared
   `hcox_fire_injection_mod.F90`. Tag only the requested inventory/category.
   Retain parent source unchanged. Use the exact parent injection profile for
   each partition, including surface fallback; verify level-by-level closure.
   In the profile experiments, branch from their reviewed injection changes
   rather than recreating a different injection algorithm on the integration base.
3. Register seven country states per cohort in GEOS-Chem's species database and
   transported list, plus the ROW complement for closure. Resolve dry/wet mapping
   through parent species properties. FSOAP remains non-depositing.
   State initialization/restart handling must distinguish pre-existing untagged
   background from the new emission cohort. Starting all origin states at zero
   measures new emissions only and must not be reported as attribution of the
   entire existing parent burden.
4. Extend `GeosCore/brc_mod.F90` conversion operators for FSOAP -> FSOAS ->
   BRCSOA -> WTC and NPBRCPOA -> WTC. Derive origin conversion and loss amounts
   from the actual *parent* operator, environment, OMOC conversion and process
   order. Allocate parent cutoff/cleanup conservatively across origins: applying
   SMALLNUM independently to each tag can destroy tag-sum closure while the
   parent survives. Parent chemistry itself remains unchanged. Preserve persistent PBRCPOA and
   DBRCPOA states. Generic deposition/transport registration alone is insufficient.
5. Review `GeosCore/aerosol_mod.F90`, optical/surface-area/heterogeneous-chemistry
   consumers and aerosol mass diagnostics to ensure diagnostic origin states do
   not contribute a second physical aerosol mass. DBRCPOA's diagnostic hygroscopic
   flag coexists with its dry carrier treatment; cloning flags without reviewing
   these consumers can change physical behavior. Review `hco_interface_gc_mod.F90`
   emissions/deposition archiving, species IDs and chemistry required-ID logic.
6. Add origin-resolved emitted mass, burdens, deposition and process budgets
   through `Headers/state_diag_mod.F90` / HISTORY. For export through a country
   boundary, archive synchronized horizontal face mass fluxes with country
   fractions/boundary geometry. Full-column net transport tendency or outside
   burden cannot independently identify gross outward crossing.
7. Define outputs before interpreting efficiency: cumulative net export /
   cumulative source emissions; gross outward crossing is a separate recirculation
   metric. First-passage export needs an additional crossing-memory method.
   Arctic deposition efficiency is origin-resolved deposited carbon in the receptor
   over the window divided by the matching emitted carbon cohort. Report remaining
   burden, return transport, non-Arctic sinks, background treatment and uncertainty.

### Required acceptance gates

- Disabled option preserves all parent restart arrays exactly on a matched test.
- Native and regridded USA+CAN+ROW sources close to the parent source at every
  injection level; invalid/overlapping/nonfinite partitions fail before launch.
- Isolated conversion tests close on a common carbon basis and match parent
  rates and timing, including bleaching, zero emissions, underflow and fallbacks.
- Sum of origin partitions plus the untagged/background partition closes
  against the unchanged parent globally;
  regional budgets use synchronized process operators and face fluxes.
- Check aggregate origin closure after every transport and deposition operator.
  Nonlinear transport reconstruction/limiters need not advect separate partitions
  additively; use a parent-consistent conservative partition method or demonstrate
  acceptable, preregistered closure error rather than assuming duplication closes.
- Tags do not alter physical aerosol diagnostics, chemistry, radiation or PM.
- Deposition for a single-source parent/tag test agrees, and all tagged fields
  are finite with their declared units. Do not require nonzero wet loss in dry cells.
- Repeat accepted tests for surface, elevated uniform and profile injection only
  after each underlying injection branch is independently qualified.
- Preregister numerical tolerances and efficiency definitions before longer runs.

The accepted diagnostic work enables parent deposition collections. The origin
prototype described below is experimental: it does not provide first-passage
export efficiency or a scientifically validated Arctic attribution result.

### Experimental origin implementation and transport capture

The working branch also contains an opt-in engineering prototype: four origins
(USA, CAN, ROW, UNT) for each of the seven parents. UNT receives the existing
restart burden and emissions outside the selected FINNv25 fire cohort. Conversion
hooks partition the actual parent reaction increment, including its carbon-basis
factor; tags clone parent deposition properties. Country inputs partition the
native FINN grid by cell centres using pinned Natural Earth 1:50 million polygons.
This geographic approximation and the transport method remain unqualified.

The single-origin (all UNT) hourly and full-day tests reproduce parent restart,
dry deposition and signed wet loss. The daily test checks all 28 restart fields
and 48 dry and 48 wet clone fields; all 21 country restart fields and 12 country
source diagnostics are exactly zero. Initial country configurations failed strict parent invariance
because they split an inherited HEMCO source chain; see the safeguard below.
Separate species transport also produces material local origin-sum residuals.
Operator accuracy remains a failed acceptance gate: PBL mixing first breaks
closure, and separate advection also fails additivity. Do not use this prototype
to report country export or Arctic deposition efficiency.

For a bounded offline transport investigation, set
`BRC_PARENT_FLUX_CAPTURE_DIR` to an existing empty directory and optionally
`BRC_PARENT_FLUX_CAPTURE_STEPS` to an integer from 1 through 6 (default 1).
Without the directory variable, capture is disabled. Existing output files cause
an error. This hook observes parents and never changes their state or fluxes.

Each `flux_<parent>_stepNNNNNN.bin` is an unformatted stream in the build's
native conversion order. The schema starts with two eight-byte ASCII fields
(`BRCFX001`, blank-padded parent name), followed by sixteen int32 values:
version, NX, NY, NZ, step, state-unit code, fp byte width, J1P, J2P, FILL,
origin count (0 or 4), endian marker `0x01020304`, IORD, JORD, KORD, CROSS.
Floating payload is Fortran column-major in the recorded fp width:

1. DT, AREA(NY), GEO(NY), GEO_PC;
2. parent before polar averaging; optional USA/CAN/ROW/UNT prestates;
3. parent after polar averaging, DP1, DP2, CX, CY, WZ;
4. for each vertical level, DQ after X then DQ after Y;
5. predictor Q before Z, DQ after Z, DQ after cleanup, final Q;
6. FX(NX,NY,NZ), FY(NX,NY+1,NZ), FZ(NX,NY,NZ).

All unspecified arrays have shape NX,NY,NZ with the model's transport vertical
order. `audit_brc_parent_flux.c` reads either endian and fp4/fp8, reconstructs
parent divergence and final pressure division, and reports cleanup separately.
Its independently reset uniform/checkerboard donor probes test algebraic
feasibility at each parent stage; they are not sequential origin trajectories or
a reconstruction of the native limiter. No clipping or renormalization occurs.
Inventories in this capture use pressure times area, not kilograms.
The reader also replays native `Qckxyz` column cleanup, including its
top/interior/bottom handling and uncompensated positive creation. It validates
the captured FILL flag and units. Four precision/endian signed-profile fixtures
exercise cleanup; all 28 native parent captures from the first two steps replay
exactly. Cleanup creation is separately quantified and does not explain away
the larger operator partition errors.
`make_brc_flux_fixture.c` supplies synthetic serialization/divergence fixtures,
including a periodic circulating flux whose checkerboard donor allocation
creates negative origins despite a positive unchanged parent. It does not test
native flux generation or meteorological consistency.

The first native control capture (two 600 s transport calls) passes every raw
parent replay gate. It also rejects the naive donor method: DBRCPOA has positive
parent stages but its X checkerboard probe creates negative origin cells.
BRCSOA has transient negative native X/Y/Z cells before `Qckxyz`; even constant
origin fractions inherit those intermediate negatives. Thus a method requiring
positive parent inventories at every raw stage cannot simply be inserted here.
Cleanup must have an explicit origin-consistent accounting treatment.

`test_brc_implicit_partition.c` is a separate toy experiment. It checks a dense
implicit mixing solve against linear residuals, per-origin inventory conservation,
face closure and singular zero-stock circulation refusal. Its periodic and
throughflow counterexamples expose spatial mixing and multi-face propagation;
Fourier timestep refinement distinguishes convergence to a discrete upwind
operator from accurate continuum advection. Passing these algebra tests does not
qualify this method for the captured native stages or live model integration.

The regional engineering integrator uses model cell-centre latitude >=66.5° for
its Arctic selection. This includes northern USA/Canada: deposition there is not
necessarily export across a national boundary. It does not compute fractional
receptor-cell overlap, gross scavenging, first passage, or a complete surface
precipitation ledger. The signed wet-loss integral is a net atmospheric process
loss and preserves re-evaporation/resuspension gains.

`audit_brc_origin_carbon.pl GC.log SIGNED_NET_LOSS.csv 1.8` sums parent and origin
families on the model's carbon-equivalent basis (FSOAP and FSOAS divided by 1.8).
Its weighted sum of species L1 discrepancies is explicitly an upper bound on the
family discrepancy, not the actual L1 of a summed cell field. The denominator
is the selected FINN USA+CAN+ROW emitted carbon over the CSV's verified interval.
The bound includes UNT/background and ignores species cancellations; it is not
an individual-country attribution error or a deposition efficiency.

### Configuration inheritance safeguard

HEMCO source fields with a `-` filename inherit the immediately preceding source
record. Native FINN SOAP inherits CO. Country fields therefore follow the final
explicit FINN MACR record, immediately before `)))FINNv25_Inject`; inserting them
between CO and SOAP changes physical SOAP emissions. The configuration regression
asserts this inheritance chain as well as the terminal tag insertion. Preserved
failed-case emissions showed SOAP as the only changed physical fire diagnostic;
corrected input-only, active surface-tag and active elevated-tag reruns reproduce
all 416 parent restart fields and all 49 common HEMCO numeric fields exactly
against their matched controls. The elevated test injects 35% of selected fire
emissions into two pressure-weighted layers above the PBL. Both surface and
elevated matched full-day pairs also pass all 416 physical restart fields and
49 common HEMCO fields exactly. These hourly and daily gates
establish physical-parent invariance; they do not resolve the separate failed
origin-transport closure gate. Individual results remain in the run evidence.

### PBL mixing localization capture

With the transport capture directory enabled, set
`BRC_PARENT_FLUX_CAPTURE_MIXING_AUDIT=1` and explicitly set
`BRC_PARENT_FLUX_CAPTURE_STEPS=2`. This requires all 28 registered origins.
The additional `mix_stepNNNNNN_latNNNN.bin` streams are read-only diagnostic
observations; the original `BRCFX001` transport schema is unchanged.

`BRCMX001` begins with its eight-byte magic and twelve int32 values: version,
NX, NZ, dynamics step, latitude index, 35 fields, fp bytes, state-unit code,
first countergradient level, first restoration level, endian marker, six phases.
Level indices are one-based in native top-to-bottom order. Units must be native
kg species/kg dry air (code 2). The 35-field order is each parent followed by
USA, CAN, ROW, UNT, with parents ordered FSOAP, FSOAS, BRCSOA, NPBRCPOA, WTC,
PBRCPOA, DBRCPOA. All real arrays use the recorded native fp format and all
integer masks use int32; arrays are Fortran column-major.

The payload contains Dt, AD(NX,NZ), AREA(NX), and Cflx(NX,35), followed by six
phase codes and Q(NX,NZ,35) snapshots: incoming state, raw countergradient,
after tracer-specific column rollback, raw implicit diffusion, after negative
clipping, and after native column-mass restoration. Between phases three and
four, an eight-byte `BRCMD001` marker precedes the actual common diffusion
coefficient arrays CC, ZE, TERM (each NX,NZ) and bottom tendency DQBOT(NX,35).
These are captured after QVDIFF, which has set ZE at the bottom level to zero;
the bottom denominator uses ZE at the level above. Finally it stores
threshold(35), rollback mask(NX,35), restoration numerator(NX,35), denominator
(NX,35), and actual safe-division branch(NX,35). Full-column inventories use
Q×AD; restoration targets use only the recorded first-restoration-level:NZ
range and Cflx×AREA×Dt. Signed intermediates are retained.

`audit_brc_mixing_capture.c` independently replays threshold masks, rollback,
clipping, all 35 native diffusion solutions, safe-division exponent tests, and
restoration arguments and scaling.
It reports signed and cellwise L1 discrepancies and negative counts at every
phase, boundary-flux closure, and mismatched parent/component guard decisions.
An explicitly signed offline probe shares only the parent's rollback mask and
restoration factor across the components, omitting component clipping. It
compares against actual final parent and parent with clipping omitted, reports
parent clipping mass, bottom-tendency closure, and negative component inventories.
It tests algebraic feasibility and does not qualify an origin repair. The run
receipt must separately require the complete two-step, 91-latitude matrix of
182 streams, each with six complete phases, and exact physical invariance for
capture-OFF versus reference and capture-ON versus OFF. Numeric replay tolerances
are 5e-12 for fp8 and 5e-5 for fp4, without a scientific accuracy threshold.

### Native process-budget QA

`extract_brc_operator_changes.pl` brackets the actual logged inventories at
600-second dynamics and 1200-second chemistry cadence, including each of the
seven parents and four origins. `audit_brc_operator_budgets.c` compares 175
global process increments against 205 native HISTORY budget fields, including
the combined mixing plus emissions/dry-deposition increment and explicit zero
FSOAP wet deposition. Budget rates are integrated with interval duration, never
area. Uninstrumented interstep mass changes remain separately unassigned.

The corrected hourly surface and elevated tests pass every comparison. The
roundoff QA bound combines 5e-7 of the cellwise absolute CDF integral, 5e-13 of
the logged inventory-pair scale, and 1e-10 kg; it was fixed before integration.
It is a bookkeeping check, without a country accuracy acceptance criterion.
The reader checks units, coordinates, averaging attributes and run span; frozen
HISTORY frequency/duration and actual model clocks provide the full-interval
contract because the native files have no explicit CF time bounds.

### Injection support

The tested configurations use PBL injection and a 35% pressure-weighted
two-layer injection above the PBL. This v14.8 FINNv25 extension does not consume
the inherited `FINNV25_GFAS_PROFILE` setting as a profile backend. The origin
stager rejects `true` atomically to avoid mislabelling a pressure-profile run.
A GFAS-profile experiment requires a separate backend implementation and its
own qualification.
