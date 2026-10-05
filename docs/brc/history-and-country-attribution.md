# Parent BrC monthly deposition and budgets

Apply `perl scripts/configure_brc_deposition.pl --history RUN/HISTORY.rc --monthly`.
The helper enables 12 dry fields,18 wet fields and41 full-column process budget fields.
PBRCPOA,NPBRCPOA,DBRCPOA,BRCSOA,FSOAS,WTC have native dry/wet registration.
FSOAP is a non-depositing precursor: archive concentrations and five process budgets,
but never invent deposition fields. The helper retains daily default and explicit
short-test hourly mode, backs up the original and refuses conflicting blocks.
Monthly and hourly options cannot be combined.

DryDep is molec cm-2 s-1 and DryDepVel cm s-1. Convert explicit DryDep flux using
species molecular weight and grid area. WetLossConv/WetLossLS and full-column
budgets are kg s-1: integrate time (and levels for wet loss), not area again.
WetLossConvFrac is a dimensionless scavenging coefficient, not a mass fraction.
Signed wet loss represents net atmospheric removal, not necessarily surface precipitation deposition.
BudgetEmisDryDepFull combines processes and in tested Classic ordering can remain
near roundoff while the increments appear in BudgetMixingFull. Use independent
HEMCO emissions for source denominators. Respect the registered carbon vs organic-matter
basis and configured OMOC when forming family totals. Do not reconstruct deposition
from products of monthly-mean concentration and velocity.

The October2 one-hour surface test qualified the availability of these71fields
and physical-parent invariance. The WE-CAN FINN/GFAS run requires its own matched
checks with new injection. All seven family members must appear in actual
SpeciesConc and Restart output; dry/wet output includes only the six aerosols.
This campaign does not include experimental USA/CAN/ROW/UNT species. Country
attribution remains a separate unqualified prototype and cannot be derived from
these parent diagnostics alone.
