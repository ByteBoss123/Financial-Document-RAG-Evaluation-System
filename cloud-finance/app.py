import json
import os
from datetime import date,timedelta
from pathlib import Path
import pandas as pd
import streamlit as st
from cloud_finance.data import demo,from_cost_explorer,validate
from cloud_finance.analytics import analyze
from cloud_finance.workflow import execute,plan_with_bedrock
from cloud_finance.auth import verify_password

st.set_page_config(page_title='Cloud Finance Intelligence',page_icon='☁',layout='wide')
if os.getenv('FINANCE_PRIVATE_MODE')=='1':
    expected=os.getenv('FINANCE_PASSWORD_SHA256','')
    if not expected:
        st.error('Private deployment is missing access configuration. Access denied.'); st.stop()
    password=st.text_input('Access password',type='password')
    if not verify_password(password,expected):
        st.info('Enter the deployment password to access private billing.'); st.stop()
st.title('Cloud Finance Intelligence')
st.caption('Product Finance / spend planning and investigation')
st.sidebar.header('Analysis controls')
upload=st.sidebar.file_uploader('AWS Cost Explorer JSON (SERVICE / DAILY)',type=['json'])
private_path=os.getenv('FINANCE_DATA_PATH','')
if private_path and os.getenv('FINANCE_PRIVATE_MODE')!='1':
    st.error('Server-side billing files require private mode. Access denied.'); st.stop()
real_source=bool(upload or private_path)
try:
    rows=(from_cost_explorer(json.load(upload)) if upload else
          from_cost_explorer(json.loads(Path(private_path).read_text())) if private_path else demo())
    validate(rows)
except (ValueError,KeyError,TypeError,OSError) as exc:
    st.error('Invalid billing export: '+str(exc)); st.stop()
if not real_source:
    st.info('Synthetic portfolio demo — generated billing, assumed budgets, no realized savings.')
else:
    st.info('Uploaded billing remains in this session. No model is called unless you request an AI plan.')
first,last=date.fromisoformat(min(r['day'] for r in rows)),date.fromisoformat(max(r['day'] for r in rows))
start=st.sidebar.date_input('Period start',max(first,last-timedelta(days=89)),min_value=first,max_value=last)
end=st.sidebar.date_input('Period end',last,min_value=first,max_value=last)
use_budget=st.sidebar.checkbox('Supply a planning budget',value=not real_source)
budget=st.sidebar.number_input('Period budget (USD)',min_value=1.0,value=13000.0,step=100.0) if use_budget else None
try:
    report=analyze(rows,start.isoformat(),end.isoformat(),budget)
except (ValueError,KeyError,TypeError) as exc:
    st.error(str(exc)); st.stop()
cols=st.columns(4)
cols[0].metric('Period spend',f"${report['actual']:,.2f}")
cols[1].metric('Budget variance',f"${report['budget_variance']:,.2f}" if budget else 'Not supplied')
cols[2].metric('Flagged service-days',len(report['anomalies']))
cols[3].metric('Reconciliation','PASS' if report['reconciliation_units']==0 else 'FAIL')
st.caption(f"Source through {last} • {report['source_age_days']} days old • {'Estimated charges included' if report['estimated'] else 'Source does not mark charges estimated'}")
overview,forecast,investigate,qbr=st.tabs(['Spend & allocation','Forecast validation','Investigate','QBR & audit'])
with overview:
    daily=pd.DataFrame(report['daily'])
    st.line_chart(daily[daily.day>=start.isoformat()].set_index('day'),y='amount')
    st.subheader('Service and team allocation')
    st.dataframe(pd.DataFrame(report['breakdown']),hide_index=True,use_container_width=True)
    st.caption('AWS service-only exports are Unallocated; demo team assignments are fictional. Negative charges remain in totals.')
with forecast:
    f=report['forecast']
    if f:
        st.write('Selected on validation:',f['selected'])
        st.dataframe(pd.DataFrame(f['scores']).T.style.format('{:.2%}'))
        chosen=f['scores'][f['selected']]['holdout_wape']
        baseline=f['scores']['seasonal_naive']['holdout_wape']
        if chosen is not None and baseline is not None and chosen>baseline:
            st.warning('Selected model underperformed the seasonal baseline on holdout. Review before using for planning.')
        future=pd.DataFrame({'day':[end+timedelta(days=i+1) for i in range(f['horizon_days'])],'forecast':f['predictions']})
        st.line_chart(future.set_index('day'))
        st.caption('28-day validation followed by a separate 28-day holdout. No calibrated prediction intervals. Net costs with credits can be negative; this nonnegative forecast models spending, so inspect credit-heavy periods separately.')
    else:
        st.warning('At least 112 daily observations are required for this evaluation.')
with investigate:
    st.subheader('Contributors to change from an equal-length preceding period')
    st.dataframe(pd.DataFrame(report['drivers']),hide_index=True)
    st.subheader('Anomalies requiring engineering review')
    st.dataframe(pd.DataFrame(report['anomalies']),hide_index=True)
    st.caption('Flags show spending departures, not waste. Validate utilization and workload requirements before changing resources.')
with qbr:
    st.write('Generate a review from verified analytical results. AI may select analysis steps; it cannot execute arbitrary SQL or modify resources.')
    question=st.text_input('Review request','Prepare a QBR covering variance, drivers, anomalies and forecast')
    model=os.getenv('BEDROCK_MODEL_ID','')
    use_ai=st.checkbox('Use Bedrock to select analysis steps',disabled=not bool(model))
    if not model:
        st.caption('Deterministic mode active. Set BEDROCK_MODEL_ID and use an IAM role to enable model planning.')
    if st.button('Generate review',type='primary'):
        try:
            plan=plan_with_bedrock(question,model) if use_ai else None
            result=execute(report,plan)
            result['planner']='bedrock' if use_ai else 'deterministic'
            st.markdown(result['markdown'])
            st.download_button('Download review',result['markdown'],'cloud-finance-review.md')
            st.download_button('Download audit evidence',json.dumps(result,indent=2),'review-evidence.json')
        except Exception:
            st.error('AI planning failed or returned an invalid plan. Disable AI planning to generate a deterministic review. No report was published.')
    st.download_button('Download analytical evidence',json.dumps(report,indent=2),'analysis.json')
