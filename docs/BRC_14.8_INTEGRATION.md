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

## Validation record

Source cascade reviewed independently on 2026-09-21: PASS for GEOS-Chem
`2465cbb9fc7513eafcb1e37959056407f0b858ec`, HEMCO
`8195cd9a01cda6f93540329b2f4c19dc3ffc2554`, and Cloud-J
`f78dca88e8767f9885e98a2889e89233ddeedf54`. HEMCO numerical CTest:
2/2 PASS on Euler compute node eu-a2p-309, allocation 14787003.
Wrapper Python regression tests: 7/7 PASS. Full model compilation and
short runtime validation are still in progress; source review is not
runtime qualification.

Validation inputs, configuration and results are recorded separately in
`runs/validation/BRC_1480_INTEGRATION_20260921/MANIFEST.md` beneath the BrC
project directory. Official GFAS inputs are v2026-06. The private restart
is the official 14.8 restart with nine new BrC/FFOC species initialized to
zero, not an assumed scientifically spun-up BrC state.
