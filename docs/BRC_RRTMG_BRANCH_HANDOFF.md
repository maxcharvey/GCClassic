# BrC, online optics, and RRTMG branch handoff

## Purpose

This document records every material addition relative to the GEOS-Chem main
branches for the BrC/RRTMG worktree as inspected on 21 July 2026 and amended
for the ordinary-map repair on 22 July. It is a source-diff handoff, not a
scientific validation claim and not a simulation result.

The name "brc_rrtmg" refers to the three modified submodule branches. The
superproject is currently on debug/rrtmg-brc-aod-checks, which points to those
submodule commits.

| Component | Comparison | Merge-base on main | Handoff head | Diff size |
| --- | --- | --- | --- | --- |
| Superproject | main...debug/rrtmg-brc-aod-checks | ed80134116a2 | this handoff commit | .gitmodules, 3 gitlinks, and handoff |
| GEOS-Chem | main...max/brc_rrtmg | df4592e84561 | f280b2a50 | 34 files, +6,147/-317 |
| HEMCO | main...max/brc_rrtmg | e23c43b89a | 2552b0a | 1 file, +125/-2 |
| Cloud-J | main...max/brc_rrtmg | 1dff6fe8d6cf | f33a1b0 | 1 file, +6/-2 |
| HETP | no branch change | n/a | 2a99b24625ed | none |

The comparison uses Git three-dot syntax, so each submodule diff is measured
from the branch merge-base with its own main branch.

## Scope states

### Committed BrC/RRTMG implementation

Everything in Sections 1 through 11 is committed on the heads listed above.
This is the implementation that would be obtained by checking out the named
branches and initializing submodules.

### 21--22 July compatibility follow-on

The following changes are now committed and pinned by this superproject
handoff:

1. a Cloud-J stratospheric-aerosol index correction;
2. a functional brown_carbon on/off gate, including GFED and legacy-OC
   compatibility behavior;
3. a source-level regression test for those contracts; and
4. optional dedicated dry-DBRCPOA Cloud-J records with a 63-entry fallback.

The first three are correctness and compatibility fixes. The fourth is
backward compatible: a normal 63-entry FJX table retains the wet-BrC mapping,
while a matching 68-entry table enables dedicated dry-DBRC records.

The 22 July GEOS-Chem follow-on safeguards the ordinary five-entry
`brown_carbon:false` hygroscopic map while retaining the fixed eleven-bin
optical layout. The superproject gitlink is advanced by `da74f7399`.

The untracked file simple_xy.nc is unrelated to this implementation and is
deliberately excluded from this document.

## 1. Scientific and tracer design

The branch adds a biomass-burning brown-carbon framework plus the supporting
emissions, aerosol, photolysis, radiation, heterogeneous-chemistry, and
diagnostic pathways needed to carry the new material online.

The implemented tracer flow is:

~~~text
GFED CO  -> FSOAP -> FSOAS -> BRCSOA -> WTC
GFED OC  -> NPBRCPOA --------------------> WTC
             \-> PBRCPOA (persistent; no bleaching)
GFED BC  -> DBRCPOA (dark, dry, persistent in this implementation)
~~~

The model also adds FFOCPI and FFOCPO to keep fossil-fuel OC separate from
fire OC before folding both back into the existing OC aerosol carriers.

| Tracer | Stored mass basis | Source/fate | Aerosol/optics treatment |
| --- | --- | --- | --- |
| FSOAP | gas; MW 150 g mol-1 | GFED CO scaled by a configurable fraction; condenses to FSOAS | no aerosol bin |
| FSOAS | organic matter; MW 150 g mol-1 | receives FSOAP condensate; darkens to BRCSOA | wet bin 9; brc.dat |
| BRCSOA | carbon; MW 12.01 g mol-1 | formed from FSOAS; photobleaches to WTC | wet bin 6; brc.dat |
| NPBRCPOA | carbon; MW 12.01 g mol-1 | configurable fraction of GFED OC; photobleaches to WTC | wet bin 7; brc.dat |
| PBRCPOA | carbon; MW 12.01 g mol-1 | persistent share of the primary-BrC allocation | wet bin 10; pbrc.dat |
| DBRCPOA | carbon; MW 12.01 g mol-1 | GFED BC multiplied by a configurable scale; no bleaching path | dry carrier in bin 11; dbrc.dat |
| WTC | carbon; MW 12.01 g mol-1 | receives bleached BRCSOA and NPBRCPOA | wet bin 8; org.dat |
| FFOCPI | carbon; MW 12.01 g mol-1 | fossil-fuel hydrophilic OC | added to existing OCPI aerosol mass |
| FFOCPO | carbon; MW 12.01 g mol-1 | fossil-fuel hydrophobic OC; ages to FFOCPI | added to existing OCPO aerosol mass |

All seven BrC species and both fossil-fuel OC species are added to
run/shared/species_database.yml. Aerosol species have density 1300 kg m-3.
The BrC aerosol species are advected and subject to dry and wet deposition.

