from datetime import date, timedelta
import math
import statistics
import numpy as np
from .data import SCALE, connect, query, fingerprint

def predict(history, horizon, method):
    values = np.asarray(history, dtype=float)
    if len(values) < 28 or not 1 <= horizon <= 90:
        raise ValueError('Need at least 28 history days and a 1–90 day horizon')
    if method == 'seasonal_naive':
        return [float(values[-7+i%7]) for i in range(horizon)]
    if method != 'trend_weekday':
        raise ValueError('Unknown forecast method')
    # Only historical observations enter the design matrix. Weekly phase is relative
    # to series start; future phase advances from the same origin.
    def design(t):
        return np.column_stack([np.ones(len(t)), t, *[(t % 7 == j).astype(float) for j in range(6)]])
    start = max(0, len(values)-84)
    t = np.arange(start,len(values))
    beta = np.linalg.lstsq(design(t), values[start:], rcond=None)[0]
    return np.maximum(0,design(np.arange(len(values),len(values)+horizon)) @ beta).tolist()

def wape(actual, predicted):
    denominator = sum(abs(v) for v in actual)
    return sum(abs(a-p) for a,p in zip(actual,predicted))/denominator if denominator else None

def rolling_validation(values,horizon=28,min_history=56):
    """Non-overlapping forward test windows; diagnostic, never used for model selection."""
    if horizon<1 or min_history<28:
        raise ValueError('Invalid rolling evaluation configuration')
    folds=[]
    for origin in range(min_history,len(values)-horizon+1,horizon):
        actual=values[origin:origin+horizon]
        folds.append({'train_days':origin,'test_start_index':origin,
                      'test_end_exclusive':origin+horizon,
                      'wape':{m:wape(actual,predict(values[:origin],horizon,m))
                              for m in ('seasonal_naive','trend_weekday')}})
    return {'horizon_days':horizon,'nonoverlapping_folds':folds,
            'purpose':'Historical diagnostics; already observed data, not a new independent test'}

def planning_readiness(scores,selected,rolling,max_wape=.20,min_folds=3):
    """Explicit engineering policy; not a Finance-approved accuracy threshold."""
    reasons=[]
    folds=rolling['nonoverlapping_folds']
    if len(folds)<min_folds:reasons.append('Insufficient non-overlapping evaluation periods')
    test=scores[selected]['holdout_wape']
    baseline=scores['seasonal_naive']['holdout_wape']
    if test is None or test>max_wape:reasons.append('Holdout error exceeds policy or is undefined')
    if test is not None and baseline is not None and test>baseline:
        reasons.append('Selected model underperformed seasonal baseline')
    if any(f['wape'][selected] is None or f['wape'][selected]>max_wape for f in folds):
        reasons.append('At least one historical period exceeds error policy')
    return {'ready':not reasons,'reasons':reasons,'max_wape':max_wape,
            'min_folds':min_folds,'policy_owner':'Engineering default; Finance approval pending'}

def forecast(values, horizon=28):
    if len(values) < 112:
        raise ValueError('112 days required for separate validation and holdout backtests')
    validation_origin = len(values)-56
    test_origin = len(values)-28
    scores = {}
    for method in ('seasonal_naive','trend_weekday'):
        scores[method] = {
            'validation_wape': wape(values[validation_origin:test_origin],predict(values[:validation_origin],28,method)),
            'holdout_wape': wape(values[test_origin:],predict(values[:test_origin],28,method))}
    selected = min(scores,key=lambda m: scores[m]['validation_wape'] if scores[m]['validation_wape'] is not None else math.inf)
    rolling=rolling_validation(values,horizon)
    return dict(selected=selected, scores=scores, horizon_days=horizon,
                rolling_validation=rolling,planning_readiness=planning_readiness(scores,selected,rolling),
                predictions=predict(values,horizon,selected),
                selection='28-day validation only; following 28-day holdout is not used for selection')

