# CloudLedger — Cloud Spend Intelligence & Finance BI

A working Product Finance portfolio module: Python/SQL cost reporting, Streamlit BI,
budget variance, service-level change contributions, forecast backtests, anomaly
investigation, and a bounded Amazon Bedrock planner for QBR workflows.

## Readiness controls and verified blockers

The forecast now includes non-overlapping rolling-origin diagnostics and a
planning-readiness policy. The real 115-day history yields only two complete
28-day folds after the initial 56 training days. It fails the engineering
readiness policy (minimum three folds, maximum 20% error per tested period,
and no holdout degradation versus baseline). The existing model selection is
unchanged; the UI and generated QBR label this forecast experimental rather than
retroactively choosing the model that looked best on the already observed test.
See `results/forecast_readiness.json`. This policy is not Finance-approved.

AWS Project and Workload cost-allocation tag keys were activated and their
Active status verified. Historical tag values were not available at the check;
no project/team attribution has been invented. Activation does not create resource
tags or prove resource ownership. Await billing propagation and verify actual
tagged cost coverage before replacing Unallocated in reports.

Existing financial-RAG Lambda telemetry was read for September 24–October 23:
108 invocations on two days, four Lambda errors. This is not a CloudLedger
production deployment or proof of business success. Per-day p95 durations are
recorded separately, not averaged into a false whole-period percentile.
`results/operational_readiness.json` leaves cost per successful business request
and realized savings unset because attributable cost and business-success labels
are missing. No running resource was resized or terminated.

44 automated tests pass. Hosted BI deployment,
verified ownership, Finance sign-off and measured impact remain unverified.

## Snowflake integration and real-data verification

See [SNOWFLAKE.md](SNOWFLAKE.md). On 2026-10-24 the pipeline was deployed to a
Snowflake trial account with a dedicated least-privilege role, and the real AWS
snapshot (939 service-day rows, 115 days) was loaded through the existing
`load_snapshot` loader running inside a Snowflake Python procedure. Every row
matched the source exactly (amount, currency, estimated flag), and totals matched
across source, table, load audit and reporting snapshot. The remaining live checks
(failure paths, scheduled-task run, viewer permissions, stored AI recommendations
and the Streamlit in Snowflake app) are listed as pending in
[`results/snowflake_verification.json`](results/snowflake_verification.json).

Forty-four automated tests pass. In addition, the actual AWS data was exercised through
the authenticated local Streamlit dashboard, QBR generation and persistent batch
pipeline. Totals matched a separate ungrouped AWS Cost Explorer query within one
microdollar. See [real-data verification](results/real_data_verification.json).
For the tested September 24–October 23 period, the detector produced no flags;
this does not establish recall because real anomalies have no ground-truth labels.
The UI now warns when the chosen forecast underperforms its baseline.

To load a private local export directly in the dashboard, configure
`FINANCE_DATA_PATH` with its path and enable the private access gate described
below. Server-side billing files are refused unless private mode is enabled.

## Evidence and honest scope

- The public demo generates 1,095 service-day records over 365 days with fictional
  teams and four injected Compute spikes. It is **synthetic**, not Snowflake billing.
- A separate private run imported **939 actual AWS service-day records across 115
  days (July 1–October 23, 2026)**. Source-to-report totals reconciled exactly at
  ten decimal places. No real billing records or dollar amounts are committed.
- `results/analysis.json` and `results/qbr.md` are the reproducible synthetic run.
- `results/planner_v1_live.json` and `planner_v2_live.json` contain actual Bedrock
  calls with generic prompts only. Prompt v1 over-selected tools. V2 adds examples
  and minimum-tool instructions; `python evaluate.py` measures both versions.
- The app runs locally and is covered by Streamlit interaction tests. **This module
  has not been deployed as a hosted enterprise BI application.** The parent
  repository's deployed RAG service is a separate application.
- Snowflake: objects and the real-data load were executed live (see `results/snowflake_verification.json`); the Streamlit in Snowflake app is not yet deployed.

## Run

```bash
cd cloud-finance
python -m pip install -r requirements.txt
python -m pytest -q
python -m cloud_finance.run --budget 13000
python evaluate.py
python -m streamlit run app.py
```

The budget is an explicit scenario assumption, not an approved business budget.
The QBR is a draft for review, with traceable evidence IDs for each section.

## Read-only real AWS import

Use an IAM role with `ce:GetCostAndUsage`; Cost Explorer requests can incur API
charges. The date range end is exclusive, and current-day data is excluded.

```bash
python -m cloud_finance.import_aws --start 2026-07-01 --end 2026-10-24
python -m cloud_finance.run --aws-json private/cost-explorer.json \
  --start 2026-07-01 --end 2026-10-23 --out private/results
```

