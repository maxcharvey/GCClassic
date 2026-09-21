# BrC integration onto GEOS-Chem Classic 14.8.0

Branch: `integration/brc-14.8.0` (wrapper and modified submodules).
Local integration checkout: `GCClassic_BrC_14.8.0`, separate from all 14.7
development checkouts. Do not run `git submodule update` against an older
wrapper revision while working on this integration.

## Source contract

| Component | Official release baseline | Development donor |
| --- | --- | --- |
| GCClassic | `d25e74367c95e0bec0f3a4ee803d359ae80cc32a` (14.8.0) | `2c22a8fcf351df373558b9dc0958e5a64dc526f1` |
| GEOS-Chem | `a4551f9442183bb572b23e9c2d362e2d34420d3a` (14.8.0) | `c72cbb3536660ce20f389ad6eb4925c06091ed2d` plus audited uncommitted safeguards in the original checkout |
| HEMCO | `870e8802284d9e180b1a2b017ae6f5616cbbaedd` (3.13.0) | `17d31b993a42d49f8b9044930e6b48eb5c8b3ab5` |
| Cloud-J | `16d18b07ebc7f6ab3f8eb4c2ddcfdae8f12d9a23` | `f33a1b06b79f26ebe3d0eea41990dadc20208391` |
| HETP | `df2f942853e886c7830bcfd78606f06114cbd7e5` | none |

The later FINN donor includes the corrected GFED CO-ratio scaling and its
tests. The optical-routing/PDER worktree remains an experiment, not an
implicit production donor. Original dirty files and existing outputs are
not modified. Submodule URLs point at the development forks; new commits
must be pushed to those forks before this wrapper can be cloned elsewhere.
No push is part of this local integration.

## Design and file-cascade checklist

1. GEOS-Chem core: retain 14.8 thermodynamics/HETP, heterogeneous chemistry,
   mechanism and diagnostics changes; layer the BrC chemistry, species,
   runtime controls and configuration templates onto them.
2. Aerosol accounting: include all separated organic components in PM2.5
   and organic component diagnostics; DBRC remains dry. PM diagnostics
   remain aerosol/organic-matter mass. BrC mass diagnostics and bleaching
   fraction use a consistent carbon basis (FSOAS has OM/OC = 1.8).
3. Optical cascade: `NRHAER=11`, `NRH=5`, `AN_=67`, 22 RRTMG aerosol slots;
   audit allocation, map, dust/stratosphere offsets, masks and metadata.
   DBRC uses dry extinction, SSA and asymmetry. BrCDry AOD follows the
   same requested-wavelength interpolation as its parent aerosol slot.
   Stratospheric-disable controls act before all optical consumers.
4. Cloud-J: preserve upstream fixes, retain 67 aerosol/RH slots and allow
   all 74 optional dedicated Mie records required by the core map. Leave
   standalone dimensions unchanged. Test organic and dedicated mappings.
5. HEMCO: retain official 3.13 GFAS extension 112 and its reference-CO
   vertical profile. Port GFED BrC scaling and FINN injection separately;
   do not replace the official variable-height GFAS with the older custom
   fixed-layer module. Validate incompatible inventory/BrC settings and
   zero-injection controls. Check column mass conservation.
6. Configuration: maintain fullchem and aerosol-only templates, complete
   species/restart coverage, explicit BrC enablement, portable optical
   defaults, online AOD/AAOD/SSA and optional RRTMG diagnostics.
7. Verification: independent Fortran cascade review before compilation;
   unit/regression tests, RRTMG-enabled and disabled builds on compute
   nodes, then uniquely named short model tests with recorded inputs.

## Science boundary

This is an engineering integration and correction, not a promotion of new
global BrC parameters. Existing bleaching and emissions assumptions remain
explicit sensitivities. Organic-equivalent optical defaults are placeholders,
not physically qualified BrC spectra; an operating diagnostic/RRTMG pathway
alone does not establish scientifically validated brown-carbon forcing.
Dedicated optical tables need provenance, matching Cloud-J/online mappings,
and separate physical qualification. WTC does not retain POA/SOA provenance;
any allocation of its mass to component PM diagnostics must be documented.

