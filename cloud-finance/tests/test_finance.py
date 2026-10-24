import copy
from decimal import Decimal
import json
import pytest
from cloud_finance.data import demo,connect,units,SCALE,from_cost_explorer,validate,fingerprint
from cloud_finance.analytics import analyze,forecast,anomalies
from cloud_finance.workflow import validate_plan,execute,parse_response

def test_precision_and_negative_credit_reconcile():
    rows=demo(days=2)
    rows[0]['amount']='0.0000000001'
    rows[1]['amount']='-12.504'
    db=connect(rows)
    actual=db.execute('SELECT SUM(amount_units) FROM costs').fetchone()[0]
    expected=sum(Decimal(r['amount']) for r in rows)
    assert Decimal(actual)/SCALE==expected
    db.close()

@pytest.mark.parametrize('change',[lambda r:r.append(r[0].copy()),lambda r:r[0].update(amount='NaN'),lambda r:r[0].update(currency='EUR'),lambda r:r[0].update(team=''),lambda r:r[0].update(estimated='false'),lambda r:r[0].update(source='aws')])
def test_bad_source_rejected(change):
    rows=demo(days=3);change(rows)
    with pytest.raises(ValueError):validate(rows)

def test_whole_day_missing_rejected():
    rows=[r for r in demo(days=3) if r['day']!='2025-10-02']
    with pytest.raises(ValueError,match='Missing whole'):validate(rows)

def test_reconciliation_budget_and_equal_period_drivers():
    rows=demo()
    r=analyze(rows,'2026-07-01','2026-09-30',13000)
    source=sum(Decimal(x['amount']) for x in rows if '2026-07-01'<=x['day']<='2026-09-30')
    assert r['actual']==float(source)
    assert r['reconciliation_units']==0
    assert r['budget_variance']==round(float(source)-13000,4)
    assert sum(x['delta'] for x in r['drivers'])==pytest.approx(r['period_delta'],abs=.001)

def test_holdout_does_not_choose_model():
    v=[100+i*.1+(i%7)*2 for i in range(160)]
    a=forecast(v);v[-28:]=[9999]*28;b=forecast(v)
    assert a['selected']==b['selected']
    for m in a['scores']:assert a['scores'][m]['validation_wape']==b['scores'][m]['validation_wape']

def test_anomaly_has_no_future_leakage():
    rows=demo();a=anomalies(rows,'2026-05-01','2026-06-01')
    for r in rows:
        if r['day']>'2026-06-01':r['amount']='99999'
    assert anomalies(rows,'2026-05-01','2026-06-01')==a

def test_missing_comparison_and_budget_abstain():
    r=analyze(demo(days=30),'2025-10-01','2025-10-30')
    assert r['previous_actual'] is None and r['forecast'] is None
    text=execute(r)['markdown']
    assert 'No approved budget' in text and 'Insufficient history' in text

@pytest.mark.parametrize('plan',[{'steps':['delete_resources']},{'steps':['variance','variance']},{'steps':[]},{'steps':['variance'],'sql':'DROP TABLE costs'},{'steps':[{}]}])
def test_untrusted_plan_rejected(plan):
    with pytest.raises(ValueError):validate_plan(plan)

def test_ce_import_retains_estimates_and_precision():
    payload={'GroupDefinitions':[{'Key':'SERVICE'}],'ResultsByTime':[{'TimePeriod':{'Start':'2026-09-01','End':'2026-09-02'},'Estimated':True,'Groups':[{'Keys':['Storage'],'Metrics':{'UnblendedCost':{'Amount':'0.0000000012','Unit':'USD'}}}]}]}
    rows=from_cost_explorer(payload)
    assert units(rows[0]['amount'])==12 and rows[0]['estimated'] is True
    assert rows[0]['team']=='Unallocated'

def test_fingerprint_order_independent():
    rows=demo(days=2)
    assert fingerprint(rows)==fingerprint(rows[::-1])

def test_report_cites_every_tool_and_never_claims_savings():
    result=execute(analyze(demo(),'2026-07-01','2026-09-30',13000))
    for t in result['trace']:assert f"[evidence:{t['tool']}]" in result['markdown']
    assert 'No savings have been measured' in result['markdown']

def test_parse_model_json_and_reject_arbitrary_sql():
    assert parse_response({'output':{'message':{'content':[{'text':'```json\n{"steps":["variance"]}\n```'}]}}})=={'steps':['variance']}
    with pytest.raises(ValueError):parse_response({'output':{'message':{'content':[{'text':'{"steps":["SELECT * FROM costs"]}'}]}}})
