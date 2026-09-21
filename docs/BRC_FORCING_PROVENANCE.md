# BrC run provenance and forcing definitions

Before building, initialize the recorded dependencies and check the source:

```sh
git submodule update --init --recursive
python3 scripts/check_brc_submodule_contract.py --repo .
```

Do not update submodules blindly in a development tree with intentional
uncommitted gitlink/source changes. The checker is read-only and requires
clean, initialized, exact recursive pins. After publication, add `--remote`
to require the integration branch tips in all four development forks to
equal the local source. CI runs the local check, not the remote-tip check,
because pull-request merge refs need not equal branch tips.

For **every new RRTMG science run**, copy
[`brc_forcing_provenance.template.json`](brc_forcing_provenance.template.json)
to the run directory, fill every null and validate it before analysis:

```sh
python3 /path/to/GCClassic/scripts/check_brc_provenance.py forcing_provenance.json
```

The template deliberately fails until completed. Paths are relative to the
record, or absolute. Use `git rev-parse HEAD` in each repository and
`sha256sum` on the actual installed executable, initial restart, configs,
and **every optical table used**, not just a representative file. Repeat
the optical artifact roles for multiple tables. Record the build-time pins,
not whatever HEAD happens to be at analysis time. Cached CMake labels can
be stale and do not override a recorded source freeze and executable hash.
`--schema-only` explicitly skips file/hash verification and is not sufficient
for a run acceptance record. The checker never writes inputs or output.

Minimum label:

`metric / boundary / sky / baseline / species_scope / inventory / optics_scheme`

Give the inventory version and bleaching/optical state explicitly. Define
flux signs and which subtraction is performed in `radiation.flux_convention`;
list exact archived field names and their sampling. A full-minus-masked
RRTMG result is not automatically absorption-only forcing, and a no-BrC
baseline is not a preindustrial baseline. Different sky/boundary definitions
need separate records or explicitly defined separate analyses.

## Qualification and absorption

Engineering runs use `purpose: engineering`,
`qualification.status: engineering_only`, and explicit limitations.
Organic-equivalent BrC tables remain `qualification.optics: placeholder`.
Do not relabel a successful smoke test as physical validation.

Science-purpose records require `reviewed_for_scope`, qualified optics,
reviewer/date/regime scope, and hashed review documents under the artifact
roles `review_optics`, `review_parameters`, `review_inventory`,
`review_operator`. One review document may cover multiple review roles.
Those documents must establish the actual approvals; a schema PASS is
**not** a scientific review and cannot certify the contents of a document.
The checker rejects missing evidence and contradictory structured status,
but a human must check the scientific claims and the limitations text.

Leave `absorption.method: unavailable` when no verified absorption product
exists. A derived product requires paired instantaneous AOD/SSA in the same
bins, exact `aod_fields`/`ssa_fields`, evidence, and a hashed
`absorption_output` artifact. An `online_aaod` product requires exact
`aaod_fields`, evidence, that artifact, and sampling `instantaneous` or
`mean_of_online_aaod`. These are declared contracts, not calculations by
this checker. Do not multiply separately time-averaged AOD and SSA:
`mean[AOD*(1-SSA)]` generally differs from `mean[AOD]*(1-mean[SSA])`.
The 14.8 smoke fixtures use instantaneous radiation snapshots saved hourly;
their cadence alone does not make them hourly averages.

Historical integration cases retain their original Markdown source/config
records. Do not pretend a new template existed before those runs or assign
them a newer source commit. New issue-audit runs use the JSON contract.
