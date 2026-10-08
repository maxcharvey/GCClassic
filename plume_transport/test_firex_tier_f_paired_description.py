from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from firex_tier_f_paired_description import (
    BLOCKED_STATUS,
    PairedDescriptionError,
    SCIENCE_OUTPUTS,
    build_outputs,
    cluster_balanced_weights,
    sha256_file,
    summarize_values,
    weighted_quantile,
    write_run,
)


CONTRACT = Path("plume_transport/tier_f_paired_description_contract_20190806_v1.json")


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(contract: dict):
    return build_outputs(contract)


def test_weighted_quantile_inverse_ecdf() -> None:
    values = np.asarray([1.0, 2.0, 3.0, 4.0])
    weights = np.full(4, 0.25)
    ordinals = np.arange(4)
    assert weighted_quantile(values, weights, ordinals, 0.25) == 1.0
    assert weighted_quantile(values, weights, ordinals, 0.50) == 2.0
    assert weighted_quantile(values, weights, ordinals, 0.75) == 3.0


def test_weighted_quantile_uses_weights() -> None:
    values = np.asarray([1.0, 2.0, 3.0])
    weights = np.asarray([0.1, 0.8, 0.1])
    ordinals = np.arange(3)
    assert weighted_quantile(values, weights, ordinals, 0.25) == 2.0
    assert weighted_quantile(values, weights, ordinals, 0.75) == 2.0


def test_weighted_quantile_rejects_nonpositive_weight() -> None:
    with pytest.raises(PairedDescriptionError):
        weighted_quantile(
            np.asarray([1.0]), np.asarray([0.0]), np.asarray([0]), 0.5
        )


def test_weighted_quantile_rejects_nonfinite_value() -> None:
    with pytest.raises(PairedDescriptionError):
        weighted_quantile(
            np.asarray([np.nan]), np.asarray([1.0]), np.asarray([0]), 0.5
        )


def test_cluster_balanced_weights_equalize_clusters() -> None:
    weights = cluster_balanced_weights(["a", "a", "a", "b"])
    assert np.sum(weights[:3]) == pytest.approx(0.5)
    assert weights[3] == pytest.approx(0.5)
    assert np.sum(weights) == pytest.approx(1.0)


def test_cluster_balanced_weights_reject_empty_id() -> None:
    with pytest.raises(PairedDescriptionError):
        cluster_balanced_weights(["a", ""])


def test_summarize_values_residual_convention() -> None:
    metrics = summarize_values(
        np.asarray([1.0, 2.0]),
        np.asarray([2.0, 4.0]),
        np.asarray([0.5, 0.5]),
        np.asarray([0, 1]),
    )
    assert metrics["mean_bias"] == pytest.approx(1.5)
    assert metrics["MAE"] == pytest.approx(1.5)
    assert metrics["RMSE"] == pytest.approx(math.sqrt(2.5))


def test_builds_expected_number_of_points(built) -> None:
    points, _, _, _, _ = built
    assert len(points) == 3 * 2041 + 1935


def test_builds_two_weightings_per_endpoint(built) -> None:
    _, summaries, _, _, _ = built
    assert len(summaries) == 8
    assert {row["weighting"] for row in summaries} == {
        "cluster_balanced_primary",
        "row_weighted_secondary",
    }


def test_absorption_counts_match_sealed_cohort(built) -> None:
    _, summaries, _, _, _ = built
    absorption = [
        row
        for row in summaries
        if row["endpoint"] == "abs_405"
        and row["weighting"] == "cluster_balanced_primary"
    ][0]
    assert absorption["rows"] == 2041
    assert absorption["model_states"] == 17
    assert absorption["clusters"] == 2


def test_aae_counts_match_sealed_cohort(built) -> None:
    _, summaries, _, _, _ = built
    aae = [
        row
        for row in summaries
        if row["endpoint"] == "AAE_405_664"
        and row["weighting"] == "cluster_balanced_primary"
    ][0]
    assert aae["rows"] == 1935
    assert aae["finite_negative_observations"] == 42


def test_all_points_are_finite(built) -> None:
    points, _, _, _, _ = built
    assert all(
        math.isfinite(row[field])
        for row in points
        for field in (
            "observation",
            "model",
            "residual_model_minus_observation",
            "cluster_balanced_weight",
            "row_weight",
        )
    )


def test_residual_is_model_minus_observation(built) -> None:
    points, _, _, _, _ = built
    for row in points[::251]:
        assert row["residual_model_minus_observation"] == pytest.approx(
            row["model"] - row["observation"]
        )


def test_cluster_weights_sum_to_one_per_endpoint(built) -> None:
    points, _, _, _, _ = built
    for endpoint in {row["endpoint"] for row in points}:
        assert sum(
            row["cluster_balanced_weight"]
            for row in points
            if row["endpoint"] == endpoint
        ) == pytest.approx(1.0)


def test_blocked_metrics_are_not_calculated(built) -> None:
    _, _, releases, summary, _ = built
    blocked = [
        row
        for row in releases
        if row["metric_class"] in {
            "Pearson_Spearman",
            "whole_cluster_interval_95",
            "age_pattern",
            "bootstrap",
        }
    ]
    assert blocked
    assert all(row["action"] in {"not_calculated", "not_executed"} for row in blocked)
    assert summary["blocked"]["Pearson_Spearman"] == BLOCKED_STATUS
    assert summary["prohibitions_verified"]["bootstrap_executed"] is False


def test_summary_contains_no_association_or_interval_values(built) -> None:
    _, _, _, summary, _ = built
    serialized = json.dumps(summary, sort_keys=True)
    for forbidden in ("pearson_value", "spearman_value", "interval_lower", "p_value"):
        assert forbidden not in serialized.lower()


def test_write_run_creates_declared_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "primary"
    write_run(CONTRACT, root, "focused-test")
    for name in (*SCIENCE_OUTPUTS, "run_manifest.json", "ARTIFACT_MANIFEST.json"):
        assert (root / name).is_file()


def test_artifact_manifest_verifies(tmp_path: Path) -> None:
    root = tmp_path / "primary"
    write_run(CONTRACT, root, "focused-test")
    manifest = json.loads((root / "ARTIFACT_MANIFEST.json").read_text())
    assert all(
        sha256_file(root / name) == expected
        for name, expected in manifest["artifacts"].items()
    )


def test_two_runs_have_byte_identical_science_outputs(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_run(CONTRACT, first, "first")
    write_run(CONTRACT, second, "second")
    assert all(
        (first / name).read_bytes() == (second / name).read_bytes()
        for name in SCIENCE_OUTPUTS
    )


def test_paired_points_preserve_endpoint_carrier_order(tmp_path: Path) -> None:
    root = tmp_path / "primary"
    write_run(CONTRACT, root, "focused-test")
    with (root / "paired_points.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for endpoint in ("abs_405", "abs_532", "abs_664", "AAE_405_664"):
        ordinals = [
            int(row["carrier_ordinal"]) for row in rows if row["endpoint"] == endpoint
        ]
        assert ordinals == sorted(ordinals)
