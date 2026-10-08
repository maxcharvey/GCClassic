#!/usr/bin/env python3
"""Independently validate FIREX-AQ Tier-F paired-description artifacts."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCIENCE_OUTPUTS = (
    "paired_points.csv",
    "paired_summary.csv",
    "metric_release_status.csv",
    "paired_description_summary.json",
)
BLOCKED = "inconclusive_insufficient_independent_support"


class ValidationError(RuntimeError):
    """Raised when paired-description acceptance validation fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_artifact_manifest(root: Path) -> dict[str, str]:
    manifest = json.loads((root / "ARTIFACT_MANIFEST.json").read_text())
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValidationError(f"invalid artifact manifest at {root}")
    for name, expected in artifacts.items():
        actual = sha256_file(root / name)
        if actual != expected:
            raise ValidationError(f"{root.name}/{name} hash mismatch")
    return artifacts


def independent_quantile(
    values: np.ndarray, weights: np.ndarray, ordinals: np.ndarray, q: float
) -> float:
    ordering = sorted(
        range(len(values)), key=lambda index: (values[index], ordinals[index])
    )
    decimal_weights = [
        Decimal(repr(float(weights[index]))) for index in ordering
    ]
    target = Decimal(repr(q)) * sum(decimal_weights, Decimal(0))
    cumulative = Decimal(0)
    for index, weight in zip(ordering, decimal_weights):
        cumulative += weight
        if cumulative >= target:
            return float(values[index])
    return float(values[ordering[-1]])


def independent_metrics(
    observation: np.ndarray,
    model: np.ndarray,
    weights: np.ndarray,
    ordinals: np.ndarray,
) -> dict[str, float]:
    residual = model - observation

    def triplet(values: np.ndarray) -> tuple[float, float, float]:
        return tuple(
            independent_quantile(values, weights, ordinals, q)
            for q in (0.25, 0.5, 0.75)
        )

    oq25, omed, oq75 = triplet(observation)
    mq25, mmed, mq75 = triplet(model)
    rq25, rmed, rq75 = triplet(residual)
    return {
        "observation_q25": oq25,
        "observation_median": omed,
        "observation_q75": oq75,
        "model_q25": mq25,
        "model_median": mmed,
        "model_q75": mq75,
        "residual_q25": rq25,
        "residual_median": rmed,
        "residual_q75": rq75,
        "mean_bias": math.fsum(
            float(weight) * float(value)
            for weight, value in zip(weights, residual)
        ),
        "MAE": math.fsum(
            float(weight) * abs(float(value))
            for weight, value in zip(weights, residual)
        ),
        "RMSE": math.sqrt(
            math.fsum(
                float(weight) * float(value) * float(value)
                for weight, value in zip(weights, residual)
            )
        ),
    }


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=2e-14, abs_tol=2e-14)


