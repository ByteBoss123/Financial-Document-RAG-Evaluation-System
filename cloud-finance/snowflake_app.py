"""CloudLedger dashboard. Runs as Streamlit in Snowflake (active Snowpark session)
or locally with a named Streamlit Snowflake connection."""
from datetime import timedelta
import json
import streamlit as st
from cloud_finance.snowflake_backend import identifier
from cloud_finance.analytics import analyze
from cloud_finance.workflow import execute

st.set_page_config(page_title='CloudLedger | Snowflake', layout='wide')
st.title('CloudLedger | Snowflake')
st.caption('Real AWS billing • Snowflake reporting snapshots • Python forecast evaluation')
database = st.sidebar.text_input('Database', 'CLOUDLEDGER')
schema = st.sidebar.text_input('Schema', 'CLOUD_FINANCE_BI')


def get_session():
    try:
        from snowflake.snowpark.context import get_active_session
        return get_active_session()
    except Exception:
        return st.connection('snowflake').session()


def sql(session, text, params=None):
    # No caching: the app must never show data older than the last committed load.
    return session.sql(text, params=params).to_pandas()


try:
    prefix = identifier(database) + '.' + identifier(schema)
    session = get_session()
    fresh = sql(session, f'SELECT * FROM {prefix}.FRESHNESS_STATUS')
    daily = sql(session, f'SELECT * FROM {prefix}.CURRENT_REPORT_DAILY ORDER BY USAGE_DATE')
    monthly = sql(session, f'SELECT * FROM {prefix}.CURRENT_REPORT_SERVICE_MONTH ORDER BY USAGE_MONTH, ACTUAL_COST DESC')
    costs = sql(session, f'''SELECT USAGE_DATE, ACCOUNT_KEY, SERVICE, TEAM,
        TO_VARCHAR(UNBLENDED_COST) UNBLENDED_COST, CURRENCY, ESTIMATED
        FROM {prefix}.COST_DAILY ORDER BY USAGE_DATE, ACCOUNT_KEY, SERVICE''')
except Exception as exc:
    st.error('Snowflake connection or reporting models are unavailable. Run the loader and '
             f'REFRESH_REPORTING first. ({type(exc).__name__})')
    st.stop()

# ---- Freshness and pipeline health -------------------------------------------
if daily.empty or costs.empty:
    st.warning('No successful reporting snapshot yet.')
    st.stop()
f = fresh.iloc[0]
h1, h2, h3, h4 = st.columns(4)
h1.metric('Source through', str(f.SOURCE_END))
h2.metric('Source lag (days)', int(f.SOURCE_LAG_DAYS))
h3.metric('Freshness', f.FRESHNESS)
h4.metric('Last successful refresh', str(f.LAST_SUCCESSFUL_REFRESH_AT)[:19])
if f.FRESHNESS != 'FRESH':
    st.warning('Source data is stale: the billing snapshot ends more than 2 days ago. '
               'Ingestion from AWS runs outside Snowflake; load a new export.')
failed_at, ok_at = f.LAST_FAILED_REFRESH_AT, f.LAST_SUCCESSFUL_REFRESH_AT
if str(failed_at) not in ('None', 'NaT') and (str(ok_at) in ('None', 'NaT') or failed_at > ok_at):
    st.error('The most recent refresh failed. Showing the last successful snapshot.')
st.caption(f'Reporting snapshot {f.CURRENT_SNAPSHOT_ID} created {str(f.CURRENT_SNAPSHOT_AT)[:19]}.')

rows = [dict(day=str(r.USAGE_DATE), account=r.ACCOUNT_KEY, service=r.SERVICE, team=r.TEAM,
             amount=str(r.UNBLENDED_COST), currency=r.CURRENCY, estimated=bool(r.ESTIMATED),
             source='aws-cost-explorer', injected=False) for r in costs.itertuples()]
first, last = min(daily.USAGE_DATE), max(daily.USAGE_DATE)
start = st.sidebar.date_input('Start', max(first, last - timedelta(days=29)), min_value=first, max_value=last)
end = st.sidebar.date_input('End', last, min_value=first, max_value=last)
has_budget = st.sidebar.checkbox('Supply an approved period budget', value=False)
budget = st.sidebar.number_input('Budget (USD)', min_value=0.01, value=100.0) if has_budget else None
try:
    report = analyze(rows, str(start), str(end), budget, as_of=str(last))
except ValueError as exc:
    st.error(str(exc)); st.stop()

overview, drivers_tab, anomaly_tab, forecast_tab, ai_tab, qbr_tab = st.tabs(
    ['Spending trend', 'Service drivers', 'Anomalies', 'Forecast evaluation', 'AI review', 'QBR'])

