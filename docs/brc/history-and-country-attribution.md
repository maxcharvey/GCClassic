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

## Investigated: USA and Canada attribution (not yet implemented)

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

The current branch implements diagnostics and documents this cascade. It does
not yet provide chemically evolving country tags, first-passage export efficiency,
or a scientifically validated Arctic attribution result.
