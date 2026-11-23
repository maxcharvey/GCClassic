# Residual primary fire OC and exclusive fire SOA routing

FOCPI and FOCPO identify the primary fire OC left after configured BrC
partitioning. They replace those emissions in generic OCPI/OCPO, rather than
adding tagged copies. FFOCPI/FFOCPO remain separate existing tracers. FOC is
carbon mass (MW 12.01), not total fire organic matter or all fire OA.

FOCPI/FOCPO inherit OCPI/OCPO density, dry/wet deposition, and Luo coefficients.
FOCPO ages into FOCPI using the same 1.15-day rate, chemistry timestep and small
concentration cutoffs. They share the existing OC optical carriers and their
phase-dependent OM:OC factors, growth, aerosol water, PM and PDER paths. Online
optics, Cloud-J and RRTMG therefore see the aggregate once; no extra aerosol bin
or optical tables are registered. FOCPO retains OCPO scavenging, unlike the
explicit no-wet-removal DBRCPOA experiment.

When harmonized FINN, GFAS or QFED BrC routing is active, ordinary selected-fire
SOAP is suppressed, while FSOAP is retained. Nonfire SOAP and ordinary inventory
modes are unchanged. The residual OC is emitted to FOCPI/FOCPO with unchanged
source fields, temporal/vertical profiles, units and partition factors. GFED
BrC emits its residual OC as FOC and suppresses SOAP when a nonzero FSOAP
replacement is requested; disabled BrC retains legacy GFED OC/SOAP behavior.
Updated GFED extension lists and transported FOC species are required, with
explicit errors for old lists rather than silently losing residual fire OC.
GFED tags inherit their corresponding OC per-species scaling and mask; conflicting
independent FOC options are rejected. A positive FSOAP replacement requires an
active FSOAP extension species before ordinary SOAP can be suppressed.

BrC-disabled execution folds tagged FOC state and flux into generic OC just as
it does existing FFOC. New tagged backgrounds are zero. Historical OC and SOAS
restart stocks are not retroactively partitioned, deleted or relabelled. Fresh
source-attribution experiments require a reviewed restart/spinup strategy.

Concentration, restart and boundary fields follow transported-species outputs.
Paired total/profile emission diagnostics and physical deposition/process budget
fields include FOC. Its optical contribution is included in ordinary OC-bin
outputs; there are no separate FOC AOD fields or aging-production diagnostic.
Use chemical process budgets to diagnose aging. Literal legacy HEMCO
`OCPI_BB`, `OCPO_BB` and `BIOMASS_OCPO` diagnostics retain their OC-only
selection and do not include FOC; use the explicit FOC emission fields for those
sources. APM, TOMAS and mercury-specific emission diagnostics are outside this
fullchem/aerosol implementation qualification. BrC primary/secondary family
diagnostics retain their existing meaning and exclude residual FOC.

Source/config and isolated native fixtures qualify wiring and arithmetic only.
Atmospheric transport/deposition, restart source history, and total fire OA
closure require later model evaluation. Old build receipts bind earlier source
snapshots. Existing run directories and archives are not modified.
