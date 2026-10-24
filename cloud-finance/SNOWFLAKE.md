# CloudLedger on Snowflake

Real AWS Cost Explorer data → Snowflake raw landing → validated, transactional
`COST_DAILY` snapshot with load audit → atomic reporting snapshots refreshed by a
scheduled task → Streamlit in Snowflake dashboard (trend, service drivers,
anomalies, forecast evaluation, AI review, QBR download).

Verification status is recorded in
[`results/snowflake_verification.json`](results/snowflake_verification.json).
That file lists only what was executed against a live account; anything not
listed there as passed is untested. No billing records, dollar amounts or
credentials are committed.

## Objects

| Object | Purpose |
|---|---|
| `CLOUDLEDGER_ROLE` | Owns the schema, loader, refresh task and app. Granted to the operator and `SYSADMIN`. |
| `CLOUDLEDGER_VIEWER` | Read-only: USAGE on DB/schema/warehouse, SELECT on the `CURRENT_*` and `FRESHNESS_STATUS` views. |
| `CLOUDLEDGER_WH` | X-Small, 60 s auto-suspend, 5-credit monthly resource monitor (suspends at 100%). |
| `CODE_STAGE` | Code only: `cloud_finance.zip` (loader) and `app/` (Streamlit). |
| `RAW_COST_EXPLORER` | Every payload submitted to the loader, with SHA-256, time and user. |
| `COST_DAILY`, `LOAD_AUDIT` | Published snapshot (day × account × service) and one audit row per successful load. |
| `LOAD_FAILURES` | Rejected loads with the reason. The published snapshot is untouched. |
| `REPORT_SNAPSHOTS`, `REPORT_DAILY`, `REPORT_SERVICE_MONTH` | Versioned reporting snapshots. A snapshot is registered only after its rows reconcile to the source, in the same transaction. |
| `CURRENT_REPORT_DAILY`, `CURRENT_REPORT_SERVICE_MONTH` | Always the last *successful* snapshot. |
| `REFRESH_REPORTING(force_failure, triggered_by)` | Integrity checks (audit reconciliation, duplicate grain, currency), new snapshot, success/failure logged to `REFRESH_LOG`. |
| `REFRESH_REPORTING_DAILY` | Task, 07:15 America/New_York daily. |
| `FRESHNESS_STATUS` | Source end date, lag in days, FRESH (≤2 days) / STALE, last load, last refresh success/failure. |
| `AI_RECOMMENDATIONS`, `AI_REVIEW_EVENTS`, `AI_RECOMMENDATION_STATUS` | Model drafts with SQL evidence and automated checks; append-only human decisions. |

## Deploy (reproducible)

Requires the [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index)
with a named connection whose credentials live outside the repository.

```bash
cd cloud-finance
snow sql -c ADMIN_CONN -f sql/deploy/01_admin.sql        # ACCOUNTADMIN, once
snow sql -c PROJECT_CONN -f sql/deploy/02_objects.sql    # CLOUDLEDGER_ROLE

# Loader package: the procedure imports cloud_finance/ from this zip
mkdir -p build && rm -f build/cloud_finance.zip && zip build/cloud_finance.zip \
  cloud_finance/__init__.py cloud_finance/data.py cloud_finance/snowflake_backend.py cloud_finance/snowpark_adapter.py
snow stage copy build/cloud_finance.zip @CLOUDLEDGER.CLOUD_FINANCE_BI.CODE_STAGE --overwrite -c PROJECT_CONN
for f in __init__ data analytics workflow snowflake_backend; do
  snow stage copy cloud_finance/$f.py @CLOUDLEDGER.CLOUD_FINANCE_BI.CODE_STAGE/app/cloud_finance/ --overwrite -c PROJECT_CONN
done
snow stage copy snowflake_app.py @CLOUDLEDGER.CLOUD_FINANCE_BI.CODE_STAGE/app/ --overwrite -c PROJECT_CONN
snow stage copy environment.yml @CLOUDLEDGER.CLOUD_FINANCE_BI.CODE_STAGE/app/ --overwrite -c PROJECT_CONN

snow sql -c PROJECT_CONN -f sql/deploy/03_loader_procedure.sql
snow sql -c PROJECT_CONN -f sql/deploy/04_streamlit.sql
```

During the verified deployment, the files were written to the stage with
Snowpark `session.file.put_stream` from Snowsight; the CLI commands above
are the equivalent path and were not themselves executed.

## Load real billing data

```bash
python -m cloud_finance.import_aws --start 2026-07-01    # writes private/cost-explorer.json (gitignored)
python -m cloud_finance.load_via_procedure --connection PROJECT_CONN
```

The procedure wraps `snowflake_backend.load_snapshot` (the same loader used by
`python -m cloud_finance.snowflake_backend`) through `snowpark_adapter.py`. It
stores the raw payload, validates grain/currency/whole-day coverage, stages
with exact decimal binding, reconciles staged row count and total against the
source, then replaces `COST_DAILY` and writes `LOAD_AUDIT` in one transaction.
Any failure is written to `LOAD_FAILURES` and the published snapshot is unchanged.

**Ingestion boundary:** Snowflake does not call AWS. The scheduled task refreshes
and checks what has been loaded, and `FRESHNESS_STATUS` turns STALE when no new
export has arrived for more than two days. Automating the AWS pull needs either an
external scheduler running `import_aws` + the loader, or a Snowflake external
access integration with AWS credentials (not configured; not available to this
trial account's setup).

## AI-assisted analysis

Snowflake Cortex `COMPLETE` is not available on trial accounts (verified error
399258), so drafting uses Amazon Bedrock (`us.amazon.nova-lite-v1:0`), as the
existing planner does. Flow (`cloud_finance/ai_review.py`):

1. Run `EVIDENCE_SQL` (E1 28-day service change, E2 monthly totals, E3 top services) in Snowflake.
2. Send only that evidence to the model with `SYSTEM` (prompt `finance-recs-v1`). The Bedrock
   call runs outside Snowflake (no external access integration on this account), with AWS
   credentials from the operator's environment.
3. Parse strictly (JSON only, 1–3 items). Check every draft: cites known evidence ids,
   every number appears in the cited evidence, no savings/delete/purchase language.
4. Insert into `AI_RECOMMENDATIONS` with evidence SQL results and check results.
   Status is `PENDING_REVIEW` until a reviewer approves or rejects in the app.

The checks do not judge qualitative wording ("significant", implied causes);
that is the reviewer's job. No savings are estimated or claimed.

## Streamlit in Snowflake runtime

Since the 2026_06 behavior bundle, `CREATE STREAMLIT` without `RUNTIME_NAME` creates a
container-runtime app that needs `pyproject.toml` and a compute pool. `04_streamlit.sql`
selects `RUNTIME_NAME = 'SYSTEM$WAREHOUSE_RUNTIME'`, and `environment.yml` pins
`streamlit=1.39.0`: the default warehouse-runtime Streamlit lacked
`st.dataframe(hide_index=...)`, so the script stopped after the first tab. The QBR
cites the audited `SOURCE_SNAPSHOT`; re-hashing rows read back from `NUMBER(28,10)`
text gives a different digest for identical values.

## Cost and access

Compute is X-Small with 60 s auto-suspend and a 5-credit cap. The Streamlit app
runs with owner's rights; share it only with people allowed to see all loaded
billing rows (no row-level security). Viewers get no write access to tables.

## Trial-account limits found during deployment

- Cortex AI functions are blocked (`399258`).
- The trial account was one day from expiry at deployment; everything stops when
  it expires unless the account is upgraded. Re-run the steps above on a new account.