def validate(
    contract_path: Path, primary: Path, reproduction: Path
) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    primary_artifacts = verify_artifact_manifest(primary)
    reproduction_artifacts = verify_artifact_manifest(reproduction)
    byte_results: dict[str, bool] = {}
    for name in SCIENCE_OUTPUTS:
        identical = (primary / name).read_bytes() == (reproduction / name).read_bytes()
        byte_results[name] = identical
        if not identical:
            violations.append(f"{name} is not byte-identical")

    primary_run = json.loads((primary / "run_manifest.json").read_text())
    reproduction_run = json.loads((reproduction / "run_manifest.json").read_text())
    for label, run in (("primary", primary_run), ("reproduction", reproduction_run)):
        if run.get("blocked_metrics_calculated") is not False:
            violations.append(f"{label} run did not keep blocked metrics closed")
        if run.get("bootstrap_executed") is not False:
            violations.append(f"{label} run executed bootstrap")
        if run.get("model_execution") is not False:
            violations.append(f"{label} run executed model")
        if run["source"]["contract"]["sha256"] != sha256_file(contract_path):
            violations.append(f"{label} contract hash mismatch")

    points = read_csv(primary / "paired_points.csv")
    summaries = read_csv(primary / "paired_summary.csv")
    releases = read_csv(primary / "metric_release_status.csv")
    summary_json = json.loads((primary / "paired_description_summary.json").read_text())
    expected_rows = {
        "abs_405": 2041,
        "abs_532": 2041,
        "abs_664": 2041,
        "AAE_405_664": 1935,
    }
    endpoint_counts: dict[str, int] = {}
    formula_checks = 0
    metric_checks = 0
    for endpoint, expected in expected_rows.items():
        endpoint_points = [row for row in points if row["endpoint"] == endpoint]
        endpoint_counts[endpoint] = len(endpoint_points)
        if len(endpoint_points) != expected:
            violations.append(f"{endpoint} row count differs from {expected}")
            continue
        ordinals = np.asarray(
            [int(row["carrier_ordinal"]) for row in endpoint_points], dtype=np.int64
        )
        if list(ordinals) != sorted(ordinals):
            violations.append(f"{endpoint} carrier order changed")
        keys = [
            (row["carrier_source_record_id"], row["carrier_ordinal"])
            for row in endpoint_points
        ]
        if len(keys) != len(set(keys)):
            violations.append(f"{endpoint} paired-point keys are not unique")
        observation = np.asarray(
            [float(row["observation"]) for row in endpoint_points], dtype=np.float64
        )
        model = np.asarray(
            [float(row["model"]) for row in endpoint_points], dtype=np.float64
        )
        residual = np.asarray(
            [float(row["residual_model_minus_observation"]) for row in endpoint_points],
            dtype=np.float64,
        )
        if not all(
            np.all(np.isfinite(values)) for values in (observation, model, residual)
        ):
            violations.append(f"{endpoint} has nonfinite paired values")
        if not np.allclose(residual, model - observation, rtol=0.0, atol=1e-14):
            violations.append(f"{endpoint} residual convention failed")
        formula_checks += len(endpoint_points)

        clusters = [row["cluster_id"] for row in endpoint_points]
        cluster_counts = Counter(clusters)
        expected_cluster_weight = 1.0 / len(cluster_counts)
        cb_weights = np.asarray(
            [float(row["cluster_balanced_weight"]) for row in endpoint_points],
            dtype=np.float64,
        )
        rw_weights = np.asarray(
            [float(row["row_weight"]) for row in endpoint_points], dtype=np.float64
        )
        if not close(float(np.sum(cb_weights)), 1.0):
            violations.append(f"{endpoint} cluster weights do not sum to one")
        if not close(float(np.sum(rw_weights)), 1.0):
            violations.append(f"{endpoint} row weights do not sum to one")
        for cluster in cluster_counts:
            total = math.fsum(
                float(weight)
                for weight, row in zip(cb_weights, endpoint_points)
                if row["cluster_id"] == cluster
            )
            if not close(total, expected_cluster_weight):
                violations.append(f"{endpoint}/{cluster} cluster total is unequal")

        for weighting, weights in (
            ("cluster_balanced_primary", cb_weights),
            ("row_weighted_secondary", rw_weights),
        ):
            published = [
                row
                for row in summaries
                if row["endpoint"] == endpoint and row["weighting"] == weighting
            ]
            if len(published) != 1:
                violations.append(f"{endpoint}/{weighting} summary is not unique")
                continue
            calculated = independent_metrics(observation, model, weights, ordinals)
            for field, value in calculated.items():
                metric_checks += 1
                if not close(float(published[0][field]), value):
                    violations.append(
                        f"{endpoint}/{weighting}/{field} independent recompute failed"
                    )

    if len(summaries) != 8:
        violations.append("paired summary must contain exactly eight rows")
    for row in summaries:
        if row["point_summary_status"] != "eligible_calculated":
            violations.append("point-summary status changed")
        if row["mean_error_status"] != "eligible_calculated":
            violations.append("mean-error status changed")

    required_blocked = {
        "Pearson_Spearman": "not_calculated",
        "whole_cluster_interval_95": "not_calculated",
        "age_pattern": "not_calculated",
        "bootstrap": "not_executed",
    }
    for endpoint in expected_rows:
        for metric_class, action in required_blocked.items():
            matching = [
                row
                for row in releases
                if row["endpoint"] == endpoint
                and row["metric_class"] == metric_class
                and row["action"] == action
            ]
            if len(matching) != 1:
                violations.append(
                    f"{endpoint}/{metric_class} blocked release state failed"
                )
    if summary_json.get("blocked", {}).get("Pearson_Spearman") != BLOCKED:
        violations.append("summary association state changed")
    if any(summary_json.get("prohibitions_verified", {}).values()):
        violations.append("a prohibited action is marked true")
    serialized = json.dumps(summary_json, sort_keys=True).lower()
    forbidden_value_fields = (
        "pearson_value",
        "spearman_value",
        "interval_lower",
        "interval_upper",
        "p_value",
        "bootstrap_draw",
    )
    for field in forbidden_value_fields:
        if field in serialized:
            violations.append(f"blocked value field was emitted: {field}")

    result = {
        "schema_version": 1,
        "verdict": "PASS" if not violations else "FAIL",
        "rule_violations": violations,
        "primary_root": str(primary),
        "reproduction_root": str(reproduction),
        "contract_sha256": sha256_file(contract_path),
        "primary_artifact_manifest_sha256": sha256_file(
            primary / "ARTIFACT_MANIFEST.json"
        ),
        "reproduction_artifact_manifest_sha256": sha256_file(
            reproduction / "ARTIFACT_MANIFEST.json"
        ),
        "artifact_manifests_verified": {
            "primary": len(primary_artifacts),
            "reproduction": len(reproduction_artifacts),
        },
        "byte_identical_science_outputs": byte_results,
        "endpoint_rows": endpoint_counts,
        "paired_formula_checks": formula_checks,
        "independently_recomputed_metric_values": metric_checks,
        "blocked_value_fields_absent": not any(
            field in serialized for field in forbidden_value_fields
        ),
        "bootstrap_executed": False,
        "scientific_interpretation": False,
        "model_execution": False,
    }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--primary-root", required=True, type=Path)
    parser.add_argument("--reproduction-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = validate(args.contract, args.primary_root, args.reproduction_root)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
