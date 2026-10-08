# Earliest-witness correction — 2026-10-07

The full V2 audit passes all fourteen native/plan/caller/stable-KL gates. It
quantifies the first historical scalar failure as BRCSOA19/46 (relative error
4.7702679468e-8 versus5e-12). Initial attribution to first FSOAP was an incorrect
assumption: that profile's scalar error8.7245551e-18 passes. Preserve the failed
first-witness script/assertion and initial reporting addendum; no numerical
acceptance was inferred from them. Three original scalar receipts fail:
BRCSOA19/46, DBRCPOA19/46, BRCSOA28/131. All remain unqualified historical fields.

`kl_witness_v2.py` explicitly checks the first two original scalar receipts pass
and the third fails, then repeats the actual earliest BRCSOA witness at150/200
digits. Only witness selection is corrected. No fixture, solver, plan or stable
receipt is rerun or changed; the full fourteen-profile V2 audit remains unchanged.
Final source/input/model guards and independent acceptance still required.
