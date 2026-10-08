from decimal import Decimal

from plume_transport.firex_tier_f_evaluation_support import (
    _collapsed_states,
    _eligibility,
    age_stability,
    numeric_state,
)


def test_numeric_state_preserves_negative_and_sentinels() -> None:
    assert numeric_state("-0.25", "-9999") == "valid"
    assert numeric_state("-9999.0", "-9999") == "missing"
    assert numeric_state("-8888", "-9999") == "LLOD"
    assert numeric_state("-7777.0", "-9999") == "ULOD"
    assert numeric_state("nan", "-9999") == "invalid"


def test_age_stability_uses_closed_untruncated_envelope() -> None:
    assert age_stability(Decimal("1.5"), Decimal("0.25")) == (
        "[1,2)",
        "stable",
    )
    assert age_stability(Decimal("1.5"), Decimal("0.5")) == (
        "[1,2)",
        "crossing",
    )
    assert age_stability(Decimal("0.1"), Decimal("0.2")) == (
        "[0,0.5)",
        "crossing",
    )


def test_support_thresholds_are_not_relaxed() -> None:
    below = _eligibility(
        rows=29, states=10, clusters=5, nonzero_variation=True
    )
    assert below["Pearson_Spearman"] == (
        "inconclusive_insufficient_independent_support"
    )
    passed = _eligibility(
        rows=30, states=10, clusters=10, nonzero_variation=True
    )
    assert passed["Pearson_Spearman"] == "eligible"
    assert passed["cluster_interval_95"] == "eligible"


def test_contract_exposes_all_direct_payload_hashes() -> None:
    import json
    from pathlib import Path

    contract = json.loads(
        Path("plume_transport/tier_f_evaluation_support_contract_20190806_v1.json")
        .read_text(encoding="utf-8")
    )
    assert {
        "aop_payload",
        "fsu_payload",
        "sp2_payload",
        "ams_payload",
    } <= set(contract["frozen_hashes"])


def test_ams_state_collapse_is_explicit() -> None:
    from collections import Counter

    assert _collapsed_states(Counter()) == "no_linked_source"
    assert _collapsed_states(Counter(valid=2)) == "valid"
    assert _collapsed_states(Counter(valid=1, missing=1)) == (
        "mixed:missing+valid"
    )


def test_fsu_seconds_convert_to_frozen_hour_bins() -> None:
    seconds = Decimal("5400")
    uncertainty_seconds = Decimal("600")
    assert age_stability(
        seconds / Decimal(3600),
        uncertainty_seconds / Decimal(3600),
    ) == ("[1,2)", "stable")
