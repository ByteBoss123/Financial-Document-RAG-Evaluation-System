from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import random
import sqlite3

SCALE = 10**10  # Preserve AWS billing precision; round only for presentation.

def units(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError('Non-finite cost')
    return int((amount * SCALE).to_integral_value(rounding=ROUND_HALF_UP))

def demo(seed=42, days=365):
    rng = random.Random(seed)
    rows = []
    services = [('Compute', 'Platform', 70), ('Storage', 'Data', 20), ('Inference', 'AI', 40)]
    for i in range(days):
        day = date(2025, 10, 1) + timedelta(days=i)
        for service, team, base in services:
            value = base * (1 + .0007 * i) * (1 if day.weekday() < 5 else .72)
            value *= 1 + rng.uniform(-.05, .05)
            injected = i in (220, 265, 310, 345) and service == 'Compute'
            if injected:
                value *= 3
            rows.append(dict(day=day.isoformat(), account='demo-account', service=service,
                             team=team, amount=str(round(value, 4)), currency='USD',
                             estimated=False, injected=injected, source='synthetic'))
    return rows

def from_cost_explorer(payload):
    definitions = payload.get('GroupDefinitions', [])
    if [d.get('Key') for d in definitions] != ['SERVICE']:
        raise ValueError('Expected Cost Explorer grouped by SERVICE only')
    rows = []
    for period in payload['ResultsByTime']:
        start = date.fromisoformat(period['TimePeriod']['Start'])
        end = date.fromisoformat(period['TimePeriod']['End'])
        if end - start != timedelta(days=1):
            raise ValueError('DAILY Cost Explorer data required')
        groups = period.get('Groups', [])
        if not groups:
            groups = [{'Keys': ['No billed service'], 'Metrics': {'UnblendedCost': {'Amount': '0', 'Unit': 'USD'}}}]
        for group in groups:
            metric = group['Metrics']['UnblendedCost']
            rows.append(dict(day=start.isoformat(), account='payer-aggregate',
                             service=group['Keys'][0], team='Unallocated',
                             amount=metric['Amount'], currency=metric['Unit'],
                             estimated=period.get('Estimated', True), injected=False,
                             source='aws-cost-explorer'))
    return rows

def validate(rows):
    if not rows:
        raise ValueError('No billing records')
    keys = set()
    sources = set()
    for row in rows:
        date.fromisoformat(row['day'])
        key = tuple(row[k] for k in ('day', 'account', 'service'))
        if key in keys:
            raise ValueError('Duplicate daily account/service grain')
        keys.add(key)
        if row['currency'] != 'USD':
            raise ValueError('Mixed or unsupported currency; convert explicitly before import')
        for k in ('account', 'service', 'team', 'source'):
            if not isinstance(row[k], str) or not row[k].strip():
                raise ValueError('Missing dimension: ' + k)
        sources.add(row['source'])
        if type(row['estimated']) is not bool:
            raise ValueError('Estimated must be a boolean')
        units(row['amount'])
    if len(sources) != 1:
        raise ValueError('Cannot combine synthetic and real source snapshots')
    days = sorted({r['day'] for r in rows})
    expected = (date.fromisoformat(days[-1])-date.fromisoformat(days[0])).days+1
    if len(days) != expected:
        raise ValueError('Missing whole billing day; do not silently impute missing ingestion')

def connect(rows):
    validate(rows)
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE costs(day TEXT, account TEXT, service TEXT, team TEXT,
        amount_units INTEGER, estimated INTEGER, PRIMARY KEY(day,account,service));
      CREATE INDEX costs_team_day ON costs(team,day);
      CREATE VIEW daily_cost AS SELECT day, SUM(amount_units) AS amount_units,
        MAX(estimated) AS estimated FROM costs GROUP BY day;
      CREATE VIEW monthly_cost AS SELECT substr(day,1,7) AS month, team, service,
        SUM(amount_units) AS amount_units FROM costs GROUP BY month,team,service;
    ''')
    db.executemany('INSERT INTO costs VALUES(?,?,?,?,?,?)',
                   [(r['day'],r['account'],r['service'],r['team'],units(r['amount']),int(r['estimated'])) for r in rows])
    return db

def query(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params)]

def fingerprint(rows):
    canonical = sorted(rows, key=lambda r:(r['day'],r['account'],r['service']))
    return hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
