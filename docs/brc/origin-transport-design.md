# Origin transport: unresolved acceptance gates

This is an offline design specification, not an implemented transport scheme.
The v14.8 origin prototype independently transports four registered species per
physical BrC parent. Its country-source and process bookkeeping can be tested,
but aggregate transport closure has failed. Initial country configurations also
failed parent invariance because a tag insertion split HEMCO's CO/SOAP source
inheritance chain. Corrected configurations require separate runtime checks.
No export or deposition efficiency is accepted.

## Evidence and impossible combination

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
