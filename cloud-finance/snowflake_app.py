"""Run in a Snowflake warehouse Streamlit runtime, or locally with named connection."""
from datetime import timedelta
import json
import streamlit as st
from cloud_finance.snowflake_backend import identifier
from cloud_finance.analytics import analyze
from cloud_finance.workflow import execute

st.set_page_config(page_title='Cloud Finance | Snowflake',layout='wide')
st.title('Cloud Finance | Snowflake')
st.caption('Real AWS billing • Snowflake reporting models • Python forecasts')
database=st.sidebar.text_input('Database','CLOUD_FINANCE')
schema=st.sidebar.text_input('Schema','CLOUD_FINANCE_BI')
try:
    prefix=identifier(database)+'.'+identifier(schema)
    conn=st.connection('snowflake')
    # TTL=0 avoids serving cached data after a completed load. App viewers must all
    # be authorized for the owner role's data when using owner-rights runtimes.
    daily=conn.query(f'SELECT * FROM {prefix}.DAILY_COST ORDER BY USAGE_DATE',ttl=0)
    monthly=conn.query(f'SELECT * FROM {prefix}.MONTHLY_SERVICE_TEAM_COST ORDER BY USAGE_MONTH,SERVICE',ttl=0)
    costs=conn.query(f'''SELECT USAGE_DATE,ACCOUNT_KEY,SERVICE,TEAM,
      TO_VARCHAR(UNBLENDED_COST) UNBLENDED_COST,CURRENCY,ESTIMATED
      FROM {prefix}.COST_DAILY ORDER BY USAGE_DATE,ACCOUNT_KEY,SERVICE''',ttl=0)
except Exception:
    st.error('Snowflake connection or reporting models are unavailable. Configure the connection and run the loader first.'); st.stop()
if costs.empty:
    st.warning('No loaded AWS snapshot.'); st.stop()
rows=[dict(day=str(r.USAGE_DATE),account=r.ACCOUNT_KEY,service=r.SERVICE,team=r.TEAM,
           amount=str(r.UNBLENDED_COST),currency=r.CURRENCY,estimated=bool(r.ESTIMATED),
           source='aws-cost-explorer',injected=False) for r in costs.itertuples()]
first,last=min(daily.USAGE_DATE),max(daily.USAGE_DATE)
start=st.sidebar.date_input('Start',max(first,last-timedelta(days=29)),min_value=first,max_value=last)
end=st.sidebar.date_input('End',last,min_value=first,max_value=last)
has_budget=st.sidebar.checkbox('Supply an approved period budget',value=False)
budget=st.sidebar.number_input('Budget (USD)',min_value=0.01,value=100.0) if has_budget else None
try:
    report=analyze(rows,str(start),str(end),budget)
except ValueError as exc:
    st.error(str(exc));st.stop()
a,b,c=st.columns(3)
a.metric('Actual',f"${report['actual']:,.2f}")
b.metric('Variance',f"${report['budget_variance']:,.2f}" if budget else 'No budget provided')
c.metric('Source through',str(last))
st.line_chart(daily[(daily.USAGE_DATE>=start)&(daily.USAGE_DATE<=end)].set_index('USAGE_DATE'),y='ACTUAL_COST')
st.subheader('Monthly reporting model — full loaded history')
st.dataframe(monthly,hide_index=True)
st.subheader('Period investigation')
st.dataframe(report['drivers'],hide_index=True)
st.dataframe(report['anomalies'],hide_index=True)
st.caption('Service contributions are not causal explanations. Unallocated means ownership has not been verified. Estimated billing can change.')
if report['forecast']:
    f=report['forecast'];st.subheader('Forecast validation')
    st.json({'selected_on_validation':f['selected'],'scores':f['scores']})
    selected=f['scores'][f['selected']]['holdout_wape'];baseline=f['scores']['seasonal_naive']['holdout_wape']
    if selected is not None and baseline is not None and selected>baseline:
        st.warning('Selected model underperformed the seasonal baseline on holdout. Review before using for planning.')
if st.button('Generate evidence-backed QBR'):
    review=execute(report)
    st.markdown(review['markdown'])
    st.download_button('Download review',review['markdown'],'cloud-finance-qbr.md')
    st.download_button('Download evidence',json.dumps(review,indent=2),'cloud-finance-evidence.json')
st.caption('This Snowflake entrypoint uses deterministic reporting. Bedrock planning remains in app.py; Cortex integration is not yet implemented.')