with overview:
    a, b, c = st.columns(3)
    a.metric('Actual (period)', f"${report['actual']:,.2f}")
    b.metric('Change vs prior period',
             f"${report['period_delta']:,.2f}" if report['period_delta'] is not None else 'n/a')
    c.metric('Budget variance', f"${report['budget_variance']:,.2f}" if budget else 'No budget provided')
    window = daily[(daily.USAGE_DATE >= start) & (daily.USAGE_DATE <= end)].copy()
    window['ACTUAL_COST'] = window.ACTUAL_COST.astype(float)
    st.line_chart(window.set_index('USAGE_DATE'), y='ACTUAL_COST')
    if report['estimated']:
        st.info('Some days in this period are marked estimated by AWS and can still change.')

with drivers_tab:
    st.subheader('Change vs equal-length prior period')
    st.dataframe(report['drivers'], hide_index=True)
    st.subheader('Monthly cost by service (reporting snapshot)')
    m = monthly.copy()
    m['ACTUAL_COST'] = m.ACTUAL_COST.astype(float)
    st.dataframe(m, hide_index=True)
    st.caption('Contributions are accounting changes, not causal explanations. '
               'TEAM is Unallocated until ownership is verified.')

with anomaly_tab:
    st.write(f"{len(report['anomalies'])} service-days flagged in the selected period.")
    st.dataframe(report['anomalies'], hide_index=True)
    st.caption('Same-weekday median/MAD detector. No ground-truth labels exist, so detection '
               'accuracy has not been measured.')

with forecast_tab:
    fc = report['forecast']
    if not fc:
        st.info('At least 112 days of history are needed for forecast evaluation.')
    else:
        if not fc['planning_readiness']['ready']:
            st.warning('Experimental forecast — not cleared for budget planning: '
                       + '; '.join(fc['planning_readiness']['reasons']))
        st.json({'selected_on_validation': fc['selected'], 'scores': fc['scores']})
        sel = fc['scores'][fc['selected']]['holdout_wape']
        base = fc['scores']['seasonal_naive']['holdout_wape']
        if sel is not None and base is not None and sel > base:
            st.warning('Selected model underperformed the seasonal baseline on holdout.')
        with st.expander('Rolling (non-overlapping) diagnostics'):
            st.json(fc['rolling_validation'])

with ai_tab:
    st.caption('Drafted by a model from SQL evidence and checked automatically. '
               'Nothing here is a decision until a reviewer approves it. No savings are claimed.')
    try:
        recs = sql(session, f'SELECT * FROM {prefix}.AI_RECOMMENDATION_STATUS ORDER BY CREATED_AT DESC')
    except Exception:
        recs = None
    if recs is None or recs.empty:
        st.info('No AI recommendations recorded.')
    else:
        try:
            reviewer = st.user.user_name
        except Exception:
            reviewer = None
        for r in recs.itertuples():
            with st.container(border=True):
                st.markdown(f'**{r.REVIEW_STATUS}** · checks {"passed" if r.PASSED_CHECKS else "FAILED"} · '
                            f'{r.MODEL_ID} · {r.PROMPT_VERSION}')
                st.write(r.RECOMMENDATION)
                with st.expander('SQL evidence and checks'):
                    st.json({'evidence_ids': json.loads(r.EVIDENCE_IDS) if r.EVIDENCE_IDS else [],
                             'evidence': json.loads(r.EVIDENCE) if r.EVIDENCE else None,
                             'evaluation': json.loads(r.EVALUATION) if r.EVALUATION else None})
                if r.REVIEW_STATUS != 'PENDING_REVIEW':
                    st.caption(f'{r.REVIEW_STATUS} by {r.REVIEWER} at {str(r.DECIDED_AT)[:19]}: {r.NOTE or ""}')
                elif not reviewer:
                    st.caption('Reviewer identity unavailable; review disabled.')
                else:
                    note = st.text_input('Review note', key='n' + r.REC_ID)
                    c1, c2 = st.columns(2)
                    for col, decision in ((c1, 'APPROVED'), (c2, 'REJECTED')):
                        if col.button(decision.title(), key=decision + r.REC_ID):
                            session.sql(f'INSERT INTO {prefix}.AI_REVIEW_EVENTS (REC_ID, DECISION, REVIEWER, NOTE) '
                                        'VALUES (?, ?, ?, ?)',
                                        params=[r.REC_ID, decision, reviewer, note or None]).collect()
                            st.rerun()

with qbr_tab:
    review = execute(report)
    st.markdown(review['markdown'])
    st.download_button('Download QBR (Markdown)', review['markdown'], 'cloudledger-qbr.md')
    st.download_button('Download evidence (JSON)', json.dumps(review, indent=2, default=str),
                       'cloudledger-evidence.json')
