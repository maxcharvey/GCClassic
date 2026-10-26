# Classic restart repair qualification

The isolated restart repair preserves cell-local dry-pressure mass and persistent
fullchem surface photolysis history. The current candidate targets GEOS-Chem
Classic fullchem with `USE_REAL8=ON`, a matched input grid, and explicit
`read_restart_as_real8: true` for its own continuation checkpoints. Retain HEMCO
regridding for an initial legacy seed when needed. HETP is unchanged.

Equal-pressure cells are literal no-ops. Changed cells receive the local ratio of
restart to runtime dry layer pressure. Pressure arrays and ratios must be finite
and positive. After photolysis reaction mapping, the two surface cache channels
are restored from the loaded JOH/JNO2 values. Other channels are preserved.

The reader checks HEMCO status/pointer/shape before copying each field. The local
REAL8 path validates matching coordinates, recognized field layouts/units and a
single Gregorian checkpoint timestamp before state loads. Canonical seconds,
minutes, hours and days since a timestamp are recognized for years 1900–9999.
This is a restricted native-restart contract, not a general CF regridding reader.
Legacy missing-field behavior remains explicit and does not promise exact
continuation. No whole-reader rollback is claimed after an error in a later field.
Packed variables, some auxiliary units and finite fill-value payloads require
additional validation before arbitrary files can be accepted. Hg/GCHP and other
restart phases need their own qualification. `USE_REAL8=OFF` is currently outside
this candidate: numerical helper interfaces are fixed REAL64 while model fields
can be REAL32. Portability must separate fixed64-bit grid/time validation from
model-precision pressure/cache operations and be tested before supporting that
configuration.

Run the standalone regressions in a compute allocation with the configured
Fortran compiler and NetCDF environment:

```bash
bash test/implementation/run_restart_validation_tests.sh
```

An optional argument supplies a real 144×91×47 checkpoint at 2019-06-01 03:00 UTC
for the fixture's native-metadata check. The synthetic tests cover swapped axes,
wrong coordinates, pressure/cache units, timestamps, invalid pressures and pointer
association/shape/status. Kernel checks share the exact included production code.
Full model continuous/prefix/restart comparisons remain necessary for every new
numerical stack; passing these fixtures alone does not qualify production runs.

Execution evidence is archived separately under
`runs/investigations/BRC_RESTART_INTEGRATION_20261026` in the BrC workspace.
Source commits, binary hashes, configurations and actual input identities define
each result. The executable was built before the source bookkeeping commits;
its compiled source checksums bind it to the committed Fortran files.
