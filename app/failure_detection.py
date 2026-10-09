"""
failure_detection.py

This is the centerpiece of FinDocQA: a taxonomy of LLM failure modes specific
to financial-document QA, plus automatic detectors for each one. The goal is
NOT generic "is this answer good" scoring -- it's catching the specific ways
these systems silently go wrong in a financial-services context, where a
wrong number or a misattributed fiscal period is a much more expensive
mistake than a vague answer.

Failure modes detected:

1. NUMERIC_HALLUCINATION
   The answer states a number (dollar amount, percentage, share count, date)
   that does not appear anywhere in the retrieved context. This is the most
   dangerous failure mode in finance -- a fabricated number reads exactly as
   confidently as a real one.

2. PERIOD_MISMATCH
   The answer cites a fiscal year/quarter that doesn't match the fiscal
   period of the retrieved chunks. E.g. user asks about FY2024 results, the
   retrieved context is from the FY2023 filing, and the model answers anyway
   without flagging the mismatch.

3. RETRIEVAL_MISS
   The similarity scores of the retrieved chunks are below a confidence
   threshold (meaning nothing actually relevant was found), but the model
   produced a confident-sounding answer anyway instead of declining.

4. UNSUPPORTED_CLAIM
   The answer makes a qualitative claim (e.g. about risk, performance,
   strategy) that is not traceable to any phrase in the retrieved context --
   different from numeric hallucination because it's prose, not a number.

5. CITATION_GAP
   The answer doesn't include any of the source attribution it was asked to
   include (company name, filing date, section), making it hard for a human
   reviewer to verify even if the content were correct.

Each detector returns a FailureFlag with a category, severity, and the
specific evidence that triggered it, so the dashboard can show *why* a
response was flagged, not just that it was.
"""

import logging
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum

logger = logging.getLogger("findocqa.failures")


class FailureCategory(str, Enum):
    NUMERIC_HALLUCINATION = "numeric_hallucination"
    PERIOD_MISMATCH = "period_mismatch"
    RETRIEVAL_MISS = "retrieval_miss"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CITATION_GAP = "citation_gap"
    ENTITY_MISMATCH = "entity_mismatch"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class FailureFlag:
    category: FailureCategory
    severity: Severity
    detail: str
    evidence: str = ""


@dataclass
class EvalResult:
    flags: list[FailureFlag] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.severity == Severity.HIGH for f in self.flags)

    @property
    def categories(self) -> list[str]:
        return [f.category.value for f in self.flags]


# --- Helpers -----------------------------------------------------------

NUMBER_PATTERN = re.compile(
    r"\$?\d[\d,]*\.?\d*\s?(?:million|billion|thousand|%|percent)?"
)

FISCAL_YEAR_PATTERN = re.compile(
    r"\b(?:fy\s?-?\s?20\d{2}|fiscal\s+year\s+20\d{2}|fiscal\s+20\d{2}|f20\d{2})\b",
    re.IGNORECASE,
)

# Rough threshold for cosine similarity (normalized embeddings, inner product
# score from FAISS) below which we consider retrieval to have "missed."
RETRIEVAL_CONFIDENCE_THRESHOLD = 0.35

# Phrases that signal the model is hedging/declining -- if these are present
# we should NOT penalize for retrieval miss, since hedging is the correct
# behavior, not a failure.
HEDGE_PHRASES = [
    "i don't have", "not available in", "cannot find", "no information",
    "not mentioned", "unable to locate", "context does not",
]


DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b")
SEC_FORM_PATTERN = re.compile(r"\b(?:10-K|10-Q|8-K|20-F|40-F|6-K|S-1)(?:/A)?\b", re.IGNORECASE)

# Names a user may use for each indexed filer (the five CIKs in edgar_ingest.KNOWN_CIKS).
COMPANY_ALIASES = {
    "bgc": ["bgc"],
    "jpmorgan": ["jpmorgan", "jp morgan", "jpmorganchase", "chase", "jpm"],
    "goldman": ["goldman sachs", "goldman"],
    "morgan stanley": ["morgan stanley"],
    "ice": ["intercontinental exchange", "ice"],
}


def _companies_named(text: str) -> set[str]:
    low = text.lower()
    low = low.replace("morgan stanley", " \x00ms\x00 ")  # keep "morgan" in Morgan Stanley from matching JPMorgan aliases
    found = {"morgan stanley"} if "\x00ms\x00" in low else set()
    for key, aliases in COMPANY_ALIASES.items():
        if key == "morgan stanley":
            continue
        if any(re.search(rf"\b{re.escape(a)}\b", low) for a in aliases):
            found.add(key)
    return found


