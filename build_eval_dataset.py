"""Build the versioned, synthetic SEC-style failure-detection benchmark."""

from __future__ import annotations

import json
from pathlib import Path


OUTPUT = Path("data/eval_benchmark.jsonl")


def build_records() -> list[dict]:
    records: list[dict] = []
    for i in range(10):
        company = f"Example Holdings {i}"
        common = {
            "company": company,
            "form_type": "10-K",
            "filed_date": "2025-03-01",
            "fiscal_period_end": "2024-12-31",
        }
        records.extend([
            {
                **common,
                "id": f"clean-{i:02d}",
                "question": "What revenue did the company report for fiscal year 2024?",
                "context": f"{company} reported revenue of $2.{i} billion in fiscal year 2024.",
                "answer": f"{company} reported revenue of $2.{i} billion in fiscal year 2024.",
                "top_score": 0.82,
                "expected_categories": [],
            },
            {
                **common,
                "id": f"numeric-hallucination-{i:02d}",
                "question": "What revenue did the company report for fiscal year 2024?",
                "context": f"{company} reported revenue of $2.{i} billion in fiscal year 2024.",
                "answer": f"{company} reported revenue of $9.{i} billion in fiscal year 2024.",
                "top_score": 0.82,
                "expected_categories": ["numeric_hallucination"],
            },
            {
                **common,
                "id": f"period-mismatch-{i:02d}",
                "question": "What happened in fiscal year 2023?",
                "context": f"{company} reported stable demand in fiscal year 2024.",
                "answer": f"{company} reported stable demand in fiscal year 2023.",
                "top_score": 0.77,
                "expected_categories": ["period_mismatch"],
            },
            {
                **common,
                "id": f"retrieval-miss-{i:02d}",
                "question": "What was management's capital-allocation priority?",
                "context": f"{company} disclosed the address of its principal office.",
                "answer": f"{company} clearly prioritized international acquisitions.",
                "top_score": 0.10,
                "expected_categories": ["retrieval_miss", "unsupported_claim"],
            },
            {
                **common,
                "id": f"citation-gap-{i:02d}",
                "question": "How did demand change?",
                "context": f"{company} reported that customer demand remained stable.",
                "answer": "Customer demand remained stable according to the filing.",
                "top_score": 0.79,
                "expected_categories": ["citation_gap"],
            },
            {
                **common,
                "id": f"unsupported-claim-{i:02d}",
                "question": "What strategy did management describe?",
                "context": f"{company} reported that customer demand remained stable.",
                "answer": f"{company} plans to acquire two competitors and exit its domestic market.",
                "top_score": 0.80,
                "expected_categories": ["unsupported_claim"],
            },
        ])
    return records


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    records = build_records()
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    print(f"Wrote {len(records)} labeled synthetic records to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