Important distinction: the branch intentionally treats DBRCPOA as a dry
optical carrier even though its species-database entry has Is_HygroGrowth:
true. That flag keeps DBRCPOA visible to tagged AOD and aerosol-area
diagnostics; aerosol_mod.F90 explicitly sets its wet mass to zero and uses a
dry DAERSL carrier for the online optics.

## 2. Fire emissions and fossil-fuel OC

### 2.1 HEMCO GFED extension

File changed: HEMCO src/Extensions/hcox_gfed_mod.F90.

The GFED extension now reads four optional extension options:

| HEMCO option | Absent-option default | Meaning |
| --- | --- | --- |
| CO to FSOAP | 0.0 | fraction of GFED CO mapped to FSOAP |
| BC to DBRCPOA | 0.0 | non-negative scale applied to GFED BC |
| OC to NPBRCPOA | 0.0 | fraction of GFED OC allocated to primary BrC |
| NPBRCPOA persistent fraction | 0.25 | share of the allocated primary BrC emitted as PBRCPOA |

For the fullchem template, the configured values are:

~~~text
CO to FSOAP                    = 0.013
BC to DBRCPOA                  = 4.0
OC to NPBRCPOA                 = 0.5
NPBRCPOA persistent fraction   = 0.25
~~~

The resulting source allocation is:

~~~text
FSOAP     = GFED_CO * CO_to_FSOAP
DBRCPOA   = GFED_BC * BC_to_DBRCPOA
NPBRCPOA  = GFED_OC * OC_to_NPBRCPOA * (1 - persistent_fraction)
PBRCPOA   = GFED_OC * OC_to_NPBRCPOA * persistent_fraction
OCPI/OCPO = previous GFED OC partitions * (1 - OC_to_NPBRCPOA)
~~~

DBRCPOA is deliberately a scale, not a fraction. HEMCO therefore allows
values above one and checks only its lower bound. The template value of 4.0
creates a DBRCPOA source equal to four times the GFED BC carbon source; it
does not subtract material from BC. Likewise, FSOAP is an added CO-scaled
proxy source rather than a subtraction from CO.

The fullchem HEMCO GFED target list now includes FSOAP, DBRCPOA, NPBRCPOA, and
PBRCPOA. HEMCO maps those species internally to the CO, BC, and OC source
fields, respectively.

### 2.2 Fossil-fuel OC separation

Files changed:

- GEOS-Chem run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem
- GEOS-Chem run/shared/species_database.yml
- GEOS-Chem GeosCore/carbon_mod.F90
- GEOS-Chem GeosCore/aerosol_mod.F90
- GEOS-Chem Headers/state_diag_mod.F90
- GEOS-Chem run/GCClassic/HISTORY.rc.templates/HISTORY.rc.fullchem

All listed CEDS OC sectors are redirected from OCPI/OCPO to FFOCPI/FFOCPO:
agriculture, energy, industry, transportation, residential-commercial-other,
solvents, waste, and shipping. New scale factors OC2FFOCPI and OC2FFOCPO are
both 0.5.

Carbon chemistry adds a first-order FFOCPO to FFOCPI aging step with the same
1.15-day lifetime used for OCPO to OCPI. The new production diagnostic is
ProdFFOCPIfromFFOCPO. For aerosol mass and optics, FFOCPI is added to OCPI
and FFOCPO is added to OCPO, so it preserves the existing OC optical
representation while retaining separate chemical tracers and emissions
diagnostics.

In the 21 July compatibility gate, `brown_carbon: false` instead routes FFOCPI and
FFOCPO HEMCO emission fluxes, plus any restart concentration, into OCPI and
OCPO before mixing, carbon chemistry, or transport. It also skips FFOC aging
and their extra aerosol-mass additions. This restores the legacy OC state
evolution while leaving the added zero-valued tracer definitions and HEMCO
diagnostic names structurally present.

## 3. BrC chemistry module

### 3.1 New module and integration

The new GEOS-Chem module is GeosCore/brc_mod.F90. It is added to the
GeosCore CMake source list, invoked from CHEMCARBON in carbon_mod.F90 after
the SOA chemistry, and cleaned up from GeosCore/cleanup.F90.

The public API is:

~~~text
ChemBrC
Init_BrC
Cleanup_BrC
~~~

ChemBrC looks up species at runtime. It returns without action unless FSOAS,
BRCSOA, and WTC exist. FSOAP and NPBRCPOA are optional. This means a
simulation can retain the code while omitting optional BrC tracers, but the
presence of the three required species activates the chain.

### 3.2 Chemical steps

| Step | Process | E-folding lifetime / rule |
| --- | --- | --- |
| 0 | FSOAP to FSOAS | 1 day |
| 1 | FSOAS to BRCSOA | 1 day |
| 2 | BRCSOA to WTC | selected bleaching scheme |
| 2b | NPBRCPOA to WTC | same selected bleaching scheme |
| 2c | PBRCPOA | persistent; no in-module loss |
| 3 | WTC | receives steps 2 and 2b |

FSOAS is carried as organic matter. Before adding it to BRCSOA, the code
divides the converted FSOAS mass by OMOC_BBOA = 1.8 to store BRCSOA as carbon
mass. The primary BrC and WTC tracers use carbon mass.

