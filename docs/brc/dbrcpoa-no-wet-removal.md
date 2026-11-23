# DBRCPOA: explicit no-wet-removal configuration

At the user's request (2026-11-18), DBRCPOA has `Is_WetDep: false`.
This excludes it from the wet-deposition species maps used by convective
scavenging and large-scale rainout/washout, with either standard or Luo wetdep.
The previous wet coefficients remain in the species database as inactive
historical metadata. Merely zeroing rainout efficiency would not disable washout.

This is an idealized no-wet-removal experiment, not a physical claim that
hydrophobic aerosol cannot be scavenged. Transport, emissions, dry deposition,
dry optical properties and the diagnostic-only hygroscopic registration remain.
PBRCPOA, NPBRCPOA, BRCSOA, PWTC and SWTC retain their wet removal.

The deposition diagnostic helper omits DBRCPOA wet-loss and wet-deposition budget
fields, retaining its dry-deposition and other operator budget fields.
Existing run directories and archived build receipts are not modified. Future
runs must use the updated species database and regenerate managed diagnostics.
No atmospheric validation is claimed for this configuration change.
