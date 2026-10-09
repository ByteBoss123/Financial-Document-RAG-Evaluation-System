# FinDocQA — LLM Failure-Mode Detection for Financial Document QA

A retrieval-augmented QA service over real SEC filings, built specifically
around the question: **when this system is wrong, how would you actually
know?** Most RAG demos stop at "it retrieves and answers." This one adds the
layer that's usually missing in production: a defined taxonomy of how
financial-document LLM applications fail, automatic detectors for each
failure mode, structured request logging, and a monitoring dashboard that
surfaces failure rate over time instead of hiding it inside a single
"looks fine" demo run.

## Results at a glance

| Area | Result | Evidence |
|---|---|---|
| Live service | AWS Lambda + API Gateway + Bedrock (Llama 3.3 70B); right-company answers 16 -> 20 of 20 after fixing a silently dropped filer | `results/live_lambda_v2.json` |
| Detector false alarms, held out | 96% -> 3% on 1,052 TAT-QA answers, still catching 98.4% of injected wrong figures | `results/heldout_tatqa_*.json` |
| Detector false alarms, live | 7 of 10 -> 0 of 20 Llama answers | `results/live_lambda_v2.json` |
| Infrastructure automation | One-command build, deploy, smoke test, automatic rollback; rollback drill 29 s, 5/5 smoke checks | `infra/redeploy.py`, `results/redeploy_drill.json` |
| Tests | 24 pytest tests, including a regression test for every real-filing bug | `tests/` |

Design decisions and the evidence behind them: [`docs/design_reviews.md`](docs/design_reviews.md) (DR-1 to DR-6).

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

## Real-filing evaluation (what the synthetic benchmark missed)

The 60-record benchmark is templated (6 patterns x 10 companies), so 100% on it says little.
The detectors were therefore also run on real filing text and on live traffic.

**FinanceBench (real 10-K/10-Q evidence).** `python scripts/real_filings_eval.py` runs the
numeric-hallucination detector on the 23 FinanceBench "information extraction" answers that
contain a figure (gold answer + the filing passage it came from), and on the same answers with
every figure changed (x1.37+1, and a harder +10%).

| Detector version | Correct answers falsely flagged | Wrong figures caught |
|---|---|---|
| Original (string match) | 14 of 23 | 21 of 23 |
| Fixed (value match at displayed precision, thousands/millions/billions) | 0 of 23 | 21 of 23 |

The 2 misses are single-digit or zero figures, which the detector skips by design. Across all
121 answers with figures, 60 are still flagged because FinanceBench computes many answers
(ratios, margins) that do not appear verbatim in the filing; those need the LLM judge.
The fix was developed on these same 23 cases, so treat 0 of 23 as in-sample.

**Live Lambda (20 questions, `results/live_lambda_replay.json`).**
- 8 of 20 answers, all copied verbatim from filings, were flagged as numeric hallucinations.
  Cause: the answer template's "10-K" label was parsed as the figure "10". SEC form names are
  now ignored, and answers are cut on word boundaries so a figure is never split. Replay: 0 of 20.
- All 4 Morgan Stanley questions were answered from JPMorgan or Goldman Sachs filings (Morgan
  Stanley appears to be missing from the deployed index), and 3 of the 4 passed every detector.
  A new `entity_mismatch` detector flags all 4 and none of the 16 right-company answers.
- Warm requests take 13 to 17 ms server-side; a cold start took 85 s (model load).
- That deployment had no LLM key, so it served extractive answers, and its role had no Bedrock
  permission, so the judge never ran. See "Redeploy" below for the rebuilt service.

**Held-out check (TAT-QA, `python scripts/heldout_tatqa_eval.py`).** 1,052 extracted answers from real
annual reports, never looked at while building the fix:

| Answers | False alarms, old -> fixed | Wrong figures (+10%) caught, old -> fixed |
|---|---|---|
| As written in the report (1,039) | 2 -> 2 | 96.7% -> 95.3% |
| Restated: no commas, 2 decimals, next unit up (1,052) | 1,015 (96%) -> 33 (3%) | 100% -> 98.4% |

The restating rule also rewrites day numbers in dates, so that variant is a stress test.

**Bugs found after redeploying with Llama 3.3 70B on Bedrock.**
- The Nova Lite judge sometimes returns a malformed tool-use response; that exception turned the
  whole `/ask` request into an HTTP 500. The judge now retries once and is skipped on failure.
- The prompt requires the model to cite "10-K filed 2026-02-13"; the date's "02" and "13" were
  flagged as hallucinated figures (7 of the first 10 Llama answers). Calendar dates are no longer treated as figures.

**Live result after redeploy (`results/live_lambda_v2.json`, same 20 questions).** 20 of 20 HTTP 200;
20 of 20 answers sourced from the right company (was 16 of 20); 0 numeric false alarms; cold start 44 s
(was 85 s); server latency with Llama 3.3 generation and the judge p50 2.1 s, p95 4.6 s. Known limitation:
the Nova Lite judge flagged 2 answers that correctly declined ("the excerpts do not cover this").

Regression tests for each case are in `tests/test_real_filing_regressions.py` (24 tests total).

Design reviews for each decision below: `docs/design_reviews.md`.

## Redeploy without local Docker

`Dockerfile` bakes the embedding model into the image (the old image downloaded it into `/tmp` on every
cold start), ingests the latest 10-K for all five filers at build time, and fails the build if any filer
yields no sections (Morgan Stanley's 10-K has no standard "Item 1A/7" headings and was silently dropped;
it now falls back to full-document text). The image is built in AWS CodeBuild (project `findocqa-build`,
source in `s3://findocqa-build-<account>/src/`) and pushed to the existing ECR repo. Answers are generated
with Amazon Bedrock when `BEDROCK_GENERATION_MODEL_ID` is set (no API key; uses the Lambda role).

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

The deterministic detector and integration suite contains 24 tests. To run
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