The importer retrieves daily **UnblendedCost** by SERVICE, retaining credits,
refunds and other billed categories in the net total. This is not amortized cost
or invoice reconciliation. AWS can revise estimated costs. Service-only exports
cannot establish ownership: those records remain **Unallocated**. Do not invent
team mappings. The source snapshot hash supports reproducibility without publishing
the private input. Missing whole days, duplicate grain, mixed currency and
nonfinite amounts cause validation failure. Current scale is a single-account
portfolio, not a demonstrated enterprise load benchmark.

## Forecast methodology

Compare weekly seasonal-naive and least-squares trend/weekday models. The first
28 days of the final 56-day window are validation; the last 28 are holdout.
Select on validation only, then refit the chosen method on all available data for
a 28-day point forecast. The candidate uses at most 84 prior days.

Synthetic data: seasonal naive was selected. See exact metrics in results.
Private real-data evaluation: trend/weekday was selected on validation but had
**22.60% holdout WAPE**, versus **4.83% for seasonal naive**. This exposes a regime
change/selection failure; do not claim that ML improved the real forecast. These
are single-origin results, not sustained production accuracy. There are no
calibrated uncertainty intervals. Nonnegative predictions can be unsuitable for
periods dominated by credits. Do not use forecast quality as evidence of savings.

## Anomaly investigations

For each service/day, compare against the previous eight observations on the
same weekday, excluding the current and future observations. A one-sided flag
requires excess above the maximum of USD 5, 35% of the median, and six scaled MADs.
The parameters are engineering defaults, not optimized on real anomaly labels.
Absent service rows are zero within a validated daily snapshot. New services
without history and gradual increases can escape detection. Flags require review
of utilization, releases, workload demand and ownership before action.

## AI workflow and prompt evaluation

Set `BEDROCK_MODEL_ID` to a model/profile enabled for the deployment's IAM role
(tested: `us.amazon.nova-lite-v1:0`). The planner receives only the review request,
not billing records. It selects up to four named tools. A schema validator rejects
unknown tools, arbitrary SQL, duplicates, malformed JSON and excessive steps.
Python performs calculations and renders all numeric statements from structured
evidence; the model cannot write freeform financial conclusions or mutate resources.
This is bounded AI orchestration, not an autonomous resource-optimization agent.

Live tests are six **development prompts reused after prompt revision**. Do not
present improved results as a held-out benchmark. Model refusal/malformed output
fails closed; the user can explicitly choose deterministic generation. Prompt
version, snapshot fingerprint, tool list and structured evidence support auditing.

## Operations and access

The batch CLI publishes to SQLite using a transaction, records success/failure
history, and retains the last good snapshot on validation failure. `pipeline.health`
detects stale snapshots and failed latest runs. Put the database on a persistent
volume, back it up, and invoke the CLI from a scheduler in a hosted deployment.
The Streamlit upload path analyzes only the active session; it does not publish
uploads to the batch database. JSON exports are secondary; the database snapshot
is the atomic source of truth. Daily scheduling, remote backup and notification
delivery are not configured by the local app.

For a private deployment set `FINANCE_PRIVATE_MODE=1` and
`FINANCE_PASSWORD_SHA256` to the SHA-256 hash of a long random password via your
hosting secret configuration. Missing credentials deny access. This is a basic
single-user access gate, not enterprise SSO/RBAC; use an authenticated TLS proxy
or OIDC integration and rate limiting before serving organizational data.
Never place a password/hash, AWS credentials, or private exports in GitHub.
The Dockerfile uses a non-root user and health check. The image has not been
built or deployed in this environment. Dependency ranges should be locked and
scanned before a production release.

## Finance/Engineering review checklist

1. Finance confirms the cost basis, period, budget, currency and treatment of credits.
2. Engineering verifies ownership mappings and explains flagged changes.
3. Finance validates forecast assumptions and signs off on QBR conclusions.
4. Track subsequent actions and measured costs before claiming savings or time saved.

No Finance stakeholder has completed this review yet. The checklist supports a
future collaboration; it is not evidence that one happened.

## Defensible project wording

Implemented a Python/SQL cloud-finance application with Streamlit reporting,
budget variance, forecast backtesting and anomaly investigation; validated cost
reconciliation on 939 actual AWS billing records and evaluated a constrained
Bedrock workflow for evidence-backed financial reviews.

AI assistance: implementation and tests were developed with ChatGPT/Codex. Review
the code and be able to explain the calculations before using this wording in an
interview. Do not claim enterprise adoption, stakeholder sign-off, a hosted
deployment, improved real forecasting accuracy, or realized savings.