def _extract_numbers(text: str) -> set[str]:
    """
    Pull normalized numeric tokens out of text for cross-checking.
    Deliberately excludes bare 4-digit years (e.g. "2024") since those are
    fiscal-year references handled by check_period_mismatch, not financial
    figures -- without this exclusion, "fiscal year 2024" would be flagged
    as a hallucinated number any time the year isn't phrased identically in
    the source text.
    """
    # SEC form names ("10-K", "10-Q", "8-K") are document labels, not financial figures
    text = SEC_FORM_PATTERN.sub(" ", text)
    # calendar dates ("filed 2026-02-13", "12/31/2025") are citations, not financial figures
    text = DATE_PATTERN.sub(" ", text)
    raw = NUMBER_PATTERN.findall(text)
    cleaned = set()
    for r in raw:
        digits = re.sub(r"[^\d.]", "", r).strip(".")
        if not digits or digits == ".":
            continue
        # Skip bare 4-digit numbers in the 1900-2099 range with no currency/
        # percent/scale suffix attached -- these are almost always years.
        is_bare_year = (
            re.fullmatch(r"19\d{2}|20\d{2}", digits)
            and not re.search(r"[\$%]|million|billion|thousand|percent", r, re.IGNORECASE)
        )
        if is_bare_year:
            continue
        cleaned.add(digits)
    return cleaned


def _extract_fiscal_years(text: str) -> set[str]:
    years = FISCAL_YEAR_PATTERN.findall(text)
    return {re.sub(r"\D", "", y) for y in years}


_SCALES = (Decimal(1), Decimal("0.001"), Decimal("0.000001"), Decimal(1000))


def _value(token: str) -> tuple[Decimal, int] | None:
    """Numeric value plus its significant decimal places ("1616.00" -> (1616, 0), "8.70" -> (8.7, 1))."""
    try:
        v = Decimal(token)
    except InvalidOperation:
        return None
    frac = token.split(".")[1].rstrip("0") if "." in token else ""
    return v, len(frac)


def _supported(token: str, context_values: list[Decimal]) -> bool:
    """A figure is supported if some context figure equals it at the answer's displayed precision,
    either as written or after a thousands/millions unit change (filings often report in thousands
    while answers are given in millions or billions)."""
    parsed = _value(token)
    if parsed is None:
        return False
    v, places = parsed
    q = Decimal(1).scaleb(-places)
    for c in context_values:
        for s in _SCALES:
            if (c * s).quantize(q, rounding=ROUND_HALF_UP) == v.quantize(q, rounding=ROUND_HALF_UP):
                return True
    return False


def check_numeric_hallucination(answer: str, context: str) -> FailureFlag | None:
    answer_numbers = _extract_numbers(answer)
    context_values = [p[0] for p in map(_value, _extract_numbers(context)) if p]
    # compare by value, not string: "1577.00" in an answer matches "1,577" in a filing
    unsupported = {n for n in answer_numbers if not _supported(n, context_values)}
    # Filter out trivial/common numbers (page refs, single digits) that are
    # too generic to be meaningful hallucination evidence.
    unsupported = {n for n in unsupported if len(n.replace(".", "")) >= 2}
    if unsupported:
        return FailureFlag(
            category=FailureCategory.NUMERIC_HALLUCINATION,
            severity=Severity.HIGH,
            detail=(
                f"Answer contains {len(unsupported)} numeric value(s) not found "
                f"in retrieved context."
            ),
            evidence=", ".join(sorted(unsupported)[:5]),
        )
    return None


def check_period_mismatch(answer: str, context_periods: list[str], question: str) -> FailureFlag | None:
    """
    context_periods should be each retrieved chunk's FISCAL PERIOD END (e.g.
    "2024-12-31" for a calendar-year 10-K), NOT the filing's submission date.
    A 10-K is typically filed two to three months after its fiscal year
    closes, so a filing dated 2025-03-03 normally covers fiscal year 2024 --
    comparing against filed_date instead of fiscal_period_end would flag
    every single normal annual-report query as a false mismatch.
    """
    q_years = _extract_fiscal_years(question)
    a_years = _extract_fiscal_years(answer)
    context_years = set()
    for d in context_periods:
        if not d:
            continue
        context_years.update(_extract_fiscal_years(d))
        m = re.match(r"(20\d{2})-", d)
        if m:
            context_years.add(m.group(1))

    target_years = q_years or a_years
    if target_years and context_years and not (target_years & context_years):
        return FailureFlag(
            category=FailureCategory.PERIOD_MISMATCH,
            severity=Severity.HIGH,
            detail=(
                f"Question/answer references fiscal year(s) {sorted(target_years)}, "
                f"but retrieved context covers fiscal period(s) ending {sorted(context_years)}."
            ),
            evidence=f"requested={sorted(target_years)} retrieved={sorted(context_years)}",
        )
    return None


