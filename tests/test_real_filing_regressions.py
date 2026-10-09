"""Regressions found by running FinDocQA on real filings (FinanceBench evidence and live Lambda traffic)."""
from app.answer_format import clip as _clip
from app.failure_detection import (
    check_entity_mismatch,
    check_numeric_hallucination,
)


def test_figure_matches_by_value_not_string():
    # FinanceBench 3M FY2018 capex: gold "$1577.00", filing prints "1,577"
    assert check_numeric_hallucination("$1577.00", "Purchases of PP&E (1,577) (1,373)") is None


def test_figure_matches_at_displayed_precision():
    # Amcor FY2020 trade receivables: answer "$1616.00" (whole millions), filing "1,615.9"
    assert check_numeric_hallucination("$1616.00", "Trade receivables, net 1,615.9 1,864.3") is None


def test_figure_matches_across_thousands_to_millions():
    # Netflix FY2017 current liabilities: filing in thousands "5,466,312", answer in millions "$5466"
    assert check_numeric_hallucination("$5466.00", "Total current liabilities 5,466,312 4,586,657") is None


def test_wrong_figure_still_flagged():
    assert check_numeric_hallucination("$1735.00", "Purchases of PP&E (1,577) (1,373)") is not None
    assert check_numeric_hallucination("$6013.00", "Total current liabilities 5,466,312 4,586,657") is not None


def test_sec_form_name_is_not_a_figure():
    # live Lambda: every extractive answer says "Based on X's 10-K"; "10" was flagged as hallucinated
    answer = "Based on BGC Group, Inc.'s 10-K (risk_factors section): AI output may be inaccurate..."
    assert check_numeric_hallucination(answer, "AI output may be inaccurate") is None


def test_clip_never_splits_a_figure():
    text = "Additional paid-in capital 16,643 16,292 more text"
    clipped = _clip(text, limit=text.index("16,292") + 4)
    assert clipped.endswith("16,643")


def test_entity_mismatch_flags_wrong_company():
    # live Lambda: Morgan Stanley questions were answered from JPMorgan / Goldman filings
    assert check_entity_mismatch("How many employees does Morgan Stanley have?", "JPMORGAN CHASE & CO") is not None
    assert check_entity_mismatch("What cybersecurity risks does Morgan Stanley disclose?", "GOLDMAN SACHS GROUP INC") is not None


def test_entity_mismatch_passes_right_company_and_generic_questions():
    assert check_entity_mismatch("What does JPMorgan say about liquidity risk?", "JPMORGAN CHASE & CO") is None
    assert check_entity_mismatch("What are Intercontinental Exchange's segments?", "Intercontinental Exchange, Inc.") is None
    assert check_entity_mismatch("What risks did the filing identify?", "BGC Group, Inc.") is None


def test_judge_error_does_not_break_evaluation():
    # live Lambda: Nova Lite returned "Model produced invalid sequence as part of ToolUse" -> HTTP 500
    from app.failure_detection import evaluate_response
    from app.types import Chunk

    calls = []

    def flaky_judge(answer, context):
        calls.append(1)
        raise RuntimeError("ModelErrorException: Model produced invalid sequence as part of ToolUse")

    chunk = Chunk(chunk_id=0, company="MORGAN STANLEY", form_type="10-K", filed_date="2026-02-19",
                  section_name="full_text", source_url="https://www.sec.gov/", text="about 83 thousand employees",
                  fiscal_period_end="2025-12-31")
    result = evaluate_response("How many employees does Morgan Stanley have?",
                               "Morgan Stanley had about 83 thousand employees.", [(chunk, 0.64)],
                               unsupported_claim_judge=flaky_judge)
    assert len(calls) == 2 and "unsupported_claim" not in result.categories


def test_cited_filing_date_is_not_a_figure():
    # live Lambda + Llama 3.3: the prompt requires "10-K filed 2026-03-02"; "02"/"03" were flagged
    answer = "BGC Group, Inc., 10-K filed 2026-03-02, section: risk_factors. AI output may be inaccurate."
    assert check_numeric_hallucination(answer, "AI output may be inaccurate") is None
    assert check_numeric_hallucination("Filed 3/2/2026; revenue $9.1 billion", "revenue $2.1 billion") is not None
