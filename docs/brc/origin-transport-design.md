# Origin transport: unresolved acceptance gates

This is an offline design specification, not an implemented transport scheme.
The v14.8 origin prototype independently transports four registered species per
physical BrC parent. Its country-source and process bookkeeping can be tested,
but aggregate operator closure has failed. PBL mixing is the first large failure in
the corrected country fixture, before the second advection call; both mixing
and advection require a qualified treatment. Initial country configurations also
failed parent invariance because a tag insertion split HEMCO's CO/SOAP source
inheritance chain. Corrected one-hour and full-day configurations pass
strict parent invariance for both injection scenarios; scenario-specific receipts
remain required.
No export or deposition efficiency is accepted.

## Contract before a live coupled repair

The native parent remains the physical reference. Preserve its concentrations,
emissions, injection, aerosol participation and operator decisions. A diagnostic
must pass matched capture-OFF/reference and capture-ON/OFF comparisons before its
evidence is used. A candidate origin scheme then has separate acceptance gates:

- Finite, nonnegative final USA/CAN/ROW/UNT inventories and cellwise additivity
  to the frozen parent. Report signed, L1 and maximum residuals separately.
- Each origin's mass target derived from actual incoming inventory, native
  source/sink forcing and documented restoration or cleanup accounting. Test
  whether all targets are compatible with the frozen parent; record infeasibility
  rather than silently changing targets or assigning created mass a country.
- Spatial fidelity for plume position, vertical displacement, PBL exchange and
  country-boundary transfer, using nontrivial partitions and the frozen failing
  cases. Conservation alone does not establish geographic accuracy.
- Explicit treatment of signed countergradient/advection intermediates, rollback
  masks, safe-division branches and Qck corrections. Signed replay is diagnostic;
  it does not satisfy the final-origin positivity gate.
- Explicit refusal or reviewed treatment for empty donors, zero support,
  singular systems and incompatible constraints. Inventory and documented forcing
  must supply any claimed provenance.

Preregister numeric and scientific acceptance criteria before testing a live
candidate. Cell clipping followed by rescaling to the parent, silent origin
transfers, relaxed thresholds and unreviewed fallbacks are excluded. Any proposed
allocation of native corrections requires its own conservation, provenance and
spatial tests. PBL mixing and advection must both qualify before country metrics
are accepted; solving the first observed failure is insufficient.

## Evidence and impossible combination

The first surface PBL-mixing call produces species L1 discrepancies of about
8,648 kg FSOAP, 13,551 kg NPBRCPOA, 35,623 kg PBRCPOA and 112,341 kg DBRCPOA
despite source partition closure within numerical roundoff. Native VDIFF
independently rolls back a
tracer's countergradient column when it violates its threshold, clips negative
post-diffusion cells, and restores each tracer's column mass. These operations
need not act identically on a parent and its components. The opt-in six-phase
mixing capture localizes these decisions without changing them. Applying a
parent restoration factor to every origin alone does not establish positivity,
placement or an origin-consistent countergradient treatment.

Two 600-second native control transport captures replay all parent X/Y/Z flux
divergences, pressure division and cap duplication. BRCSOA has negative raw
intermediate cells, which Qck later repairs. No sum of nonnegative origins can
equal a negative parent cell. A specification must therefore allow and audit
signed intermediates, restrict its initial domain, or separately change/review
parent positivity. It cannot silently claim all three conditions at every stage.

The positive DBRCPOA capture also rejects simple face flux times initial donor
fraction: some outgoing fluxes exceed available donor-origin stock, even though
incoming parent flux leaves a positive cell. The synthetic periodic fixture makes
this failure explicit. A parent flux sum alone does not describe origin support.

## Reconstruction-level candidate

Consistent Multi-fluid Advection (Plewa & Müller, 1999,
<https://arxiv.org/pdf/astro-ph/9807241>) is a relevant PPM precedent. It makes
partial face fluxes consistent with the carrier flux by adjusting reconstructed
interface fractions. Such interface consistency is distinct from post-transport
cell-state renormalization; the latter remains excluded. Coupled monotonicity and
composition reconstruction are required in addition to face-sum closure. This
paper does not qualify the GEOS-Chem fvDAS cross-term implementation.

Before a live change, extend the offline capture to record native X/Y/Z predictor
support, limiter/reconstruction decisions, swept multi-cell Courant contributions,
and actual Qck donor/receiver transfers. A cleanup delta alone cannot identify
origin provenance. Periodic and polar faces must use one shared allocation for
both sides with the native geometry. Preserve the actual physical-parent flux and
all state arrays. Handle zero carrier support, zero-stock circulation and numerical
floor-created mass explicitly; refuse undetermined geographic attribution.

## Mechanical and placement tests

- Replay native parent stages before interpreting any allocation.
- Audit linear/reconstruction residuals, origin face sums, per-origin inventory
  conservation, finite values, aggregate closure and final nonnegativity.
- Keep pressure changes, polar averaging, cross predictors, cleanup and flooring
  distinct. Never normalize cell inventories to hide their residual.
- Test constant fractions, smooth mixtures, contacts and rare species; zero
  support, incoming credit, long Courant support, seams, poles and reversed flow.
- Compare origin support, centroid, spread and boundary crossings to independent
  analytic references. Refine timestep and spatial resolution separately.
- Scale attribution errors to the emitted cohort, not only to the large preexisting
  parent burden. Define acceptable placement/export/deposition error before
  acceptance; those science tolerances are currently unspecified.
- Repeat a qualified implementation for surface and elevated/profile injection,
  then extend output intervals to daily before any longer integration.

The capture replay uses fp8 max-scale tolerance 1e-12 (fp4 1e-5). These are parser
and parent algebra gates, not tolerances for geographic attribution accuracy.
The implicit-mixing toy checks feasibility in admissible positive stages, while
its analytic counterexamples expose diffusion and within-step multi-face label
propagation. It is not a selected production replacement.

## Regional metrics remain distinct

A country-origin burden outside the source region is not first-passage export.
Gross outward flux counts recrossings; net export needs synchronized signed face
fluxes and regional budget closure. First passage requires crossing memory.
Receptor deposition needs matching emissions on a common carbon basis, complete
process accounting, remaining burden and the same cohort/injection scenario.
Native wet-loss fields are signed process tendencies where precipitation can
return material to air; preserve those signs and distinguish net loss from gross
scavenging. None of these accepted metrics follows from a tag name alone.
