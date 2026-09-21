# Fire inventory selection on the 14.8 BrC integration

The supported additional inventory is **QFED2**, not “QFAS”. These are
engineering pathways with inherited, explicitly controlled BrC proxies;
they do not qualify inventory-specific BrC emission factors or physical optics.
Keep the existing organic-equivalent optical tables for this work.

Select only one inventory and disable the other parent extensions/options.
Disabling `GFED4` alone is not equivalent to setting extension `GFED: off`.
The model rejects competing GFED/GFAS/FINNv25/QFED2 selections and rejects
harmonized-proxy switches when their inventory or `brown_carbon` is disabled.

| Inventory | Selection in HEMCO_Config.rc | Vertical treatment | Runtime evidence |
| --- | --- | --- | --- |
| GFED4 | `111 GFED: on`, `GFED4: true` | Existing fixed FT fraction/level-count options, including surface-only control | Surface and positive-injection 14.8 runs pass |
| GFAS | `112 GFAS: on`, `GFAS_BRC_HARMONIZED_SENSITIVITY: true` for BrC proxies | Native 14.8 `cofire_3d/cofire` profile; do not add the legacy GFAS_Inject extension | Native-height 14.8 smoke passes; August daily input QC complete |
| FINNv2.5 | `FINNv25: true`, `165 FINNv25_Inject: on`, `FINNV25_BRC_HARMONIZED_SENSITIVITY: true` for BrC proxies | Existing shared fixed-fraction injection; surface alternative retained in templates | Static contracts pass; canonical v2025-06 inventory absent locally, no runtime claim |
| QFED2 | `QFED2: true`, `QFED2_BRC_HARMONIZED_SENSITIVITY: true` for BrC proxies | Existing QFED 65% PBL / 35% PBL-to-5500m partition, unchanged | Paired proxy-off/on one-hour RRTMG runs pass |

The GFAS/FINN/QFED harmonized-proxy switches default to false. With QFED's
switch off, its ordinary OC and POG pathways remain intact. With it on,
the tested proxy chains retain 0.5 residual OC + 0.375 NPBRCPOA + 0.125
PBRCPOA, FSOAP=0.013 CO, and DBRCPOA=4 total BC. QFED CO's existing 1.05
scale and its diurnal factor are applied consistently. POG rows explicitly
retain the full-OC file and native vertical dimensions, preventing accidental
HEMCO hyphen inheritance from a BrC row. These identities establish only the
declared proxy partition: additive DBRC and SOAP/FSOAP overlap still require
the separate mass-basis review in core issue #22.

## Diagnostics must select the inventory too

Run-directory creation copies HEMCO_Diagn.rc; it does **not** rewrite its
biomass-burning selectors. The standard `Emis*_BioBurn` columns and matching
`Emis*_BioBurn3D` profiles default to GFAS. Set both members of every pair:

| Path | ExtNr / category / hierarchy |
| --- | --- |
| GFED extension | `111 / -1 / -1` |
| GFAS native extension | `112 / -1 / -1` |
| FINNv2.5 injection extension | `165 / -1 / -1` |
| FINNv2.5 direct surface rows | `0 / 5 / 3` |
| QFED2 direct rows | `0 / 5 / 2` |

Use dimension 2 for the column and 3 for the layer-integrated profile, both
in kg/m2/s. All-source `Total`/`TotalColumn` pairs remain available but cannot
replace inventory-specific attribution diagnostics.

## Reproducible QFED check

`scripts/prepare_qfed_smoke.py` stages a new paired directory from the
documented completed GFED donor and current fullchem template; it never
launches or assigns an executable. Source/build freeze, restart coverage,
independent preflight, and compute-node execution are separate mandatory
steps. It refuses existing output roots and preserves failed staging.

The published [paired-output audit](validation/2026-09-21/qfed_pair.json)
finds CO/BC unchanged exactly and residual-OC+NP+PB conservation error
9.62e-8; all profile/proxy relative errors are below 2.83e-7 (gate 2e-6).
The [BrC/RRTMG audit](validation/2026-09-21/qfed_brc_smoke.json) also passes.
Binary SHA256: `30377e1d0823f99a1d6a2806a23954ab16eccc7555495076dfe28e510e52ed8d`;
build origin wrapper `f30a54a`, core `b34f550`, HEMCO `c06052a`, Cloud-J
`f78dca8`. Later template-only commits do not relabel this executable.

No new optical constants, fire inventory downloads beyond the approved GFAS
month inputs, or new chemistry mechanisms are part of this follow-up.