### 3.3 Bleaching parameterisation

The viscosity-dependent schemes implement the Schnitzler et al. (2022)
resistor-model lifetime:

~~~text
tau_BrC = C_FACTOR * 2 * a / (3 * Hk(T) * P_O3 * sqrt(D_O3))
~~~

The calculation chain is local temperature and RH to BBOA viscosity, then
ozone diffusivity, then lifetime. It uses:

- kappa = 0.07 for the BBOA water-activity mixing calculation.
- Reference dry viscosity 1e5 Pa s at 294 K.
- Fractional Stokes-Einstein exponent for ozone, xi = 0.684.
- Ozone hydrodynamic radius 0.198 nm.
- Particle radius a = 150 nm.
- Maximum viscosity 1e12 Pa s.
- Lower lifetime bound 21,600 s (6 h).
- Upper lifetime bound 1e8 s (about 3.2 years).
- Fixed-O3 option of 35 ppb when scheme 3 is selected.

The input key is aerosols.carbon.bleach_scheme. It is parsed in input_mod.F90,
stored as Input_Opt%BrC_Bleach_Scheme, and validated as an integer from 0
through 4.

| Scheme | Behaviour |
| --- | --- |
| 0 | exact no-bleaching tracer control; rate constant is zero |
| 1 | fixed 1-day bleaching lifetime everywhere |
| 2 | fixed 1-day lifetime only at or below 1 km AGL |
| 3 | viscosity-dependent lifetime with fixed 35 ppb ozone |
| 4 | viscosity-dependent lifetime with local model ozone; default |

For scheme 4, local ozone partial pressure is derived from the model O3
mixing ratio and midpoint pressure. If O3 is unavailable, the code falls
back to the fixed 35 ppb value.

The previous in-timestep 25% stop-loss implementation is not present at the
branch head. Persistent primary material is represented instead by PBRCPOA at
emission time.

### 3.4 Configuration caveat

The input parser renamed the Boolean key from
aerosols.carbon.use_brown_carbon to aerosols.carbon.brown_carbon. The
fullchem template sets brown_carbon: false and bleach_scheme: 4.

The 21 July implementation makes `LBRC` the authoritative user-facing
gate. With `brown_carbon: false`, it:

- suppresses the BrC chemistry call and GFED BrC source partitioning;
- restores the original GFED OCPI/OCPO fractions;
- folds branch-specific fossil-fuel OC emissions back into OCPI/OCPO;
- zeroes BrC aerosol mass, PM2.5, online-optics, Cloud-J, and heterogeneous-
  chemistry inputs;
- substitutes `org.dat` for unused BrC optical-file slots; and
- maps inactive BrC photolysis bins to an existing legacy OC Mie record.

This is intended to restore main-branch physical behavior, not to create a
bitwise-identical main executable: the expanded dimensions, extra tracer
definitions, and diagnostic names remain compiled into this branch.

## 4. Aerosol mass, AOD, area, and optics

### 4.1 Expanded aerosol dimensions

The standard hygroscopic aerosol count changes from 5 to 11:

| Constant/container | Main | Branch | Reason |
| --- | --- | --- | --- |
| NRHAER | 5 | 11 | six BrC aerosol bins |
| Phot%NSPAA | 8 | 14 | six added optical species slots |
| Phot%NASPECRAD | 16 | 22 | six added RRTMG aerosol categories |
| Phot%NSPECRAD | 23 | 29 | corresponding aerosol-plus-gas count |
| KPP aerosol-type arrays | 14 | 20 | six BrC types before SLA and ice |
| DAERSL components | 2 | 3 | added dry DBRCPOA carrier |

Files providing this infrastructure are:

- Headers/CMN_SIZE_mod.F90
- Headers/phot_container_mod.F90
- Headers/aermass_container_mod.F90
- Headers/state_chm_mod.F90
- GeosCore/aerosol_mod.F90
- GeosCore/dust_mod.F90
- KPP/fullchem/commonIncludeVars.H

The dust lookup index is changed from a fixed 8 to
NRHAER + NSTRATAER + 1 so dust continues to follow the expanded aerosol list.

### 4.2 BrC optical-bin mapping

| Hygroscopic index | AerMass field | Species | Optical data | Implementation detail |
| --- | --- | --- | --- | --- |
| 6 | BRCPI | BRCSOA | brc.dat | wet, uses existing hydrophilic OC mass conversion |
| 7 | NPBRC | NPBRCPOA | brc.dat | wet |
| 8 | WTCPI | WTC | org.dat | wet, transparent/ordinary OC optics |
| 9 | FSOAS | FSOAS | brc.dat | wet; already organic-matter mass |
| 10 | PBRC | PBRCPOA | pbrc.dat | wet |
| 11 | BRCPO in DAERSL(3) | DBRCPOA | dbrc.dat | dry; WAERSL(:, :, :, 11) is forced to zero |

