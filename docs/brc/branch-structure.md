# BrC repository branches

Established 2026-10-08. This convention applies to the maxcharvey forks of
GCClassic, GEOS-Chem, HEMCO and Cloud-J.

## Release and development baselines

- `main` is the exact official GCClassic 14.8.0 release baseline. Component
  `main` branches use the commits pinned by that release: GEOS-Chem 14.8.0,
  HEMCO 3.13.0 and the release's Cloud-J commit. Do not merge custom BrC work
  into `main`.
- `max/brc` is the accepted custom BrC development baseline. It starts from
  the corrected FINN-mass/GFAS-profile hybrid used for the successful
  May-September 2018 WE-CAN season. Merge reviewed BrC development here.
- `accepted/wecan-finn-gfas-2018-20261008` records the exact accepted source
  checkpoint in all four repositories. Later documentation commits may
  advance `max/brc` without changing this acceptance tag.
- `baseline/gcclassic-14.8.0` records each official release component commit.

RRTMG remains disabled in the accepted seasonal build and configuration.
Its implementation is retained in source; the season exercised online AOD,
not RRTMG radiation. Optical tables remain organic-equivalent placeholders;
engineering acceptance does not establish physical BrC optics, forcing or
observational skill.

## Remaining development

- `feature/brc-country-tracking`: consolidated country-source and process
  development in GCClassic, GEOS-Chem and HEMCO. Unqualified experimental
  source is committed separately from the accepted hybrid.
- `feature/finn-gfas-gaussian-14.8` and
  `feature/finn-gfas-uniform-14.8`: separate injection sensitivities in
  GCClassic, GEOS-Chem and HEMCO.
- `plume-transport/initial-source-bridge`: independent plume work in
  GCClassic and GEOS-Chem; not part of accepted FINN/GFAS production.

Archived experiments and original branch/worktree tips are retained under
`archive/2026-10-08/`. Snapshot commits preserve existing source bytes;
their presence on GitHub does not qualify an experiment as production.
Legacy run directories and historical worktree paths remain available.

## Component pins and publishing

GCClassic uses exact submodule commit IDs, not moving component branch tips.
Commit and publish component work first, then commit and publish the wrapper
gitlinks. Verify a fresh recursive checkout before retiring old branches.
Advance upstream releases on `main`, then integrate the upstream update into
`max/brc` with appropriate engineering checks.

For the accepted development checkout:

```sh
git clone --branch max/brc --recurse-submodules https://github.com/maxcharvey/GCClassic.git
```

For the exact accepted checkpoint, check out the acceptance tag and update
submodules recursively. Reproducing the archived simulation additionally
requires its external inputs, restart, build environment and run settings.
The source manifest, configuration hashes, binary checksum and receipt
locations are recorded in `accepted-wecan-2018.json` beside this document.