The GEOS-only PM component convention assigns NPBRCPOA, WTC, PBRCPOA
and DBRCPOA to `PM25oc`, and BRCSOA/FSOAS to `PM25soa`. These remain
organic-matter diagnostics. WTC's placement is bookkeeping, not a claim
that all bleached carbon originated as primary aerosol. Chemistry's
existing FSOAS OM/OC=1.8 darkening conversion is preserved; only the
diagnostic carbon accounting is normalized.
`PM25oc` and `PM25soa` remain behind the upstream `MODEL_GEOS` guards;
they are not available Classic HISTORY outputs. Classic smoke tests use
`PM25`, `TotalOA`, and `AerMassPOA`; the total PM25 BrC correction applies
to Classic. Exposing separate PM component diagnostics in Classic would
require a further registration/computation change.

FFOCPI/FFOCPO remain separate transported provenance tracers, but their
aerosol mass is aggregated into the OCPI/OCPO carriers before PM and
optical calculations. Separate FFOC terms must not be added again to those
totals. The BrC-off compatibility path transfers FFOC back to OC and zeros
the provenance tracers.

Emissions closure has a specific scope: residual OC + NPBRCPOA + PBRCPOA
preserves the OC-derived branch (0.5 + 0.375 + 0.125). DBRCPOA at 4 x BC
is additive, not deducted from that OC branch. Generic SOAP and BrC FSOAP
also remain separate CO-derived precursor branches, each with the existing
0.013 ratio in GFED and the harmonized GFAS sensitivity. This inherited assumption is not a conservative
partition of one total secondary-precursor inventory. Scientific
qualification must address potential source overlap; vertical-injection
and diagnostic-closure tests alone cannot establish total fire-carbon
budget closure.
GFED's logged CO scaling factor 1.05 is distinct from those 0.013
precursor ratios: SOAP and FSOAP both follow the scaled CO emissions.

Remaining qualification work is explicit:

- Generate/qualify consistent WB/PB/DB optical tables for online AOD,
  RRTMG and Cloud-J; inspect spectra, SSA and asymmetry. Organic-equivalent
  smoke tests do not validate brown-carbon absorption or forcing.
- Spin up the added tracers and run longer paired conservation, chemistry
  and observational tests before seasonal production. The BrC-off case is
  an internal control, not proof of bitwise equivalence to stock 14.8.
- Keep inventory proxy splits and bleaching parameters as documented
  sensitivities pending scientific calibration; do not silently promote
  the separate PDER/optical-routing experiment.
- Full-model FINN, aerosol-only, GCHP and CESM qualification is outside
  the four-case Classic/fullchem smoke matrix. FINN's shared injection
  kernel and configuration branches have separate numerical/static tests.

The donor's stale regular CESM HEMCO diagnostics file was restored to the
official symlink into the maintained Classic fullchem template. This
preserves new diagnostics without claiming a CESM runtime test.

## Selecting the new GFAS pathway

Create a new fullchem/RRTMG run directory from this checkout, then explicitly
set `aerosols.carbon.brown_carbon: true`. In `HEMCO_Config.rc`, enable GFAS
extension 112, disable GFED and FINN, and set
`GFAS_BRC_HARMONIZED_SENSITIVITY : true` to exercise the controlled BrC
proxy emissions. Leave the official `GFAS_CO_3D` reference mapping intact
and supply the v2026-06 daily GFAS files. This switch applies the existing
BrC proxy assumptions; it does not infer measured BrC speciation from GFAS.