The new AerMass fields are allocated, initialized, and freed in
aermass_container_mod.F90. aerosol_mod.F90 populates them from chemical
tracer concentrations, puts the wet species into WAERSL, places DBRCPOA into
DAERSL(3), includes the added material in PM2.5 and SNA/OM quantities, and
adds dry DBRCPOA AOD and surface area to bin 11.

BRCSOA, NPBRCPOA, WTC, FSOAS, and PBRCPOA participate in wet aerosol
treatment. DBRCPOA has dry AOD and dry surface area, even though it is
registered in the hygroscopic species map for diagnostic visibility.

New State_Chm aerosol field families make the six types addressable by
heterogeneous chemistry and diagnostics:

~~~text
AeroAreaBRC, AeroAreaNPBRC, AeroAreaWTC, AeroAreaFSOAS, AeroAreaPBRC, AeroAreaDBRC
AeroRadiBRC, AeroRadiNPBRC, AeroRadiWTC, AeroRadiFSOAS, AeroRadiPBRC, AeroRadiDBRC
WetAeroArea..., WetAeroRadi..., and AeroH2O... equivalents
~~~

### 4.3 Online optical assets

RD_AOD now reads fourteen spectral files rather than eight. The added file
names are brc.dat, pbrc.dat, and dbrc.dat; org.dat is also explicitly reused
for WTC. The fullchem template points to the site-specific directory:

~~~text
/cluster/work/climate/mharvey/ModelDevlopment/BrC/Aerosol_Optics/full_test_v2025-03/
~~~

This directory is not versioned in this repository. It contains the BrC files
and symlinks to the standard v2025-03 optics files. RD_AOD uses exactly the
same reader for `so4.dat`, `org.dat`, and every BrC file: it joins `input_dir`
and the selected filename, checks that the file exists, and reads the result.
The issue is therefore data deployment and the non-portable absolute path,
not a different BrC reader. At the documented snapshot, org.dat, brc.dat,
pbrc.dat, and dbrc.dat are byte-identical:

~~~text
SHA-256 1b5dc096875dec51a987855da7b936bb6c8d4bc548d10c3ddf5236d4f3ec6d26
~~~

Thus the branch creates distinct online pathways and attribution tags, but
the currently configured BrC, persistent-BrC, dry-DBRC, and WTC optical files
do not yet contain distinct numerical optical properties. A handoff must copy
or recreate this directory, including its standard-file symlinks, rather than
rely on the main-branch external-data path.

When `brown_carbon: false`, the local gate replaces the six inactive BrC file
names with `org.dat`. It therefore does not require `brc.dat`, `pbrc.dat`, or
`dbrc.dat`; a portable main-branch optics directory is sufficient for the
disabled mode.

### 4.4 Debug output

aerosol_mod.F90 adds root-rank BRC_DEBUG output that reports globally summed
standard AOD contributions for BRCSOA, NPBRCPOA, WTC, FSOAS, PBRCPOA, and
DBRCPOA when the relevant AOD calculation runs. brc_mod.F90 also prints
root-rank per-step conversion fluxes and BrC-family masses. These messages are
not restricted to verbose mode and can make long production logs large.

## 5. Online photolysis

### 5.1 Cloud-J

Cloud-J src/Core/cldj_cmn_mod.F90 increases the GEOS-Chem dimensions to:

| Constant | Main | Committed branch |
| --- | --- | --- |
| AN_ (aerosol selections per layer) | 37 | 67 |
| A_ (aerosol Mie sets) | 56 | 68; 63-entry tables remain supported |

AN_ = 67 is consistent with 10 fixed selections plus 11 hygroscopic bins at
five RH entries plus two stratospheric entries. Cloud-J accepts the ordinary
63-entry FJX_scat-aer.dat BrC setup; the additional five records are used
only when a matching 68-entry table is supplied.

GEOS-Chem GeosCore/cldj_interface_mod.F90:

- Corrects lookup-table strides from NRHAER to NRH.
- Adds BrC mass insertion for all six new bins.
- Applies RH interpolation to BRCSOA, NPBRCPOA, WTC, FSOAS, and PBRCPOA.
- Inserts DBRCPOA as dry mass in its dedicated bin.
- Maps stratospheric sulfate and PSC after the added BrC entries.

The 21 July interface correction derives the two stratospheric aerosol
fields as 10 + NRHAER * NRH + 1 and the following field. With 11 hygroscopic
aerosol bins, the former hard-coded 41/42 fields belong to NPBRCPOA, while
the correct fields are 66/67. The derived mapping remains correct if the
aerosol layout changes again.

The GEOS-Chem photolysis map assigns wet-BrC FJX records to BRCSOA, NPBRCPOA,
FSOAS, and PBRCPOA; WTC reuses OC records. DBRCPOA uses dedicated records
64--68 only with a 68-entry table and otherwise retains the wet-BrC mapping.
Inactive bins under brown_carbon:false use the ordinary OC Mie record. The
code also checks that the Cloud-J AN_ dimension equals the expected GEOS-Chem
aerosol layout before constructing the mapping.

### 5.2 Fast-JX

The Fast-JX path changes in:

- Headers/CMN_FJX_MOD.F90
- GeosCore/fast_jx_mod.F90
- GeosCore/fjx_interface_mod.F90
- GeosCore/photolysis_mod.F90

