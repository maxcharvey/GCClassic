# All-country source attribution: staged implementation

Branch: brc-origin-native-integration-20261005 (wrapper and core).
Science gate: science-advisor CONSISTENT, conditional on the safeguards below.

This new standalone package preserves the existing four-origin implementation
and frozen numerical evidence. It does not enable a live model hook.

## Catalogue and source contract

Use the pinned Natural Earth 50m Admin-0 GeoJSON, commit
9380cca83db5f9aef52d5e762765100745f84b27. Its 242 distinct ADM0_A3
features are separate source identities, sorted lexicographically. Retain ISO
aliases, names, type and sovereignty metadata; disputed labels describe this
dataset's convention. Append UNS (geographically unassigned source) and UNT
(unattributed initial/background stock): 244 origins, seven families, 1708
stocks. UNT never receives newly partitioned emissions. Geography gaps are
UNS, not inferred ocean. Never retrospectively split legacy nonzero ROW.

Bind catalogue, ordering, geometry and source hashes to a registration manifest.
Classification is cell-centre attribution at the pinned dataset resolution,
not a claim of border precision. Preserve polygon components and holes; exact
boundaries/multiple matches refuse rather than impose a country priority.
Normalize longitude while keeping dateline-crossing rings continuous. Malformed
coordinates, open rings, duplicate IDs and unsupported geometry refuse.

## Source arithmetic

New assumed-shape Fortran module accepts 1..244 source entries. Input parent,
raw partition and injected parent share the caller's mass basis; no conversion
or second physical emission is performed. Preserve the old direct-product
algorithm and 2e-6 source closure / 5e-5 fp32 / 5e-12 fp64 output gates.
Exact zeros alone may be omitted; rare positive source support cannot be dropped.
Shape/capacity/resource/nonfinite/negative/closure/underflow failures leave the
entire Parts destination unchanged. Allocation uses STAT. The old three-origin
module is included literally as a compatibility reference, never edited.
The catalogue-bound bundle interface stages all source families together and
requires the final UNT source row to be zero. The lower-level arithmetic API
has no identities; that contract belongs to this bound wrapper. Independent
NumPy fp32/fp64 rounded-operation oracle checks every country's returned share,
alongside decimal summation, asymmetric shares and positive UNS controls.

## File cascade and acceptance

1. country_catalogue.py: deterministic source identities, strict geometry
   validation, point classifier, catalogue and disabled registration candidate.
2. all_country_source_mod.F90: independent dynamic source-allocation interface.
3. test_catalogue.py / source_probe.F90: manufactured geometry controls, real
   interior points, all 242 countries' metadata, deterministic hashes and
   fp32/fp64 closure/refusal/three-origin compatibility controls.
4. run.sh: guarded, one-shot compute-only build/test; exact source/input/model
   hashes checked before/after. New investigation phase, failures retained.
5. Independent preflight/results audit, then vault record.

## Subsequent live gates

This package supplies the roster and source interface, not 1708 working model
species. Native integration must separately extend HEMCO mappings, species and
advect/restart/deposition identities, chemistry transfers, own-stock losses,
transport and HISTORY diagnostics. Preserve SOAP source-inheritance anchor and
daily FINN refresh. Initial physical-only restart goes to UNT explicitly;
nonzero legacy ROW migration refuses unless separately designed. Manifest
identity/order must accompany restarts.

The fixed SP_LIMIT=128 PBL solver remains frozen. A dynamic/sparse all-country
solver needs its own science/design/qualification; donor identities and causal
budgets remain distinct. The legacy full first-success dispatcher and native
units6/tmp1 bindings also remain open. No cap increase, rare-source cutoff,
parent rescaling or retagging accepted plans is permitted.

Preflight 1708 additional stocks against actual grid, vertical levels, ranks and
live working arrays. At 144*91*47 cells, one binary64 tagged state alone is
8,415,493,632 bytes; HISTORY/restarts/temporary copies add further costs. Use
selected diagnostics for short qualification, not global hourly all-tag output.
Then compare tags off/on physical parents, sum countries versus parent, own
deposition and conversion budgets, positive FINN countries, multi-day restart
and serial/parallel behavior before a seasonal run.
