# Snowflake + Streamlit deployment

Target: actual AWS Cost Explorer data -> Snowflake COST_DAILY -> daily/monthly
SQL reporting models -> Streamlit and Python forecast evaluation.

**Status:** implementation prepared and locally tested; no Snowflake connection
was available in this workspace. Do not claim an executed Snowflake pipeline or
hosted Streamlit deployment until the live checks below pass.

## Load the real-data snapshot

Use your own existing Snowflake database and a **dedicated schema**. The loader
replaces the complete COST_DAILY snapshot in this schema on each successful run.
It does not create a database, warehouse or broad role grants. The schema must
not contain unrelated data under the same table names. One writer per schema.

Configure a named connection using Snowflake's local connections.toml or your
approved secret manager. Never commit passwords, private keys, tokens or billing
exports. Then run:

```bash
python -m pip install -r requirements-snowflake.txt
python -m cloud_finance.snowflake_backend --connection YOUR_CONNECTION \
  --database YOUR_DATABASE --schema CLOUD_FINANCE_BI \
  --aws-json private/cost-explorer.json
```

The loader validates source grain/currency/completeness, preserves decimal
precision, checks staging row count and source total, and only then replaces
the published data and records an audit row in a DML transaction. Failed staging
does not touch the published snapshot; failed publication rolls back. DDL occurs
before BEGIN because Snowflake DDL implicitly commits. An unchanged reload is
data-idempotent but adds another audit entry. Concurrent writers are not supported.

## Streamlit

Create a Streamlit app in Snowsight using an existing warehouse. Upload
`snowflake_app.py` and the `cloud_finance` package; select that entrypoint and make
NumPy, pandas and snowflake-snowpark-python available. Enter your database/schema
in the sidebar. The app uses `st.connection("snowflake")`; locally, configure the
corresponding Streamlit connection and run `streamlit run snowflake_app.py`.

Use a least-privilege app owner role with SELECT/USAGE on only the reporting
schema and warehouse. In owner-rights deployments, only share with viewers
authorized for the full underlying billing data. This app does not implement
per-user row security. Keep warehouses small with auto-suspend configured by
your account administrator. Compute consumption is billed by Snowflake.

No demo fallback exists in this entrypoint: an unavailable connection or table
shows an error. No assumed budget is supplied for real records. AWS credits and
estimated charges remain visible. Forecasts run in Python using Snowflake-loaded
history; daily/monthly reporting aggregations run in Snowflake SQL.

## Live acceptance checks (pending connection)

1. Run the loader and confirm its source reconciliation result.
2. Independently compare `SUM(UNBLENDED_COST)` and row counts against the AWS export.
3. Rerun the same snapshot: row count and totals must remain unchanged.
4. Upload a duplicate-grain snapshot: it must fail before modifying COST_DAILY.
5. Open the Streamlit app, inspect charts, choose dates, and generate the QBR.
6. Verify a read-only viewer cannot modify tables and cannot see unauthorized data.

Local mocked connector tests verify client control flow, not Snowflake SQL
execution, permissions, connector compatibility or a deployed app.

References: https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api
and https://docs.streamlit.io/develop/api-reference/connections/st.connections.snowflakeconnection