Its dimensions likewise grow to A_ = 63 and AN_ = 67. The code loops over all
NRHAER aerosol types rather than five. The old LBRC-dependent overwrite of OC
Mie records is removed; Fast-JX now reads the expanded jv_spec_mie.dat table
directly. The FJX interface no longer passes an LBRC argument to RD_MIE.

The explicit eleven-bin mapping in photolysis_mod.F90 is:

| Bins | FJX treatment |
| --- | --- |
| 1 through 5 | existing sulfate, BC, OC, sea-salt mappings |
| 6, 7, 9, 10, 11 | BrC Mie block beginning at record 57 |
| 8 | existing OC block beginning at record 36 |

Therefore a Fast-JX deployment requires an expanded 63-record
jv_spec_mie.dat consistent with the compiled dimensions.

## 6. RRTMG online radiation and attribution

Files changed:

- GeosCore/rrtmg_rad_transfer_mod.F90
- Headers/input_opt_mod.F90
- Headers/diaglist_mod.F90
- Headers/phot_container_mod.F90
- run/GCClassic/HISTORY.rc.templates/HISTORY.rc.fullchem

The RRTMG aerosol menu expands from 16 selectable aerosol outputs to 24.
The new menu tags are case-insensitive:

| Menu index | Tag | Included material |
| --- | --- | --- |
| 17 | BRC | absorbing BrC family: BRCSOA, NPBRCPOA, FSOAS, PBRCPOA, DBRCPOA; excludes WTC |
| 18 | BSOA | BRCSOA only |
| 19 | NPBR | NPBRCPOA only |
| 20 | WTC | WTC only |
| 21 | FSOA | FSOAS only |
| 22 | PBRC | PBRCPOA only |
| 23 | DBRC | dry DBRCPOA carrier only |
| 24 | BRCT | all six BrC aerosol bins, including WTC |

Existing dust and stratospheric-aerosol slots are moved to follow the six
BrC slots. The RRTMG mask maps its aerosol slots 8 through 13 to the six new
BrC classes. The fullchem HISTORY template adds explicit radiative fields for
all eight tags, including longwave and shortwave surface fluxes, AOD, SSA,
and asymmetry factor.

The diagnostics list and input options are resized for the new tags:

- RadOut grows from 17 to 25 entries.
- the parsed RRTMG wildcard expands from ten to eighteen optional output tags.
- NSpecRadMenu grows from 17 to 24.

rrtmg_rad_transfer_mod.F90 adds BRC_DEBUG output for the expanded tags. It
prints tie-point AOD sums and the archived radiative AOD at selected
wavelengths.

The explanatory index comment in HISTORY.rc.fullchem does not match the
implemented numerical map for all new BrC tags. Use the table above and
rrtmg_rad_transfer_mod.F90 as authoritative; the field tag names themselves
are parsed correctly.

## 7. Heterogeneous chemistry changes

This branch changes chemistry, not only diagnostics.

The KPP fullchem rate-law code grows the aerosol-type arrays from 14 to 20
and assigns six BrC types between generic OC and stratospheric/ice aerosol:
BRCSOA, NPBRCPOA, WTC, FSOAS, PBRCPOA, and DBRCPOA.

New helper functions aggregate generic OC plus all six BrC types for aerosol
surface-area and organic-volume calculations. They change the following
heterogeneous pathways:

| Pathway | Branch change |
| --- | --- |
| HO2 uptake | includes BrC surface area wherever generic OC area was used |
| NO2 uptake | includes BrC surface area |
| NO3 uptake | includes BrC surface area |
| generic VOC uptake | includes BrC surface area |
| N2O5 on sulfate/organic coating | includes BrC organic volume and water in the active calculation |
| N2O5 fine sea-salt chloride pathway | includes BrC organic volume and water in the active calculation |

DBRCPOA contributes dry organic volume but is intentionally excluded from
organic aerosol water. The N2O5 changes calculate a second, ORC-only shadow
case solely for comparison diagnostics; the BrC-inclusive case is the one
used in the actual rate calculation.

fullchem_mod.F90 only archives the resulting N2O5 quantities. The chemistry
change is in KPP/fullchem/fullchem_RateLawFuncs.F90, supported by the larger
HetState arrays in commonIncludeVars.H and state reset logic in
fullchem_HetStateFuncs.F90.

## 8. Diagnostics and output templates

### 8.1 BrC state diagnostics

state_diag_mod.F90 registers, allocates, finalizes, and provides metadata for:

| Group | Diagnostics | Units / meaning |
| --- | --- | --- |
| Bleaching drivers | BrCTauBleach, BrCKBleach, BrCEtaBBOA, BrCTemp, BrCRH, BrCO3ppbv | s; s-1; Pa s; K; percent; ppbv |
| BrC family state | BrCAbsMass, BrCTotMass, BrCBleachedFrac | kg; kg; unitless |
| Chemical transfers | BrCFluxFSOAP2FSOAS, BrCFluxFSOAS2BRC, BrCFluxBRC2WTC, BrCFluxNPBRC2WTC | kg per chemistry timestep |
| Dry DBRC AOD | BrCDryAODWL1, BrCDryAODWL2, BrCDryAODWL3 | unitless at the configured output wavelengths |

