# FinDocQA — LLM Failure-Mode Detection for Financial Document QA

A retrieval-augmented QA service over real SEC filings, built specifically
around the question: **when this system is wrong, how would you actually
know?** Most RAG demos stop at "it retrieves and answers." This one adds the
layer that's usually missing in production: a defined taxonomy of how
financial-document LLM applications fail, automatic detectors for each
failure mode, structured request logging, and a monitoring dashboard that
surfaces failure rate over time instead of hiding it inside a single
"looks fine" demo run.

## Why this problem

RAG over financial filings (10-Ks, 10-Qs, earnings materials) is genuinely
unreliable in ways that are easy to miss in a casual demo: a model can
fabricate a number that sounds plausible, cite the wrong fiscal year, or
answer confidently from a failed retrieval instead of declining. In a
financial-services context, that's not a cosmetic bug — it's the kind of
error that costs trust or money. BGC Group's own 2024 10-K explicitly names
this as a business risk: *"We may use artificial intelligence in our
business, and challenges with properly managing its use could result in
competitive harm, regulatory action, legal liability and brand or
reputational harm."* This project is a concrete, working answer to that
risk category — not a contrived exercise.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  edgar_ingest.py │────▶│ rag_index.py │────▶│    main.py       │
│  (SEC EDGAR API) │     │ (FAISS +     │     │   (FastAPI       │
│  real 10-K/10-Q  │     │  embeddings) │     │   /ask endpoint) │
└─────────────────┘     └──────────────┘     └────────┬────────┘
                                                         │
                              ┌──────────────────────────┼─────────────┐
                              ▼                          ▼              ▼
                    ┌──────────────────┐      ┌──────────────────┐   logs/
                    │failure_detection.│      │ observability.py │  requests.jsonl
                    │py (taxonomy +    │◀────▶│ (structured      │
                    │ detectors)       │      │  JSON-lines log) │
                    └──────────────────┘      └────────┬─────────┘
                                                         ▼
                                              ┌──────────────────┐
                                              │  dashboard.py     │
                                              │  (Streamlit:      │
                                              │  failure rate,    │
                                              │  latency, flagged │
                                              │  request browser) │
                                              └──────────────────┘
```

## The failure-mode taxonomy

This is the core contribution. Five specific, automatically-detected failure
modes, chosen because they're the ones that matter most in a financial
context (as opposed to generic "is this a good answer" scoring):

| Category | What it catches | Severity |
|---|---|---|
| `numeric_hallucination` | Answer states a number not present anywhere in retrieved context | High |
| `period_mismatch` | Answer/question fiscal year doesn't match the retrieved filing's actual fiscal period | High |
| `retrieval_miss` | Retrieval confidence is below threshold but the model answered confidently instead of declining | High |
| `unsupported_claim` | Bedrock judge finds a qualitative claim not supported by retrieved text | Medium |
| `citation_gap` | Answer doesn't name its source company/filing, making it hard to verify | Low |

Every flag carries the specific evidence that triggered it (e.g. the exact
numbers that didn't match), not just a pass/fail label, so the dashboard can
show *why* a response was flagged.

## A real bug this taxonomy caught in itself

Worth calling out explicitly, because it's a good illustration of why this
kind of detector needs testing, not just intuition: the first version of
`period_mismatch` compared the requested fiscal year against the filing's
**filed date**. That's wrong by design, not by accident — a 10-K is
typically filed two to three months *after* its fiscal year closes (BGC's
FY2024 10-K was filed March 3, 2025). Comparing against filed date would
have flagged every single normal annual-report query as a false mismatch.
The fix was to thread the filing's actual **fiscal period end** (SEC's
`reportDate` field) through the pipeline as its own field, separate from
`filed_date`, and anchor the check on that instead. Caught by a unit test
(`test_evaluate_response_clean_answer_passes`), not by inspection — see
`tests/test_failure_detection.py` for the regression test that locks this in.

## Setup

```bash
pip install -r requirements.txt

# SEC requires a descriptive User-Agent on every request (their fair-use policy)
export EDGAR_USER_AGENT="Your Name your@email.com FinDocQA project"

# Optional: for real LLM-generated answers instead of the extractive fallback
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Running it

```bash
# 1. Pull real filings from SEC EDGAR (default: BGC, JPM, GS, MS, ICE)
python -m app.edgar_ingest BGC JPM

# 2. Build the embedding index
python -m app.rag_index

# 3. Start the API
uvicorn app.main:app --reload --port 8000

# 4. Ask a question
curl -X POST localhost:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "What does BGC say about AI-related risks?"}'

# 5. Watch it in the dashboard
streamlit run dashboard/dashboard.py
```

## Testing

```bash
python -m pytest tests/ -v
```

The deterministic detector and integration suite contains 14 tests. To run
the versioned 60-record synthetic SEC-style benchmark with all five detectors,
including the Amazon Nova Lite judge:

```bash
python build_eval_dataset.py
python eval_harness.py --bedrock-model-id us.amazon.nova-lite-v1:0 --region us-east-1
```

The report is written to `results/eval_report.json` and includes exact-match
accuracy, per-category precision/recall/F1, micro precision/recall/F1, p50/p95
evaluation latency, and every mismatch. Omitting `--bedrock-model-id` produces
a deterministic four-detector baseline and explicitly excludes examples whose
labels require the LLM judge.

Tests run against synthetic `Chunk` objects and don't require network access
or the embedding model — they validate the detection *logic*, independent of
retrieval quality. (`app/types.py` exists specifically so `failure_detection.py`
can be imported and tested without pulling in `faiss`/`sentence-transformers`.)

## Limitations and what a production version would add

- **`unsupported_claim` uses an LLM judge.** It requires Bedrock model access
  and therefore adds latency and model-invocation cost. The deterministic four-
  detector path remains available when the judge is disabled.
- **Logging is JSON-lines, not Prometheus/Datadog.** Local runs write to
  `logs/`; Lambda writes to its permitted `/tmp/findocqa/logs` filesystem.
  Chosen so the project
  runs with zero infra setup. The `RequestLog` schema in `observability.py`
  is flat and typed specifically so it could be piped into a real metrics
  backend with a thin adapter, not a rewrite.
- **Retrieval is a single dense FAISS index**, no re-ranking or hybrid
  sparse+dense search. Fine for a demo-scale corpus of a handful of filings;
  would need work for a larger document set.
- **CIK lookup is a hardcoded dict** for five companies. SEC's own
  `company_tickers.json` endpoint could replace this with full ticker
  coverage in about ten lines of code.