def check_retrieval_miss(answer: str, top_score: float) -> FailureFlag | None:
    is_hedged = any(p in answer.lower() for p in HEDGE_PHRASES)
    if top_score < RETRIEVAL_CONFIDENCE_THRESHOLD and not is_hedged:
        return FailureFlag(
            category=FailureCategory.RETRIEVAL_MISS,
            severity=Severity.HIGH,
            detail=(
                f"Top retrieval similarity ({top_score:.2f}) is below confidence "
                f"threshold ({RETRIEVAL_CONFIDENCE_THRESHOLD}), but the model did "
                f"not hedge or decline to answer."
            ),
            evidence=f"top_score={top_score:.3f}",
        )
    return None


def check_citation_gap(answer: str, expected_company: str) -> FailureFlag | None:
    if expected_company and expected_company.split(",")[0].split()[0].lower() not in answer.lower():
        return FailureFlag(
            category=FailureCategory.CITATION_GAP,
            severity=Severity.LOW,
            detail="Answer does not name the source company/filing, making it harder to verify.",
            evidence=expected_company,
        )
    return None


def check_entity_mismatch(question: str, retrieved_company: str) -> FailureFlag | None:
    """The question names a company, but the passage the answer is built from belongs to a different one."""
    asked = _companies_named(question)
    source = _companies_named(retrieved_company)
    if asked and source and not (asked & source):
        return FailureFlag(
            category=FailureCategory.ENTITY_MISMATCH,
            severity=Severity.HIGH,
            detail=f"Question asks about {sorted(asked)} but the answer's source filing is from {retrieved_company}.",
            evidence=f"asked={sorted(asked)} source={retrieved_company}",
        )
    return None


def check_unsupported_claim(answer: str, context: str, judge) -> FailureFlag | None:
    """Use an injected judge to detect unsupported qualitative claims.

    The judge is a remote LLM call and can fail (live Nova Lite occasionally returns a malformed
    tool-use response). One retry, then skip the check rather than failing the user's request."""
    judgment = None
    for attempt in range(2):
        try:
            judgment = judge(answer, context)
            break
        except Exception as e:  # noqa: BLE001 - any judge/provider error must not break /ask
            logger.warning(f"unsupported-claim judge failed (attempt {attempt + 1}): {e}")
    if judgment is None:
        return None
    if not judgment.supported:
        return FailureFlag(
            category=FailureCategory.UNSUPPORTED_CLAIM,
            severity=Severity.MEDIUM,
            detail=judgment.rationale,
            evidence=judgment.evidence,
        )
    return None


def evaluate_response(
    question: str,
    answer: str,
    retrieved_chunks: list,  # list of (Chunk, score) tuples from rag_index.FilingIndex.search
    unsupported_claim_judge=None,
) -> EvalResult:
    """
    Run the full failure-mode taxonomy against one Q/A turn.
    retrieved_chunks comes straight from FilingIndex.search().
    """
    result = EvalResult()
    if not retrieved_chunks:
        result.flags.append(FailureFlag(
            category=FailureCategory.RETRIEVAL_MISS,
            severity=Severity.HIGH,
            detail="No chunks retrieved at all.",
        ))
        return result

    context_text = "\n".join(c.text for c, _ in retrieved_chunks)
    context_periods = [c.fiscal_period_end for c, _ in retrieved_chunks]
    top_score = retrieved_chunks[0][1]
    company = retrieved_chunks[0][0].company

    for check_fn, args in [
        (check_numeric_hallucination, (answer, context_text)),
        (check_period_mismatch, (answer, context_periods, question)),
        (check_retrieval_miss, (answer, top_score)),
        (check_citation_gap, (answer, company)),
        (check_entity_mismatch, (question, company)),
    ]:
        flag = check_fn(*args)
        if flag:
            result.flags.append(flag)

    if unsupported_claim_judge is not None:
        flag = check_unsupported_claim(answer, context_text, unsupported_claim_judge)
        if flag:
            result.flags.append(flag)

    return result
