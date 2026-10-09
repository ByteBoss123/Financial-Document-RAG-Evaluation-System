# Design reviews

Decisions made while testing FinDocQA on real filings and redeploying it, with the options considered and the
evidence. Numbers come from `results/`.

---

## DR-1 Numeric-hallucination check: compare values at displayed precision, not strings

**Problem.** On 23 FinanceBench extraction answers (real 10-K/10-Q text), the string-matching detector flagged
14 correct answers: "$1577.00" vs "1,577", "$1616.00" vs "1,615.9", "$5466" (millions) vs "5,466,312" (thousands).

**Options.** (a) keep string match; (b) relative tolerance (e.g. within 1%); (c) exact value match at the answer's
displayed precision, allowing thousand/million/billion unit changes.

**Decision.** (c). A tolerance (b) would also accept wrong figures within the band; (c) only accepts a figure that
some filing figure rounds to.

**Evidence.** FinanceBench: false alarms 14 of 23 -> 0 of 23, wrong figures caught 21 of 23 before and after
(`real_filings_numeric_*.json`). Held-out TAT-QA, 1,052 answers restated the way LLMs write them: false alarms
96% -> 3%; cost: recall on +10% wrong figures 100% -> 98.4%, and 96.7% -> 95.3% on answers in original form
(`heldout_tatqa_*.json`). The fix was built on the 23 FinanceBench cases; TAT-QA is the out-of-sample check.

---

## DR-2 Build and deploy without local Docker

**Problem.** The image had to be rebuilt to ship fixes, with no Docker on the developer machine.

**Options.** (a) `sam build` locally; (b) AWS CodeBuild building the image in the cloud from source in S3,
pushing to the existing ECR repo, then `UpdateFunctionCode`.

**Decision.** (b), project `findocqa-build`, least-privilege role (push to one ECR repo, read one bucket).

**What the builds found.** The Python 3.11 Lambda base (Amazon Linux 2) has a glibc too old for current
manylinux wheels, so pip tried to compile scikit-learn and Pillow with no compiler. Moved to the Python 3.12 base
(Amazon Linux 2023) with pinned versions and `--prefer-binary`. Also baked the embedding model into the image:
first-call latency after idle 85 s -> 44 s.

**Rollback.** The previous image stays in ECR; one `UpdateFunctionCode` call restores it.

---

## DR-3 A failing LLM judge must not fail the request

**Problem.** Live, Nova Lite sometimes returned "Model produced invalid sequence as part of ToolUse"; the
exception propagated and `/ask` returned HTTP 500.

**Options.** (a) fail the request; (b) retry once, then skip only the unsupported-claim check and log it.

**Decision.** (b). The four deterministic checks still run; the skipped judge is visible in the logs.
Locked in by `test_judge_error_does_not_break_evaluation`.

---

## DR-4 Ingestion fails loudly; filers without standard headings are still indexed

**Problem.** Morgan Stanley's 10-K has no standard "Item 1A / Item 7" headings, so the section parser returned
nothing, the error was swallowed, and the company silently disappeared from the index. All 4 Morgan Stanley
questions were answered from other companies' filings, and 3 passed every detector.

**Decision.** Fall back to full-document text when no section matches; exit non-zero if any filer still yields no
records; add an entity-mismatch detector (question names company X, source is company Y).

**Evidence.** After redeploy, right-company answers 16 of 20 -> 20 of 20 (`live_lambda_v2.json`); the entity
check flagged all 4 misattributed answers in the replayed logs and none of the 16 correct ones.

---

## DR-5 Do not treat citation dates or form names as figures

**Problem.** Answers cite "10-K filed 2026-02-13", as the prompt requires. "10" (from 10-K) and "02"/"13"
(from the date) were flagged as hallucinated numbers: 8 of 20 live extractive answers, then 7 of 10 live Llama
answers.

**Decision.** Strip SEC form names and calendar dates before extracting figures.

**Evidence.** Live false alarms -> 0 of 20; FinanceBench and TAT-QA results unchanged by this change.

---

## DR-6 Redeploys are one command with smoke tests and automatic rollback

**Problem.** The first redeploys were a sequence of manual API calls; a bad image would have stayed live until
someone noticed.

**Decision.** `infra/redeploy.py`: CodeBuild build -> UpdateFunctionCode -> smoke test (one question per filer:
HTTP 200, non-error answer, top source is the company named) -> roll back to the previous image digest on any failure.
`--rollback-drill` exercises the rollback path on purpose.

**Evidence** (`results/redeploy_drill.json`): build 202 s; deploy and smoke 5 of 5; rollback drill 29 s to deploy,
5 of 5; roll forward 29 s, 5 of 5.