The ordinary GFAS configuration leaves the sensitivity disabled. Do not
confuse GFAS's native daily 3D profile with GFED/FINN's optional prescribed
elevated fraction/level controls. Online AOD and RRTMG use
`aerosols.carbon.brc_optics`; Cloud-J separately uses
`operations.photolysis.cloud-j.brc_optics`. Both default to `organic`.
The online table directory is configurable at `aerosols.optics.input_dir`.
Only select `dedicated` after qualifying the corresponding tables.

For a BrC-off control, remove explicit inactive BrC `AODHyg` species from
HISTORY. For an RRTMG-off build, disable the runtime RRTMG activation,
`longwave_fluxes`, `shortwave_fluxes`, `clear_sky_flux`, `all_sky_flux`,
the HEMCO RRTMG input switch and its HISTORY collection. Leave the
configured AOD wavelengths; separate BrC online-AOD diagnostics remain usable.

To publish later, push GEOS-Chem, HEMCO and Cloud-J integration branches
to their development forks first, then the GCClassic wrapper branch.
All are local until explicitly pushed.

## Validation record

Source cascade reviewed independently on 2026-09-21: PASS for GEOS-Chem
`2465cbb9fc7513eafcb1e37959056407f0b858ec`, HEMCO
`8195cd9a01cda6f93540329b2f4c19dc3ffc2554`, and Cloud-J
`f78dca88e8767f9885e98a2889e89233ddeedf54`. HEMCO numerical CTest:
2/2 PASS on Euler compute node eu-a2p-309, allocation 14787003.
Test-only core follow-up: `205c55493` (FINNv25 template regression and
isolated optics-test module files; no production Fortran change).
Later reviewed core fixes restore the CESM diagnostics symlink, ensure
GNU compiler options apply to the two large RRTMG coefficient initializers,
and import `To_UpperCase` in the optics parser. Runtime core snapshot:
`85907636a089a7d1ef764f42da2a0706ca3c5512`.
Wrapper Python regression tests: 24/24 PASS, including HISTORY collection
and filename/template syntax guards. Five core implementation checks PASS.
Both RRTMG-enabled and disabled Release builds/installations PASS. The
no-RRTMG Debug build also compiles, but its runtime is not qualified on
the installed NetCDF stack (see below).

All four one-hour Classic/fullchem cases complete with exit 0 and pass
independent output audits:

| Inventory | BrC | RRTMG | Runtime result |
| --- | --- | --- | --- |
| GFED | on | on | PASS: nonzero BrC optics, carbon accounting, three dry-AOD pairs |
| GFAS | on | on | PASS: native elevated injection, profile/column and proxy-ratio closure |
| GFED | off | on | PASS: zero BrC optical contributions, ordinary radiation active |
| GFED | on | compiled out | PASS: nonzero online AOD, no RRTMG output |

GFAS maximum profile/column relative difference is 2.745e-7 (gate 2e-6).
The three dry-AOD fields agree exactly between matched GFED RRTMG-on and
compiled-out runs. These are engineering results from cold-start, organic-
equivalent optical fixtures, not validation of physical BrC absorption.

The Debug failure is separately reproduced without GEOS-Chem: a standalone
`nf90_open`/`nf90_close` program on the Olson dry-deposition input exits 136
with `-ffpe-trap=invalid,zero,overflow`, and passes at the same `-O0` without
those traps. Standard Debug runtime needs a compatible NetCDF/library setup
or a separately reviewed I/O/trap solution. No model physics or shared
library was changed to hide this limitation. Failed configuration attempts
and Debug evidence are preserved in the validation directories.

The model-dev science/review/run-steward gates guided this integration:
existing parameter assumptions remain explicit, and unqualified optical
tables were not promoted merely because the engineering tests pass.

Validation inputs, configuration and results are recorded separately in
`runs/validation/BRC_1480_INTEGRATION_20260921/MANIFEST.md` beneath the BrC
project directory. Official GFAS inputs are v2026-06. The private restart
is the official 14.8 restart with nine new BrC/FFOC species initialized to
zero, not an assumed scientifically spun-up BrC state.
