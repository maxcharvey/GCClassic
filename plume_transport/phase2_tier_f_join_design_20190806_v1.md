# Phase-2 Tier-F source-record-preserving join design

## Scope

This implementation performs only the released Phase-2 join for the
2019-08-06 FIREX-AQ Tier-F carrier.  It does not reaggregate to 60 seconds,
match model output, construct cohorts, calculate statistics, interpret
results, change model configuration, build GCClassic, or run a model.

The frozen v2 evaluation and inventory contracts remain authoritative.  This
file records the implementation choices needed where those contracts require
record preservation but deliberately do not prescribe a storage layout.

## Inputs

- The sealed v1 root supplies final `mrg01` R3, AOP R2, FSU R1, SP2 R4, and
  AMS R3.
- The sealed v2 root supplies FIRE-FLAGS R9, FIRE-FLAG table R12, and the
  already accepted semantic audit.
- All payload, contract, seal, and audit hashes are checked before output-root
  reservation.

## Stable identity

Every ICARTT record ID is:

```text
<payload-sha256>:<zero-based-data-record-ordinal>
```

Every R12 record ID is:

```text
<R12-payload-sha256>:worksheet-row-<row-number>
```

`source_record_inventory.csv` records the input product, stable ID, ordinal or
worksheet row, time bounds, raw-record byte count, and raw-record SHA-256.
The immutable sealed payload plus ordinal and raw-record hash is the lossless
record authority; source values are never rewritten in that inventory.

## Temporal relationship

- The carrier interval is its declared half-open
  `[Time_Start, Time_Stop)`.
- R9, AOP, FSU, and SP2 are audited continuous one-second products.  Their
  records use exact one-second half-open intervals beginning at their declared
  time.
- AMS supplies explicit half-open `[Time_Start, Time_Stop)` bounds.
- R12 inclusive intervals use their audited half-open equivalent
  `[start, end + 1 second)`.
- A carrier/source link exists when the two declared half-open intervals have
  positive overlap.

No nearest fill, interpolation, fallback, averaging, or source-record
deduplication is allowed.  One-to-many and many-to-one relationships are
retained as separate rows in `carrier_source_links.csv`.

## Outputs

- `source_record_inventory.csv`: immutable source-record identities and raw
  hashes for all six ICARTT inputs plus the 25 relevant R12 rows.
- `carrier_source_links.csv`: one row per positive-overlap temporal
  relationship, including overlap bounds and duration.
- `carrier_join.csv`: one row per carrier record containing carrier identity,
  protected raw-record hash, time/navigation fields, exact R9/AOP/FSU/SP2
  tokens, R12 lexical metadata where present, and semicolon-delimited AMS
  source IDs.  The AMS list is an index only; no AMS values are aggregated.
- `validation.json`: fail-closed gate results and mapping/count inventories.
- `run_manifest.json`: command, interpreter, input/code hashes, mapping rules,
  output inventory, and environment exception.
- `ARTIFACT_MANIFEST.json`: SHA-256 and byte size for every published artifact.
- `PHASE2_JOIN_SEAL.json`: written last after every validation passes.

## Protected carrier policy

The complete carrier payload remains in the sealed v1 root.  Every carrier
record receives a raw-line SHA-256 and byte count.  The join copies only
explicitly declared time/navigation fields and protected R9 mirror tokens;
all other carrier variables remain authoritative only in the unchanged
sealed payload.  Validation rereads the carrier and proves the inventory and
join reference the same ordinal, raw bytes, times, and payload hash.

## Fail-closed conditions

Stop without a seal if any frozen hash changes, an output root already exists,
an ICARTT schema or row width changes, time bounds are invalid, an exact
one-second source is missing or duplicated for a carrier row, an R9/R12
mapping changes, a protected mirror differs beyond the frozen audited
sentinel/serialization rules, a lexical identifier is altered, a source
record is omitted from the inventory, or a published artifact changes before
the seal is written.

## Reproduction

Primary and reproduction runs use distinct fresh roots and the same pinned
contract.  Reproduction acceptance compares normalized artifact roles:
`source_record_inventory.csv`, `carrier_source_links.csv`,
`carrier_join.csv`, and `validation.json` must be byte-identical.  Manifests
and seals may differ only in output path, command, and creation time.
