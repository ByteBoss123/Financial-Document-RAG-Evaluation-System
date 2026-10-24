from decimal import Decimal
import json
import pytest
from cloud_finance.snowpark_adapter import SnowparkConnection, load_procedure
from cloud_finance.snowflake_backend import load_snapshot


class Row(tuple):
    pass


class FakeSession:
    """Records SQL; answers the loader's two reconciliation queries."""
    def __init__(self, total, count, dup=0, fail_on=None):
        self.calls = []
        self.total, self.count, self.dup, self.fail_on = total, count, dup, fail_on

    def sql(self, q, params=None):
        self.calls.append((q, params))
        if self.fail_on and q.startswith(self.fail_on):
            raise RuntimeError('boom')
        outer = self

        class R:
            def collect(self_inner):
                if 'COUNT(*),SUM(UNBLENDED_COST)' in q:
                    return [Row((outer.count, outer.total))]
                if 'HAVING COUNT(*)>1' in q:
                    return [Row((outer.dup,))]
                return []
        return R()


def payload(days=2):
    res = []
    for d in range(days):
        res.append({'TimePeriod': {'Start': f'2026-07-0{d+1}', 'End': f'2026-07-0{d+2}'},
                    'Estimated': False,
                    'Groups': [{'Keys': ['Amazon S3'], 'Metrics': {'UnblendedCost': {'Amount': '0.0123456789', 'Unit': 'USD'}}},
                               {'Keys': ['AWS Lambda'], 'Metrics': {'UnblendedCost': {'Amount': '1.5', 'Unit': 'USD'}}}]})
    return {'GroupDefinitions': [{'Type': 'DIMENSION', 'Key': 'SERVICE'}], 'ResultsByTime': res}


def test_executemany_batches_with_qmark_and_exact_decimals():
    s = FakeSession(Decimal('3.0246913578'), 4)
    out = json.loads(load_procedure(s, json.dumps(payload())))
    assert out['reconciled'] and out['rows'] == 4
    inserts = [c for c in s.calls if c[0].startswith('INSERT INTO CLOUDLEDGER.CLOUD_FINANCE_BI.COST_STAGE')]
    assert len(inserts) == 1 and inserts[0][0].count('(?,?,?,?,?,?,?,?)') == 4
    assert '0.0123456789' in inserts[0][1]  # Decimal bound as exact string
    assert any(c[0] == 'COMMIT' for c in s.calls)
    assert s.calls[0][0].startswith('INSERT INTO CLOUDLEDGER.CLOUD_FINANCE_BI.RAW_COST_EXPLORER')


def test_reconciliation_failure_logged_and_published_data_untouched():
    s = FakeSession(Decimal('999'), 4)
    with pytest.raises(ValueError, match='reconciliation'):
        load_procedure(s, json.dumps(payload()))
    assert not any(c[0].startswith('DELETE') for c in s.calls)
    assert s.calls[-1][0].startswith('INSERT INTO CLOUDLEDGER.CLOUD_FINANCE_BI.LOAD_FAILURES')


def test_duplicate_grain_rejected_before_staging():
    p = payload(1)
    p['ResultsByTime'][0]['Groups'].append(p['ResultsByTime'][0]['Groups'][0])
    s = FakeSession(Decimal('0'), 0)
    with pytest.raises(ValueError, match='Duplicate'):
        load_procedure(s, json.dumps(p))
    assert not any('COST_STAGE' in c[0] for c in s.calls)
    assert 'LOAD_FAILURES' in s.calls[-1][0]


def test_publish_failure_rolls_back():
    s = FakeSession(Decimal('3.0246913578'), 4, fail_on='INSERT INTO CLOUDLEDGER.CLOUD_FINANCE_BI.COST_DAILY')
    with pytest.raises(RuntimeError):
        load_procedure(s, json.dumps(payload()))
    assert any(c[0] == 'ROLLBACK' for c in s.calls) and not any(c[0] == 'COMMIT' for c in s.calls)
