# Polar topology validation correction

The frozen V1 source-phase results remain historical and immutable. A new
manufactured witness found that an unsupported polar winding exterior could
be skipped by the query latitude bounds, yielding UNS instead of refusal.
V2 rejects such rings during catalogue construction, before any query or
catalogue publication. The existing query-level check remains defensive.

All1632 rings of the pinned242-feature dataset have zero winding. Its source
hash, ordering, catalogue digest and1708 disabled stock candidates are unchanged.
This correction adds no polar classifier or geographic qualification. Record
the old failure witness and V2 geometry tests in the separate geometry phase;
do not rerun or rewrite frozen compiler/solver/source-allocation evidence.
