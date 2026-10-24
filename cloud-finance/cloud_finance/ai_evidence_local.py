"""Local mirror of ai_review.EVIDENCE_SQL, used to cross-check that Snowflake's
evidence equals an independent computation over the same billing rows."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


def _r(x, places='0.01'):
    return float(Decimal(x).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def evidence(rows):
    end = max(date.fromisoformat(r['day']) for r in rows)
    last, prior = defaultdict(Decimal), defaultdict(Decimal)
    for r in rows:
        d = date.fromisoformat(r['day'])
        if d > end - timedelta(days=28):
            last[r['service']] += Decimal(r['amount'])
        elif d > end - timedelta(days=56):
            prior[r['service']] += Decimal(r['amount'])
    e1 = []
    for s in set(last) | set(prior):
        l, p = _r(last[s]), _r(prior[s])
        ch = _r(Decimal(str(l)) - Decimal(str(p)))
        if abs(ch) >= 0.01 or l >= 0.01:
            e1.append({'SERVICE': s, 'LAST_28D_USD': l, 'PRIOR_28D_USD': p, 'CHANGE_USD': ch})
    e1 = sorted(e1, key=lambda x: (-abs(x['CHANGE_USD']), x['SERVICE']))[:8]

    month = defaultdict(Decimal); mdays = defaultdict(set); mest = defaultdict(bool)
    for r in rows:
        m = r['day'][:7]
        month[m] += Decimal(r['amount']); mdays[m].add(r['day']); mest[m] |= bool(r['estimated'])
    e2 = [{'MONTH': m, 'TOTAL_USD': _r(month[m]), 'DAYS': len(mdays[m]), 'HAS_ESTIMATES': mest[m]}
          for m in sorted(month)]

    svc = defaultdict(Decimal)
    for r in rows:
        svc[r['service']] += Decimal(r['amount'])
    total = sum(svc.values())
    e3 = [{'SERVICE': s, 'TOTAL_USD': _r(v), 'SHARE_PCT': _r(100 * v / total, '0.1')}
          for s, v in sorted(svc.items(), key=lambda kv: -kv[1])[:6]]
    return {'E1_service_change_28d': e1, 'E2_monthly_total': e2, 'E3_top_services_total': e3}
