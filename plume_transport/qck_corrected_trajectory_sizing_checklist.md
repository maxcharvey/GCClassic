# QCK corrected-trajectory sizing diagnostic checklist

This checklist implements the independent science review for the diagnostic-only
2019-08-05 corrected-trajectory run. It does not authorize a production cap.

- [x] Start only from the accepted, hash-checked 2019-08-05 parent restart.
- [x] Keep the native QCK survey disabled and mutually exclusive.
- [x] Require explicit temporary event/call/run ceilings of 10/10/10 kg.
- [x] Make sizing instrumentation opt-in and fail closed on invalid activation.
- [x] Keep the instrumentation output-only; the existing bounded correction,
  not the instrumentation, remains responsible for accepted tracer-state changes.
- [x] Convert pressure shortfall to mass with the existing
  `closure_hPa * area_m2 * g0_100` relation, with `g0_100 = 100/g0`.
- [x] Record maximum closure-eligible attempted event, accepted microclosure
  event, accepted species-call sum, species index/name, model date/time,
  TPCORE invocation ordinal, and I/J/K.
- [x] Use a total tie-break order of date, time, invocation ordinal, species,
  K, J, and I after the event value.
- [x] Exclude invalid-donor and over-ceiling fatal outcomes from sizing
  candidates; their existing fatal messages remain the breach record.
- [x] Independently sum accepted species-call closures and reconcile them with
  the existing `f8` run total using `1e-12 kg` absolute and `1e-10` relative
  tolerances.
- [x] Pass compiled and Python regression tests.
- [x] Prove diagnostics-off/on equality for endpoint restarts and normalized
  existing ledgers on the same short full-model control.
- [x] Prove normalized one-thread/eight-thread and repeated eight-thread sizing
  summary equality.
- [x] Build and hash a fresh executable; do not overwrite the production binary.
- [x] Obtain independent run-steward approval for the exact manifest and runner.
- [x] Run one complete 2019-08-05 day with sizing enabled and native survey
  variables unset.
- [x] Treat a missing final summary or any 10 kg ceiling breach as incomplete.
- [x] Quarantine every diagnostic history/restart from chaining, collocation,
  production acceptance, and science claims.
- [ ] Obtain separate science/policy review before choosing tight production
  event/call ceilings; retain the 10 kg daily cap.