BrCAbsMass is defined as BRCSOA + FSOAS + optional NPBRCPOA + optional
DBRCPOA + optional PBRCPOA. BrCTotMass adds WTC. Because FSOAS is stored as
organic matter while the other family members are stored as carbon, these
two family-mass diagnostics combine different mass bases. They are useful
implementation diagnostics but should not be treated as rigorously
mass-consistent carbon totals without conversion.

Similarly, BrCFluxFSOAS2BRC archives the loss of FSOAS before the division by
OMOC_BBOA. It is an organic-matter flux, whereas the receiving BRCSOA is
stored as carbon. The diagnostic metadata labels it simply kg. This
distinction must be retained in analysis scripts.

### 8.2 N2O5 coating diagnostics

The branch adds:

~~~text
N2O5GammaSNAOrg
N2O5GammaORCOnly
N2O5DeltaGammaBrC
N2O5YieldClNO2SNAOrg
N2O5EffRadiusSNAOrg
N2O5SurfAreaSNAOrg
N2O5OrgVol
N2O5OrgVolBrC
N2O5OrgH2O
N2O5OrgH2OBrC
N2O5InorgH2O
N2O5BrCOrgVolFrac
N2O5BrCOrgH2OFrac
~~~

These expose the BrC-inclusive and ORC-only coating calculations, their
difference, and the organic/inorganic contributors. They are output-only
fields, but they diagnose a rate-law calculation that has changed as
described in Section 7.

### 8.3 HISTORY and HEMCO diagnostics

HISTORY.rc.carbon gains an enabled BrCDiagnostics collection with bleaching
lifetime, rate, viscosity, and the four transfer fields. The fullchem
template defines a larger BrCDiagnostics collection but leaves it commented
out in COLLECTIONS by default. It includes the bleaching drivers, family
state, transfers, first dry-DBRC AOD wavelength, and N2O5 diagnostics.

The fullchem HEMCO diagnostic template gains:

- 40 three-dimensional GFED biomass-burning emission profiles for existing
  emitted species.
- Two-dimensional and three-dimensional emission diagnostics for DBRCPOA,
  FSOAS, NPBRCPOA, and PBRCPOA.
- anthropogenic and shipping diagnostics for FFOCPI and FFOCPO.

The 40 added existing-species GFED 3-D profiles are ACET, ACR, ACTA, ALD2,
ALK4, BCPI, BCPO,
BENZ, C2H2, C2H4, C2H6, C3H8, C4H6, CH2O, CO, EOH, FURA, GLYX, HCOOH, ISOP,
MEK, MGLY, MOH, MTPA, MVK, NAP, NH3, NO, OCPI, OCPO, PHEN, POG1, POG2, PRPE,
RCHO, SO2, SOAP, STYR, TOLU, and XYLE. Together with the four BrC entries,
there are 44 added BioBurn3D diagnostics.

run/CESM/HEMCO_Diagn.rc changes from a symbolic link to a tracked 897-line
copy of the fullchem HEMCO diagnostic configuration. This is a real file-type
change and must be retained if CESM run-directory behaviour is expected to
match this branch.

## 9. Complete committed file inventory

### Superproject

| Path | Change |
| --- | --- |
| .gitmodules | switches GEOS-Chem, HEMCO, and Cloud-J URLs to the maxcharvey forks; Cloud-J URL changes from SSH to HTTPS |
| src/GEOS-Chem | gitlink advanced to f280b2a50 (from cd9c5c1b7 in the 21 July handoff) |
| src/HEMCO | gitlink advanced to 2552b0a |
| src/Cloud-J | gitlink advanced to f33a1b0 |

### GEOS-Chem source and headers

