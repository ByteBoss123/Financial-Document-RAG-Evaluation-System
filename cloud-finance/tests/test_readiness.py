from cloud_finance.analytics import rolling_validation,forecast
from cloud_finance.workflow import execute
from cloud_finance.analytics import analyze
from cloud_finance.data import demo

def test_rolling_folds_are_forward_and_nonoverlapping():
    v=[100+i*.1 for i in range(200)]
    folds=rolling_validation(v)['nonoverlapping_folds']
    for a,b in zip(folds,folds[1:]):
        assert a['test_end_exclusive']<=b['test_start_index']
    for f in folds:assert f['train_days']==f['test_start_index']
    changed=v[:];changed[112:]=[9999]*len(changed[112:])
    assert rolling_validation(changed)['nonoverlapping_folds'][:2]==folds[:2]

def test_insufficient_history_never_marked_ready():
    result=forecast([100]*115)
    assert not result['planning_readiness']['ready']

def test_report_carries_readiness_warning():
    report=analyze(demo(days=115),'2025-10-01','2026-01-23')
    assert 'not cleared for budget planning' in execute(report)['markdown']
