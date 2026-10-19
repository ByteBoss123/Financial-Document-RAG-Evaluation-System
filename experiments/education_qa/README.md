# Course Evidence QA: when relevant text is not an answer

## Problem
Students need reliable answers grounded in course materials. A passage can share
keywords with a question without containing its answer. Returning that passage
confidently can mislead a learner even when the citation itself is real.

This runnable, offline educational-technology experiment measures that failure.
It is a small **extractive retrieval baseline**, not an LLM tutor, deployed product,
university research appointment or demonstration of improved student learning.
It extends this repository's reliability theme into an educational setting, with
an independent implementation; it does not call the finance-specific detectors.

## Run in two minutes
Python 3.10+; no API keys, packages, cloud services or downloads required.
From the repository root, on Windows, macOS or Linux:

```bash
python experiments/education_qa/assistant.py "What is precision?"
python experiments/education_qa/assistant.py "What grade will my baseline model earn?"
python experiments/education_qa/evaluate.py
python -m unittest discover -s experiments/education_qa -p "test_*.py" -v
```

The assistant uses the selected threshold from `results.json` when present.
`--threshold 0.5` allows manual exploration; scores at a manually chosen threshold
must not be reported as independently validated results.

## What is implemented
* Word TF-IDF cosine retrieval over 12 short, authored machine-learning notes.
* Exact source-passage responses with source ID and title.
* Abstention for zero similarity or scores below a selected threshold.
* 12 development questions and 24 separate test questions with source-ID labels.
* Development-only threshold selection across 21 thresholds, with a fixed tie rule.
* A low-threshold retrieval baseline, selective policy, row-level outputs and input hashes.
* Five behavioral tests covering citations, abstention, invalid inputs and metric correctness.

This baseline extracts complete notes. It does not generate explanations or check
semantic entailment. An authentic citation does not imply that the passage answers
the question. The retrieval score is not a calibrated probability of correctness.

## Measured demonstration results
Run on 19 October 2026; see `results.json` for all predictions and hashes.

| Measure on 24 test questions | Low-threshold baseline | Dev-selected threshold 0.20 |
|---|---:|---:|
| Correct decision (right source or correct abstention) | 17/24 | 17/24 |
| Questions answered | 19/24 | 19/24 |
| Correct source among answered questions | 12/19 | 12/19 |
| Answerable questions receiving the right source | 12/12 | 12/12 |
| Unanswerable questions incorrectly answered | 7/12 | 7/12 |

The baseline has threshold zero but still abstains on zero-similarity queries;
“always_retrieve” in the JSON means retrieve whenever there is a positive match.
Neither policy answers the five entirely unmatched questions.
The development-selected threshold produced **no test improvement**. No result
was changed by tuning against these test failures.

### A concrete failure
“What grade will my baseline model earn?” matches the baseline-model note.
The note explains how to compare models but provides no grade information.
The assistant returns it anyway. This demonstrates why lexical relevance alone
is insufficient for deciding whether an educational question is answerable.

## Data card and limits
All notes, questions and expected source labels were authored with AI assistance
for this demonstration. They are not copied GMU course materials, real student
records, instructor-reviewed labels or a representative educational benchmark.
Development and test were authored together, so their separation is procedural,
not evidence of an independently collected held-out evaluation. Notes overlap in
vocabulary with the questions. The 24-case test is small and balanced by design.

“Correct source” is an ID comparison, not human grading of answer quality.
The benchmark contains no multi-source synthesis, personalized feedback,
multilingual queries or learning-outcome measurements. No accuracy claims should
be generalized to real students or a deployed LLM. There is no online model,
student profiling or collection of user questions.

## A credible next research step
1. Obtain instructor-approved materials and independently authored questions.
2. Include answerable paraphrases, near-topic unanswerable questions and ambiguous cases.
3. Have two reviewers label evidence sufficiency and adjudicate disagreements.
4. Compare this lexical baseline against dense retrieval and an answerability verifier.
5. Lock thresholds on development data; evaluate once on a fresh test set.
6. Measure answer correctness, unsupported answers and coverage separately.
7. Investigate learning outcomes only in a properly designed, approved study.

## Explain it in an interview
“I built an educational QA evaluation prototype to investigate whether retrieval
confidence is enough to decide when to answer. On a small authored benchmark,
it retrieved the right source for all 12 answerable questions but also answered
7 of 12 unsupported questions. The threshold selected on development data did
not fix this. My next step would be an instructor-reviewed benchmark and a
separate check that the evidence actually answers the question.”

Use this wording only after you have run the code and can explain it. The initial
code and fixtures were created with AI assistance; review and reproduce the work
before presenting it as something you understand and can maintain.

## Files
* `assistant.py`: tokenization, TF-IDF, retrieval, abstention and CLI.
* `course_notes.json`: authored corpus with stable source IDs.
* `benchmark.json`: provenance, development and test questions.
* `evaluate.py`: development selection and frozen test reporting.
* `results.json`: measured results, configuration and hashes.
* `test_assistant.py`: deterministic behavioral tests.