| Path | Added or changed behaviour |
| --- | --- |
| GeosCore/CMakeLists.txt | builds brc_mod.F90 |
| GeosCore/aerosol_mod.F90 | BrC/FFOC masses, bins, AOD, area, PM2.5, optics files, BRC_DEBUG, and LBRC false-path gating |
| GeosCore/brc_mod.F90 | new 1,871-line BrC chemistry and viscosity/bleaching module |
| GeosCore/carbon_mod.F90 | calls ChemBrC; adds FFOCPO to FFOCPI aging; gates both on LBRC |
| GeosCore/cldj_interface_mod.F90 | Cloud-J BrC optical mass mapping, corrected RH strides, and dimension-derived stratospheric slots |
| GeosCore/cleanup.F90 | calls Cleanup_BrC |
| GeosCore/dust_mod.F90 | calculates dust index after the expanded aerosol menu |
| GeosCore/fast_jx_mod.F90 | loops over 11 hygroscopic aerosols; removes old LBRC overwrite |
| GeosCore/fjx_interface_mod.F90 | uses revised RD_MIE interface |
| GeosCore/fullchem_mod.F90 | archives N2O5 coating diagnostics |
| GeosCore/input_mod.F90 | parses renamed brown_carbon key and bleach_scheme |
| GeosCore/hco_interface_gc_mod.F90 | passes brown_carbon to GFED; returns FFOC restart state and HEMCO fluxes to OCPI/OCPO when disabled |
| GeosCore/photolysis_mod.F90 | explicit eleven-bin FJX map, false-path OC fallback, optional dry-DBRC map, and Cloud-J dimension check |
| GeosCore/rrtmg_rad_transfer_mod.F90 | BrC RRTMG menu tags, masks, moved indices, debug output |
| Headers/CMN_FJX_MOD.F90 | Fast-JX A_ = 63 and AN_ = 67 |
| Headers/CMN_SIZE_mod.F90 | NRHAER = 11 |
| Headers/aermass_container_mod.F90 | six BrC AerMass arrays and third dry-aerosol component |
| Headers/diaglist_mod.F90 | enlarged RRTMG tag storage and wildcard tags |
| Headers/input_opt_mod.F90 | BrC bleaching option and 24-entry radiation menu |
| Headers/phot_container_mod.F90 | enlarged online-optics and RRTMG dimensions |
| Headers/state_chm_mod.F90 | registers six new aerosol area/radius/wet/water field families |
| Headers/state_diag_mod.F90 | FFOC, BrC, dry-AOD, and N2O5 output fields and metadata |
| KPP/fullchem/commonIncludeVars.H | 20 aerosol types and N2O5 diagnostic state |
| KPP/fullchem/fullchem_HetStateFuncs.F90 | resets N2O5 diagnostic state per grid box |
| KPP/fullchem/fullchem_RateLawFuncs.F90 | BrC-aware HO2, NO2, NO3, VOC, and N2O5 heterogeneous uptake |
| test/implementation/brc_wiring_test.sh | non-running source-level check of the gate and Cloud-J slot contracts |

### GEOS-Chem run templates and data definitions

| Path | Added or changed behaviour |
| --- | --- |
| run/CESM/HEMCO_Diagn.rc | replaces symlink with full diagnostic configuration |
| run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem | GFED BrC emissions; FFOC CEDS remap |
| run/GCClassic/HEMCO_Diagn.rc.templates/HEMCO_Diagn.rc.fullchem | 3-D biomass-burning and BrC/FFOC emissions diagnostics |
| run/GCClassic/HISTORY.rc.templates/HISTORY.rc.carbon | enabled BrCDiagnostics collection |
| run/GCClassic/HISTORY.rc.templates/HISTORY.rc.fullchem | BrC, N2O5, FFOC, and RRTMG tag diagnostics |
| run/GCClassic/geoschem_config.yml.templates/geoschem_config.yml.fullchem | BrC/FFOC transport species, bleaching scheme, external optics path |
| run/shared/species_database.yml | seven BrC plus two FFOC species definitions |

### HEMCO and Cloud-J

| Path | Added or changed behaviour |
| --- | --- |
| HEMCO src/Extensions/hcox_gfed_mod.F90 | GFED source partitioning/configuration plus the GEOSCHEM_BROWN_CARBON compatibility gate |
| Cloud-J src/Core/cldj_cmn_mod.F90 | GEOS-Chem FJX dimension expansion to AN_ = 67 and optional Mie capacity A_ = 68 |

No integration-test definition or HETP file changes in this handoff. The
GEOS-Chem follow-on adds test/implementation/brc_wiring_test.sh, a
non-running source-level regression test for the Boolean gates and Cloud-J
index contract.

## 10. Commit chronology

The committed GEOS-Chem branch history is:

| Commit | Date | Main addition |
| --- | --- | --- |
| cb0fbafbc | 2026-02-19 | initial FSOAS to BRCSOA to WTC scheme |
| 1bd852889 | 2026-02-24 | moves BrC logic into brc_mod.F90 |
| fff0a2f21 | 2026-02-24 | viscosity-dependent bleaching |
| 61c43b23c | 2026-03-06 | bleaching diagnostics |
| d01cfb3a6 | 2026-03-06 | selectable bleaching schemes |
| c131fa5a4 | 2026-03-06 | no-bleaching tracer option |
| dee37e588 | 2026-03-11 | local ozone option |
| 6c6774bb2 | 2026-03-19 | lifetime bound and BrC aerosol-area work |
| b1da06972 | 2026-04-24 | BrC species in run templates |
| 484d82603 | 2026-06-09 | carbon HISTORY BrCDiagnostics |
| b32728569 | 2026-06-09 | 3-D biomass-burning diagnostics templates |
| dd10dd618 | 2026-06-30 | persistent PBRCPOA split |
| e586d1f20 | 2026-07-01 | full-test optics, RRTMG, and runtime setup |
| e3d8468da | 2026-07-01 | BrC aerosol bounds correction |
| f5ab3ba60 | 2026-07-10 | hardened BrC photolysis mappings |
| 78f650be1 | 2026-07-10 | complete BrC RRTMG integration |
| 24fecc76e | 2026-07-15 | production upper whitening-lifetime bound |
| cd9c5c1b7 | 2026-07-21 | brown_carbon compatibility gate, Cloud-J slots, static test |
| f280b2a50 | 2026-07-22 | safeguard ordinary brown_carbon:false map |

