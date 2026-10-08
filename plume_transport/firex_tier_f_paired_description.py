#!/usr/bin/env python3
"""Compute the frozen, supported FIREX-AQ Tier-F paired descriptions."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any, Mapping, Sequence

import numpy as np


SCIENCE_OUTPUTS = (
    "paired_points.csv",
    "paired_summary.csv",
    "metric_release_status.csv",
    "paired_description_summary.json",
)
BLOCKED_STATUS = "inconclusive_insufficient_independent_support"


class PairedDescriptionError(RuntimeError):
    """Raised when an input or frozen paired-description invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise PairedDescriptionError(f"{label} is absent: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise PairedDescriptionError(
            f"{label} SHA-256 changed: expected {expected}, got {actual}"
        )


def read_csv(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PairedDescriptionError(f"CSV has no header: {path}")
        return tuple(reader.fieldnames), list(reader)


def textual_bool(value: str, label: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise PairedDescriptionError(f"{label} is not a textual Boolean: {value!r}")


def finite_float(token: str, label: str) -> float:
    try:
        value = float(token)
    except (TypeError, ValueError) as exc:
        raise PairedDescriptionError(f"{label} is not numeric: {token!r}") from exc
    if not math.isfinite(value):
        raise PairedDescriptionError(f"{label} is not finite: {token!r}")
    return value


def weighted_quantile(
    values: np.ndarray,
    weights: np.ndarray,
    ordinals: np.ndarray,
    quantile: float,
) -> float:
    """Return the frozen inverse-empirical-CDF weighted quantile."""
    if values.ndim != 1 or weights.ndim != 1 or ordinals.ndim != 1:
        raise PairedDescriptionError("weighted_quantile inputs must be 1-D")
    if not (len(values) == len(weights) == len(ordinals)) or len(values) == 0:
        raise PairedDescriptionError("weighted_quantile inputs are empty/misaligned")
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(weights)):
        raise PairedDescriptionError("weighted_quantile inputs must be finite")
    if np.any(weights <= 0.0):
        raise PairedDescriptionError("weighted_quantile weights must be positive")
    if not 0.0 <= quantile <= 1.0:
        raise PairedDescriptionError("quantile is outside [0,1]")
    order = np.lexsort((ordinals, values))
    sorted_values = values[order]
    sorted_weights = weights[order]
    decimal_weights = [Decimal(repr(float(weight))) for weight in sorted_weights]
    target = Decimal(repr(quantile)) * sum(decimal_weights, Decimal(0))
    cumulative = Decimal(0)
    for value, weight in zip(sorted_values, decimal_weights):
        cumulative += weight
        if cumulative >= target:
            return float(value)
    return float(sorted_values[-1])


def cluster_balanced_weights(cluster_ids: Sequence[str]) -> np.ndarray:
    if not cluster_ids or any(not cluster for cluster in cluster_ids):
        raise PairedDescriptionError("cluster IDs must be nonempty")
    counts = Counter(cluster_ids)
    cluster_count = len(counts)
    weights = np.asarray(
        [1.0 / (cluster_count * counts[cluster]) for cluster in cluster_ids],
        dtype=np.float64,
    )
    if not math.isclose(float(np.sum(weights)), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise PairedDescriptionError("cluster-balanced weights do not sum to one")
    for cluster, count in counts.items():
        total = float(
            np.sum(weights[np.asarray([item == cluster for item in cluster_ids])])
        )
        if not math.isclose(
            total, 1.0 / cluster_count, rel_tol=0.0, abs_tol=1e-12
        ):
            raise PairedDescriptionError(
                f"cluster {cluster!r} does not receive equal total weight"
            )
        if count <= 0:
            raise PairedDescriptionError("impossible empty contributing cluster")
    return weights


def row_weights(row_count: int) -> np.ndarray:
    if row_count <= 0:
        raise PairedDescriptionError("row count must be positive")
    return np.full(row_count, 1.0 / row_count, dtype=np.float64)


def summarize_values(
    observation: np.ndarray,
    model: np.ndarray,
    weights: np.ndarray,
    ordinals: np.ndarray,
) -> dict[str, float]:
    if not (
        len(observation) == len(model) == len(weights) == len(ordinals)
        and len(observation) > 0
    ):
        raise PairedDescriptionError("summary inputs are empty/misaligned")
    if not np.all(np.isfinite(observation)) or not np.all(np.isfinite(model)):
        raise PairedDescriptionError("summary values must be finite")
    if not math.isclose(float(np.sum(weights)), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise PairedDescriptionError("summary weights do not sum to one")
    residual = model - observation

    def quartiles(values: np.ndarray) -> tuple[float, float, float]:
        return tuple(
            weighted_quantile(values, weights, ordinals, quantile)
            for quantile in (0.25, 0.5, 0.75)
        )

    obs_q25, obs_median, obs_q75 = quartiles(observation)
    model_q25, model_median, model_q75 = quartiles(model)
    residual_q25, residual_median, residual_q75 = quartiles(residual)
    return {
        "observation_q25": obs_q25,
        "observation_median": obs_median,
        "observation_q75": obs_q75,
        "model_q25": model_q25,
        "model_median": model_median,
        "model_q75": model_q75,
        "residual_q25": residual_q25,
        "residual_median": residual_median,
        "residual_q75": residual_q75,
        "mean_bias": float(np.sum(weights * residual, dtype=np.float64)),
        "MAE": float(np.sum(weights * np.abs(residual), dtype=np.float64)),
        "RMSE": float(
            np.sqrt(np.sum(weights * residual * residual, dtype=np.float64))
        ),
    }


def _compound_key(row: Mapping[str, str]) -> tuple[str, str]:
    return row["carrier_source_record_id"], row["carrier_ordinal"]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise PairedDescriptionError(f"refusing empty CSV output: {path.name}")
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _support_release(
    support_rows: Sequence[Mapping[str, str]], cohort: str
) -> None:
    relevant = [
        row
        for row in support_rows
        if row["cohort"] == cohort
        and row["age_bin"] == "all"
        and row["endpoint"] in {"abs_405", "abs_532", "abs_664"}
    ]
    if len(relevant) != 3:
        raise PairedDescriptionError(
            f"support inventory lacks three primary endpoint rows for {cohort}"
        )
    for row in relevant:
        if row["point_summary"] != "eligible":
            raise PairedDescriptionError(
                f"{cohort}/{row['endpoint']} point summary is not released"
            )
        if row["mean_bias_MAE_RMSE"] != "eligible":
            raise PairedDescriptionError(
                f"{cohort}/{row['endpoint']} mean errors are not released"
            )
        if row["Pearson_Spearman"] != BLOCKED_STATUS:
            raise PairedDescriptionError("association must remain blocked")
        if row["cluster_interval_95"] != BLOCKED_STATUS:
            raise PairedDescriptionError("cluster interval must remain blocked")


def _endpoint_values(
    endpoint: Mapping[str, Any],
    memberships: Sequence[Mapping[str, str]],
    carriers: Sequence[Mapping[str, str]],
    mechanical: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    cohort = endpoint["cohort"]
    result: list[dict[str, Any]] = []
    denominator = math.log(405.0 / 664.0)
    for membership, carrier, match in zip(memberships, carriers, mechanical):
        if not textual_bool(membership[cohort], cohort):
            continue
        if endpoint["id"] == "AAE_405_664":
            obs_short = finite_float(
                carrier[endpoint["observation_fields"][0]], "observed 405"
            )
            obs_long = finite_float(
                carrier[endpoint["observation_fields"][1]], "observed 664"
            )
            model_short = finite_float(
                match[endpoint["model_fields"][0]], "model 405"
            )
            model_long = finite_float(
                match[endpoint["model_fields"][1]], "model 664"
            )
            if min(obs_short, obs_long, model_short, model_long) <= 0.0:
                raise PairedDescriptionError(
                    "C_aae_primary contains a nonpositive AAE endpoint"
                )
            observation = -math.log(obs_short / obs_long) / denominator
            model = -math.log(model_short / model_long) / denominator
        else:
            observation = finite_float(
                carrier[endpoint["observation_field"]],
                f"{endpoint['id']} observation",
            )
            model = finite_float(
                match[endpoint["model_field"]], f"{endpoint['id']} model"
            )
        if not math.isfinite(observation) or not math.isfinite(model):
            raise PairedDescriptionError(f"{endpoint['id']} produced nonfinite value")
        result.append(
            {
                "endpoint": endpoint["id"],
                "unit": endpoint["unit"],
                "cohort": cohort,
                "carrier_source_record_id": membership["carrier_source_record_id"],
                "carrier_ordinal": int(membership["carrier_ordinal"]),
                "observation_time_utc": membership["observation_time_utc"],
                "cluster_id": membership["cluster_id"],
                "model_state_id": membership["model_state_id"],
                "fire_id": membership["r12_fire_id"],
                "plume_id": membership["r12_plume_id"],
                "transect_id": membership["r12_transect_id"],
                "direct_aop_source_record_id": carrier["aop__source_record_id"],
                "observation": observation,
                "model": model,
                "residual_model_minus_observation": model - observation,
            }
        )
    return result


def build_outputs(
    contract: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Path],
]:
    support_root = Path(contract["inputs"]["support_root"])
    paths = {
        "row_membership": support_root / "row_membership.csv",
        "support_inventory": support_root / "support_inventory.csv",
        "acceptance_seal": support_root / "ACCEPTANCE_SEAL.json",
        "mechanical_rows": Path(contract["inputs"]["mechanical_rows"]),
        "carrier_rows": Path(contract["inputs"]["carrier_rows"]),
    }
    for label, path in paths.items():
        verify_hash(path, contract["frozen_hashes"][label], label)

    seal = json.loads(paths["acceptance_seal"].read_text(encoding="utf-8"))
    if seal.get("status") != contract["expected"]["support_seal_status"]:
        raise PairedDescriptionError("evaluation-support acceptance seal is not PASS")

    _, memberships = read_csv(paths["row_membership"])
    _, support_rows = read_csv(paths["support_inventory"])
    _, mechanical = read_csv(paths["mechanical_rows"])
    _, carriers = read_csv(paths["carrier_rows"])
    expected_rows = int(contract["expected"]["carrier_rows"])
    if not (
        len(memberships) == len(mechanical) == len(carriers) == expected_rows
    ):
        raise PairedDescriptionError("input row counts differ from the contract")
    membership_keys = [_compound_key(row) for row in memberships]
    if len(set(membership_keys)) != expected_rows:
        raise PairedDescriptionError("membership compound keys are not unique")
    if membership_keys != [_compound_key(row) for row in mechanical]:
        raise PairedDescriptionError("mechanical rows are not in membership order")
    if membership_keys != [_compound_key(row) for row in carriers]:
        raise PairedDescriptionError("carrier rows are not in membership order")

    _support_release(support_rows, "C_abs_primary")
    _support_release(support_rows, "C_aae_primary")

    all_points: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    release_rows: list[dict[str, Any]] = []
    json_endpoints: dict[str, Any] = {}
    for endpoint in contract["endpoints"]:
        points = _endpoint_values(endpoint, memberships, carriers, mechanical)
        expected = int(
            contract["expected"][
                "C_aae_primary_rows"
                if endpoint["cohort"] == "C_aae_primary"
                else "C_abs_primary_rows"
            ]
        )
        if len(points) != expected:
            raise PairedDescriptionError(
                f"{endpoint['id']} rows differ: expected {expected}, got {len(points)}"
            )
        cluster_ids = [str(row["cluster_id"]) for row in points]
        model_states = {str(row["model_state_id"]) for row in points}
        if len(set(cluster_ids)) != int(contract["expected"]["primary_clusters"]):
            raise PairedDescriptionError(f"{endpoint['id']} cluster count changed")
        if len(model_states) != int(contract["expected"]["primary_model_states"]):
            raise PairedDescriptionError(f"{endpoint['id']} model-state count changed")
        if len(points) < int(contract["support"]["point_summary"]["minimum_rows"]):
            raise PairedDescriptionError("point-summary row support failed")
        if len(model_states) < int(
            contract["support"]["point_summary"]["minimum_model_states"]
        ):
            raise PairedDescriptionError("point-summary model-state support failed")
        if len(points) < int(contract["support"]["mean_error"]["minimum_rows"]):
            raise PairedDescriptionError("mean-error row support failed")
        if len(model_states) < int(
            contract["support"]["mean_error"]["minimum_model_states"]
        ):
            raise PairedDescriptionError("mean-error model-state support failed")

        cluster_weights = cluster_balanced_weights(cluster_ids)
        equal_row_weights = row_weights(len(points))
        for point, cluster_weight, equal_row_weight in zip(
            points, cluster_weights, equal_row_weights
        ):
            point["cluster_balanced_weight"] = float(cluster_weight)
            point["row_weight"] = float(equal_row_weight)
        all_points.extend(points)

        observation = np.asarray(
            [row["observation"] for row in points], dtype=np.float64
        )
        model = np.asarray([row["model"] for row in points], dtype=np.float64)
        ordinals = np.asarray(
            [row["carrier_ordinal"] for row in points], dtype=np.int64
        )
        counts = {
            "rows": len(points),
            "finite_negative_observations": int(np.sum(observation < 0.0)),
            "observation_source_records": len(
                {row["direct_aop_source_record_id"] for row in points}
            ),
            "model_states": len(model_states),
            "transects": len({row["transect_id"] for row in points}),
            "plumes": len({row["plume_id"] for row in points}),
            "fires": len({row["fire_id"] for row in points}),
            "clusters": len(set(cluster_ids)),
        }
        endpoint_json: dict[str, Any] = {"counts": counts, "weightings": {}}
        for weighting, weights in (
            ("cluster_balanced_primary", cluster_weights),
            ("row_weighted_secondary", equal_row_weights),
        ):
            metrics = summarize_values(observation, model, weights, ordinals)
            row = {
                "endpoint": endpoint["id"],
                "unit": endpoint["unit"],
                "cohort": endpoint["cohort"],
                "weighting": weighting,
                **counts,
                **metrics,
                "point_summary_status": "eligible_calculated",
                "mean_error_status": "eligible_calculated",
            }
            summaries.append(row)
            endpoint_json["weightings"][weighting] = metrics
        json_endpoints[endpoint["id"]] = endpoint_json

        metric_states = (
            ("counts_raw_points", "eligible", "calculated"),
            ("median_IQR_residual_point_summary", "eligible", "calculated"),
            ("mean_bias_MAE_RMSE", "eligible", "calculated"),
            ("Pearson_Spearman", BLOCKED_STATUS, "not_calculated"),
            ("whole_cluster_interval_95", BLOCKED_STATUS, "not_calculated"),
            (
                "age_pattern",
                contract["support"]["age_pattern"],
                "not_calculated",
            ),
            ("bootstrap", "closed", "not_executed"),
        )
        for metric_class, status, action in metric_states:
            release_rows.append(
                {
                    "endpoint": endpoint["id"],
                    "cohort": endpoint["cohort"],
                    "metric_class": metric_class,
                    "status": status,
                    "action": action,
                }
            )

    summary = {
        "schema_version": "firex-tier-f-paired-description-v1",
        "result": "completed",
        "terminal_label": "accepted-descriptive-August6-paired-description",
        "scope": "supported primary paired descriptions only",
        "endpoints": json_endpoints,
        "blocked": {
            "Pearson_Spearman": BLOCKED_STATUS,
            "whole_cluster_interval_95": BLOCKED_STATUS,
            "age_pattern": contract["support"]["age_pattern"],
            "age_uncertainty_pattern": contract["support"][
                "age_uncertainty_pattern"
            ],
        },
        "prohibitions_verified": {
            "association_computed": False,
            "bootstrap_executed": False,
            "sampling_or_measurement_interval_computed": False,
            "age_summary_computed": False,
            "sensitivity_computed": False,
            "scientific_interpretation": False,
            "rematching": False,
            "model_execution": False,
            "day_eight": False,
        },
    }
    return all_points, summaries, release_rows, summary, paths


def write_run(
    contract_path: Path,
    output_root: Path,
    command: str,
) -> None:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    design_path = Path(contract["design"]["path"])
    if not design_path.is_absolute():
        design_path = Path.cwd() / design_path
    verify_hash(design_path, contract["design"]["sha256"], "design")
    output_root.mkdir(parents=True, exist_ok=False)
    points, summaries, releases, summary, paths = build_outputs(contract)
    _write_csv(output_root / "paired_points.csv", points)
    _write_csv(output_root / "paired_summary.csv", summaries)
    _write_csv(output_root / "metric_release_status.csv", releases)
    _write_json(output_root / "paired_description_summary.json", summary)

    run_manifest = {
        "schema_version": 1,
        "command": command,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "numpy_version": np.__version__,
        },
        "random_seed": {
            "applicable": False,
            "reason": "paired-description gate contains no bootstrap or RNG",
        },
        "source": {
            "implementation": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "contract": {
                "path": str(contract_path.resolve()),
                "sha256": sha256_file(contract_path),
            },
            "design": {
                "path": str(design_path.resolve()),
                "sha256": sha256_file(design_path),
            },
        },
        "inputs": {
            label: {"path": str(path), "sha256": sha256_file(path)}
            for label, path in paths.items()
        },
        "outputs": list(SCIENCE_OUTPUTS),
        "blocked_metrics_calculated": False,
        "bootstrap_executed": False,
        "model_execution": False,
    }
    _write_json(output_root / "run_manifest.json", run_manifest)
    artifacts = {
        name: sha256_file(output_root / name)
        for name in (*SCIENCE_OUTPUTS, "run_manifest.json")
    }
    _write_json(
        output_root / "ARTIFACT_MANIFEST.json",
        {
            "schema_version": 1,
            "artifacts": artifacts,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    command = (
        f"{Path(__file__).as_posix()} --contract {args.contract.as_posix()} "
        f"--output-root {args.output_root.as_posix()}"
    )
    write_run(args.contract, args.output_root, command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
