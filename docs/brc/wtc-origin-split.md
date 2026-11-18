# White-carbon provenance and derived WTC

Branch: `feature/brc-wtc-origin-split-20261118`.

The current revision implements the user's WTC = PWTC + SWTC convention. The
previous three-stock source snapshot and its build receipts are preserved under
`maintenance/wtc-origin-split-2026-11-18/derived-total-revision/` and the parent
maintenance package; those receipts do not qualify this revision.

## Physical and output contract

- NPBRCPOA bleaching produces PWTC; BRCSOA bleaching produces SWTC.
- Only PWTC and SWTC are physical, advected, dry/wet-deposited white-carbon stocks.
- WTC is removed from transported_species and explicitly appended to the model
  species union with missing KPP indices. It remains a named metadata/output slot,
  with zero internal stock and no
  transport, chemistry, deposition or emissions. Its canonical HYG registration
  supplies bin-8 metadata only. It is not an additional aerosol burden.
- WTC concentration, restart, boundary and Planeflight values are derived from
  the two components at the actual sampling instant, in their current units.
  No persistent mirror is used: this avoids stale values after transport or
  deposition and avoids incorrect unit conversions of a nonadvected mirror.
- WTCPI = PWTCPI + SWTCPI. All physical white-carbon consumers count this once.
  Existing optical WTC diagnostic names retain their total-white-carbon meaning.
- Primary-family carbon: NPBRCPOA+PBRCPOA+DBRCPOA+PWTC. Secondary-family aerosol
  carbon: FSOAS/OMOC_BBOA+BRCSOA+SWTC. Gas-phase FSOAP is outside these stocks.
- BrCWhiteMass = PWTC+SWTC; BrCTotMass = BrCPriMass+BrCSecMass, within precision.
- PM25oc includes PWTC; PM25soa includes SWTC. Both use the existing white-carbon
  OM:OC convention OCFOPOA; rates, yields and deposition parameters are unchanged.

## Restart contract

Both component fields are required explicitly before background fallback. A new
spin-up seed must explicitly supply PWTC and SWTC, including zeros where intended.
An old restart with only WTC cannot be split retrospectively and is refused.
No seed is modified or legacy mass discarded automatically.

If a restart contains WTC, its total must match the two components within a fixed
float32 serialization envelope (8 epsilon relative plus 8 subnormal ULP absolute).
The stored total is then discarded from internal state; future output is always
recomputed. Restarts without the redundant total can restore both components.
Restart output continues to include SpeciesRst_WTC through ?ALL?. Boundary
output templates use ?ADVWTC?: physical advected species plus derived WTC when
active. Ordinary configurations without WTC retain their advected-only output.
The BC map accepts all species IDs so WTC can also be requested explicitly.

## PDER and optics

PDER includes WTCPI once in SNAOM and R_OMSNA (OM/SNA). Existing dry DBRCPOA
exclusion remains. PDER-selected LUT size interpolation applies to SNA/ordinary
OC bins 1/3; white-carbon bin 8 retains its existing LUT size.

Online growth/AOD, surface/water and heterogeneous chemistry use aggregate bin8.
Cloud-J reads WTCPI. RRTMG receives the same mass through optical slot10 and
its WTC/BRCT/PM masks. No new LUT records or radiative masks are required.

## File cascade and validation

Headers/brc_wtc_output_mod.F90 centralizes sampling-time output and restart
checks. Headers CMake, species metadata/union, brc_mod, aerosol_mod, diagnostics_mod,
History_Write, Planeflight and the restart reader use the derived-total contract.
Optional dry-deposition-height-adjusted SpeciesConcALT1_WTC is not added; WTC
has no independent deposition velocity. Standard VV/MND outputs include WTC.
Fullchem before/after-chemistry concentration diagnostics also derive the total
at sampling. HISTORY templates retain WTC boundary output; deposition helpers list physical
components only. Tests cover output units/timing, mismatched restart totals,
missing components, physical sums, PDER and output-path wiring.

This revision needs fresh compiled checks. Prior standalone and RRTMG OFF/ON
builds passed for the preceding three-stock implementation only. Full native
transport/deposition/restart IO/optical-output and atmospheric SOA qualification
remain open. Independent transport does not guarantee bitwise agreement with
historical single-tracer WTC trajectories. No allocation or model run has been
requested for this revision.