HEMCO commits are 62dd0e8 (initial OC/FSOAP partition), 5d481e9 (DBRCPOA
scaled from BC), 3bdab08 (persistent primary-BrC split), and 2552b0a
(brown_carbon gate). Cloud-J commits are 1e4cdb3, d12e35a, ae07e3c, 52407db,
and f33a1b0, which progressively enlarge or extend the aerosol table.

## 11. 21 July compatibility fixes and optional dry-DBRC Cloud-J support

### Compatibility and Cloud-J fixes

The committed follow-on:

1. derives Cloud-J stratospheric aerosol positions from NRHAER and NRH,
   replacing the incorrect hard-coded 41/42 positions;
2. makes brown_carbon control BrC chemistry, GFED source partitioning,
   aerosol mass/area/AOD, online optics, Cloud-J inputs, and photolysis maps;
3. route FFOC HEMCO fluxes and restart mass into legacy OC tracers when BrC
   is disabled; and
4. adds test/implementation/brc_wiring_test.sh, which checks these source
   contracts without compiling or running GEOS-Chem.

The static test is not a numerical integration test. A future controlled run
must compare a brown_carbon:false case against a main-branch run.

### Optional dry-DBRC Cloud-J support

Cloud-J src/Core/cldj_cmn_mod.F90 changes A_ from 63 to 68 and documents five
optional dry-DBRCPOA entries at FJX indices 64 through 68.

### GEOS-Chem change

GEOS-Chem GeosCore/photolysis_mod.F90 replaces the fixed FJX mapping array
with a mutable array. In the Cloud-J build path only, it:

1. starts with the committed map, where DBRCPOA shares wet-BrC entries;
2. checks whether the loaded FJX table contains at least entries 64 through
   68; and
3. maps DBRCPOA bin 11 to record 64 when those records exist.

This preserves a 63-entry table fallback and allows a case-local 68-entry
FJX_scat-aer.dat to use five RH-indexed dry-DBRC entries. It has no matching
Fast-JX change; Fast-JX remains a 63-entry implementation.

The matching Cloud-J capacity and GEOS-Chem map are committed together. A
68-entry external table is still required before dedicated dry-DBRC records
can be exercised.

### 22 July ordinary brown_carbon:false map repair

GEOS-Chem `f280b2a50` initializes the fixed eleven-bin `Map_NRHAER` map
canonically, then remaps only active state entries. State-backed AOD, area,
and debug loops now use `State_Chm%nHygGrth`, so an ordinary five-entry state
does not dereference inactive slots. The code rejects a state map larger than
the fixed layout and rejects an enabled BrC state that lacks all eleven
entries. The static wiring test asserts these contracts.

## 12. Handoff requirements and cautions

1. Check out the exact submodule refs in the opening table. The root branch
   alone only changes gitlinks; it does not contain the GEOS-Chem/HEMCO/
   Cloud-J source history.
2. Preserve the maxcharvey fork URLs or otherwise make the named refs
   available from replacement remotes.
3. Transfer the external full_test_v2025-03 aerosol-optics directory or
   replace the absolute input_dir with a portable, complete optics directory.
4. Supply the matching FJX_scat-aer.dat for Cloud-J and jv_spec_mie.dat for
   Fast-JX. The committed source requires 63 BrC-capable entries; the
   optional dry-DBRC mapping needs 68 Cloud-J entries.
5. Use brown_carbon:false for a main-branch-like physical configuration.
   It leaves expanded arrays, zero-valued extra tracers, and diagnostic names
   in the executable, so it is not a literal bitwise main-branch build.
6. Account for mixed OM/carbon bases in BrC family-mass and FSOAS-to-BRCSOA
   diagnostics.
7. Expect heterogeneous chemistry changes whenever the BrC aerosol bins are
   populated, particularly for HO2, NO2, NO3, VOC, and N2O5 uptake.
8. Review or suppress BRC_DEBUG output before long production simulations.
9. The committed static test checks source wiring only. Compile and
   controlled-run validation remain required separately from this source
   documentation.
10. The committed source diff is not whitespace-clean: git diff --check
    reports 19 trailing-whitespace warnings (16 in GEOS-Chem and 3 in
    HEMCO). This documentation task does not modify those scientific source
    files. The two local dry-DBRC candidate edits and this document have no
    such warning.

## 13. Reproducing the audit

Run these read-only comparisons from the superproject root:

~~~sh
git diff --stat main...HEAD
git diff main...HEAD -- .gitmodules
git -C src/GEOS-Chem diff --stat main...max/brc_rrtmg
git -C src/HEMCO diff --stat main...max/brc_rrtmg
git -C src/Cloud-J diff --stat main...max/brc_rrtmg
git -C src/GEOS-Chem diff main...max/brc_rrtmg -- GeosCore/brc_mod.F90
bash src/GEOS-Chem/test/implementation/brc_wiring_test.sh
~~~

No build, simulation, or external job was launched while producing this
document.
