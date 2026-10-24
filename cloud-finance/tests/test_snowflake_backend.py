from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from cloud_finance.data import demo
from cloud_finance.snowflake_backend import load_snapshot,identifier

def real_shaped():
    rows=demo(days=2)
    for r in rows:r['source']='aws-cost-explorer'
    return rows

def connection(rows,bad_total=False,fail_publish=False):
    con=MagicMock(); cur=con.cursor.return_value
    total=sum(Decimal(r['amount']) for r in rows)
    cur.fetchone.side_effect=[(len(rows),total+1 if bad_total else total),(0,)]
    if fail_publish:
        def run(sql,*args):
            if sql.startswith('INSERT INTO DB.BI.COST_DAILY'):raise RuntimeError('publication failed')
        cur.execute.side_effect=run
    return con,cur

def test_bad_total_never_replaces_published_data():
    rows=real_shaped();con,cur=connection(rows,bad_total=True)
    with pytest.raises(ValueError,match='reconciliation'):load_snapshot(con,rows,'DB','BI')
    assert not any(x.args[0].startswith('DELETE') for x in cur.execute.call_args_list)

def test_failed_publication_rolls_back():
    rows=real_shaped();con,cur=connection(rows,fail_publish=True)
    with pytest.raises(RuntimeError):load_snapshot(con,rows,'DB','BI')
    assert any(x.args[0]=='ROLLBACK' for x in cur.execute.call_args_list)
    assert not any(x.args[0]=='COMMIT' for x in cur.execute.call_args_list)

def test_synthetic_rejected_before_connection_use():
    con=MagicMock()
    with pytest.raises(ValueError,match='Real AWS'):load_snapshot(con,demo(days=2),'DB','BI')
    con.cursor.assert_not_called()

def test_identifier_injection_rejected():
    with pytest.raises(ValueError):identifier('DB; DROP DATABASE X')

def test_successful_snapshot_commits():
    rows=real_shaped();con,cur=connection(rows)
    assert load_snapshot(con,rows,'DB','BI')['reconciled']
    assert any(x.args[0]=='COMMIT' for x in cur.execute.call_args_list)
