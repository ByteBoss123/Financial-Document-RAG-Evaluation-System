"""
test_failure_detection.py

Unit tests for the failure-mode taxonomy, using synthetic Chunk objects so
this validates the detection LOGIC without requiring network access, a
downloaded embedding model, or a live FAISS index. Run with:

    python -m pytest tests/test_failure_detection.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.types import Chunk
from app.failure_detection import (
    evaluate_response,
    check_numeric_hallucination,
    check_period_mismatch,
    check_retrieval_miss,
    FailureCategory,
    check_unsupported_claim,
)
from app.bedrock_judge import ClaimJudgment


def make_chunk(text, company="BGC Group, Inc.", form_type="10-K", filed_date="2025-03-03",
                fiscal_period_end="2024-12-31", section="risk_factors"):
    return Chunk(
        chunk_id=0, company=company, form_type=form_type, filed_date=filed_date,
        section_name=section, source_url="https://www.sec.gov/example", text=text,
        fiscal_period_end=fiscal_period_end,
    )


# --- Numeric hallucination ------------------------------------------------

def test_numeric_hallucination_detected():
    context = "The company reported total revenue of $2.5 billion for the fiscal year."
    answer = "The company reported total revenue of $4.8 billion for the fiscal year."
    flag = check_numeric_hallucination(answer, context)
    assert flag is not None
    assert flag.category == FailureCategory.NUMERIC_HALLUCINATION


def test_numeric_match_not_flagged():
    context = "The company reported total revenue of $2.5 billion for the fiscal year."
    answer = "According to the filing, revenue was $2.5 billion."
    flag = check_numeric_hallucination(answer, context)
    assert flag is None


def test_sentence_final_year_is_not_a_numeric_hallucination():
    context = "The company reported stable demand in fiscal year 2024."
    answer = "The company reported stable demand in fiscal year 2023."
    assert check_numeric_hallucination(answer, context) is None


# --- Period mismatch -------------------------------------------------------

def test_period_mismatch_detected():
    # Filing's fiscal period end is 2024-12-31 (i.e. it covers FY2024), but
    # the answer talks about FY2022 -- a real mismatch.
    answer = "In fiscal year 2022, the company saw strong growth."
    flag = check_period_mismatch(answer, context_periods=["2024-12-31"], question="")
    assert flag is not None
    assert flag.category == FailureCategory.PERIOD_MISMATCH


def test_period_match_not_flagged():
    # Filing covers FY2024 (fiscal_period_end=2024-12-31), question and
    # answer both correctly reference FY2024 -- should NOT be flagged, even
    # though the filing was *filed* in 2025 (10-Ks file ~2-3 months after
    # fiscal year close, so filed_date and fiscal_period_end legitimately
    # differ by design, not by error).
    answer = "In fiscal year 2024, the company saw strong growth."
    flag = check_period_mismatch(answer, context_periods=["2024-12-31"], question="What happened in fiscal year 2024?")
    assert flag is None


# --- Retrieval miss ---------------------------------------------------------

def test_retrieval_miss_detected_when_confident_answer_given():
    answer = "The company's main competitor is clearly XYZ Corp."
    flag = check_retrieval_miss(answer, top_score=0.12)
    assert flag is not None
    assert flag.category == FailureCategory.RETRIEVAL_MISS


def test_retrieval_miss_not_flagged_when_model_hedges():
    answer = "I don't have enough information in the provided context to answer this."
    flag = check_retrieval_miss(answer, top_score=0.12)
    assert flag is None


def test_high_confidence_not_flagged():
    answer = "Revenue grew significantly according to the filing."
    flag = check_retrieval_miss(answer, top_score=0.81)
    assert flag is None


# --- End-to-end evaluate_response -------------------------------------------

def test_evaluate_response_clean_answer_passes():
    chunk = make_chunk(
        "BGC Group reported revenue of $2.5 billion in fiscal year 2024. "
        "The company also discussed risks related to artificial intelligence "
        "use in its operations."
    )
    question = "What did BGC report for fiscal year 2024 revenue?"
    answer = "BGC Group reported revenue of $2.5 billion in fiscal year 2024, according to the filing."
    result = evaluate_response(question, answer, [(chunk, 0.78)])
    assert result.passed
    assert result.categories == [] or "citation_gap" in result.categories  # citation gap is LOW severity, doesn't block "passed"


def test_evaluate_response_hallucinated_number_fails():
    chunk = make_chunk("BGC Group reported revenue of $2.5 billion in fiscal year 2024.")
    question = "What was BGC's revenue?"
    answer = "BGC Group reported revenue of $9.9 billion."
    result = evaluate_response(question, answer, [(chunk, 0.78)])
    assert not result.passed
    assert "numeric_hallucination" in result.categories


def test_evaluate_response_no_chunks_flags_retrieval_miss():
    result = evaluate_response("anything", "some answer", [])
    assert not result.passed
    assert "retrieval_miss" in result.categories


def test_unsupported_claim_judge_flag_is_added():
    def judge(answer, context):
        return ClaimJudgment(False, "No supporting sentence", "Claim is absent from context")

    flag = check_unsupported_claim("The company will acquire a rival.", "Revenue was stable.", judge)
    assert flag is not None
    assert flag.category == FailureCategory.UNSUPPORTED_CLAIM


def test_supported_claim_judge_returns_no_flag():
    def judge(answer, context):
        return ClaimJudgment(True, "Revenue was stable", "Answer is grounded")

    flag = check_unsupported_claim("Revenue was stable.", "Revenue was stable.", judge)
    assert flag is None


if __name__ == "__main__":
    import subprocess
    subprocess.run(["python", "-m", "pytest", __file__, "-v"])