def anomalies(rows, start, end):
    """One-sided same-weekday median/MAD detector using only prior eight weeks."""
    services = sorted({r['service'] for r in rows})
    first = date.fromisoformat(min(r['day'] for r in rows))
    last = date.fromisoformat(max(r['day'] for r in rows))
    daily = {}
    for r in rows:
        key=(r['service'],r['day'])
        daily[key] = daily.get(key,0)+float(r['amount'])
    found=[]
    for service in services:
        history=[]
        for offset in range((last-first).days+1):
            day=(first+timedelta(days=offset)).isoformat()
            value=daily.get((service,day),0)
            previous=history[-56::7] if len(history)>=56 else []
            if previous and start<=day<=end:
                baseline=statistics.median(previous)
                mad=statistics.median(abs(v-baseline) for v in previous)
                threshold=max(5.0,abs(baseline)*.35,6*1.4826*mad)
                if value-baseline>threshold:
                    found.append(dict(day=day,service=service,actual=round(value,4),
                                      baseline=round(baseline,4),excess=round(value-baseline,4),
                                      explanation='Higher than prior same-weekday spending; cause requires engineering review'))
            history.append(value)
    return found

def analyze(rows,start,end,budget=None,as_of=None):
    if start>end:
        raise ValueError('Start is after end')
    date.fromisoformat(start); date.fromisoformat(end)
    if budget is not None and (not math.isfinite(budget) or budget<=0):
        raise ValueError('Budget must be positive and finite')
    first,last=min(r['day'] for r in rows),max(r['day'] for r in rows)
    if start<first or end>last:
        raise ValueError('Requested period is outside available data')
    db=connect(rows)
    try:
        totals=query(db,'SELECT SUM(amount_units) total, MAX(estimated) estimated FROM costs WHERE day BETWEEN ? AND ?', (start,end))[0]
        breakdown=query(db,'SELECT service,team,SUM(amount_units) amount_units FROM costs WHERE day BETWEEN ? AND ? GROUP BY service,team ORDER BY amount_units DESC',(start,end))
        series=query(db,'SELECT day,amount_units FROM daily_cost WHERE day<=? ORDER BY day',(end,))
        duration=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
        previous_end=(date.fromisoformat(start)-timedelta(days=1)).isoformat()
        previous_start=(date.fromisoformat(start)-timedelta(days=duration)).isoformat()
        previous=None
        drivers=[]
        if previous_start>=first:
            previous=query(db,'SELECT SUM(amount_units) total FROM costs WHERE day BETWEEN ? AND ?', (previous_start,previous_end))[0]['total']/SCALE
            old=query(db,'SELECT service,SUM(amount_units) amount_units FROM costs WHERE day BETWEEN ? AND ? GROUP BY service',(previous_start,previous_end))
            old={r['service']:r['amount_units']/SCALE for r in old}
            current={}
            for r in breakdown:
                current[r['service']]=current.get(r['service'],0)+r['amount_units']/SCALE
            drivers=sorted([dict(service=s,delta=round(current.get(s,0)-old.get(s,0),4)) for s in set(old)|set(current)],key=lambda r:abs(r['delta']),reverse=True)
        total=totals['total']/SCALE
        prediction=forecast([s['amount_units']/SCALE for s in series]) if len(series)>=112 else None
        age=(date.fromisoformat(as_of or date.today().isoformat())-date.fromisoformat(last)).days
        return dict(source=rows[0]['source'],source_sha256=fingerprint(rows),rows=len(rows),
                    start=start,end=end,source_end=last,source_age_days=age,estimated=bool(totals['estimated']),
                    actual=round(total,4),budget=budget,
                    budget_variance=round(total-budget,4) if budget else None,
                    budget_variance_pct=(total/budget-1)*100 if budget else None,
                    previous_actual=previous,previous_start=previous_start if previous is not None else None,
                    previous_end=previous_end if previous is not None else None,
                    period_delta=total-previous if previous is not None else None,
                    breakdown=[dict(service=r['service'],team=r['team'],amount=r['amount_units']/SCALE) for r in breakdown],
                    drivers=drivers,anomalies=anomalies(rows,start,end),forecast=prediction,
                    daily=[dict(day=s['day'],amount=s['amount_units']/SCALE) for s in series],
                    reconciliation_units=totals['total']-sum(r['amount_units'] for r in breakdown))
    finally:
        db.close()
