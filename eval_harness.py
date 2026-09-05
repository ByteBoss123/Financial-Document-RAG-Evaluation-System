"""Evaluate FinDocQA failure detectors on the versioned labeled benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from app.bedrock_judge import BedrockUnsupportedClaimJudge
from app.failure_detection import evaluate_response
from app.types import Chunk


CATEGORIES = {
    "numeric_hallucination",
    "period_mismatch",
    "retrieval_miss",
    "unsupported_claim",
    "citation_gap",
}


def _metrics(expected_sets: list[set[str]], predicted_sets: list[set[str]]) -> dict:
    per_category = {}
    micro_tp = micro_fp = micro_fn = 0
    for category in sorted(CATEGORIES):
        tp = sum(category in e and category in p for e, p in zip(expected_sets, predicted_sets))
        fp = sum(category not in e and category in p for e, p in zip(expected_sets, predicted_sets))
        fn = sum(category in e and category not in p for e, p in zip(expected_sets, predicted_sets))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_category[category] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(category in e for e in expected_sets),
        }
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn
    micro_precision = micro_tp / (micro_tp + micro_fp) if micro_tp + micro_fp else 0.0
    micro_recall = micro_tp / (micro_tp + micro_fn) if micro_tp + micro_fn else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall else 0.0
    )
    return {
        "micro_precision": round(micro_precision, 4),
        "micro_recall": round(micro_recall, 4),
        "micro_f1": round(micro_f1, 4),
        "per_category": per_category,
    }


def run_eval(dataset: Path, judge=None) -> dict:
    records = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line]
    expected_sets: list[set[str]] = []
    predicted_sets: list[set[str]] = []
    failures = []
    latencies = []
    for record in records:
        chunk = Chunk(
            chunk_id=0,
            company=record["company"],
            form_type=record["form_type"],
            filed_date=record["filed_date"],
            section_name="benchmark",
            source_url="https://www.sec.gov/",
            text=record["context"],
            fiscal_period_end=record["fiscal_period_end"],
        )
        started = time.perf_counter()
        result = evaluate_response(
            record["question"],
            record["answer"],
            [(chunk, record["top_score"])],
            unsupported_claim_judge=judge,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        expected = set(record["expected_categories"])
        if judge is None:
            expected.discard("unsupported_claim")
        predicted = set(result.categories)
        expected_sets.append(expected)
        predicted_sets.append(predicted)
        if expected != predicted:
            failures.append({
                "id": record["id"],
                "expected": sorted(expected),
                "predicted": sorted(predicted),
            })

    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered)) - 1))
    return {
        "dataset": str(dataset),
        "dataset_type": "curated synthetic SEC-style benchmark",
        "judge_enabled": judge is not None,
        "records_evaluated": len(records),
        "exact_match_accuracy": round(1 - len(failures) / len(records), 4),
        **_metrics(expected_sets, predicted_sets),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(ordered[p95_index], 2),
        },
        "mismatches": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/eval_benchmark.jsonl"))
    parser.add_argument("--bedrock-model-id")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", type=Path, default=Path("results/eval_report.json"))
    args = parser.parse_args()
    judge = None
    if args.bedrock_model_id:
        judge = BedrockUnsupportedClaimJudge(args.bedrock_model_id, args.region)
    try:
        report = run_eval(args.dataset, judge)
    except Exception as exc:
        print(f"AWS error: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
