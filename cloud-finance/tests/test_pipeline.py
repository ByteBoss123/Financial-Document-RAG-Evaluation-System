import sqlite3
import hashlib
import pytest
from cloud_finance.data import demo
from cloud_finance.pipeline import publish,health
from cloud_finance.auth import verify_password

def test_failed_refresh_retains_last_good_and_records_failure(tmp_path):
    path=tmp_path/'history.db';rows=demo()
    good=publish(path,rows,'2026-07-01','2026-09-30',13000)
    assert health(path)['healthy']
    rows.append(rows[0])
    with pytest.raises(ValueError):publish(path,rows,'2026-07-01','2026-09-30',13000)
    db=sqlite3.connect(path)
    assert db.execute('SELECT run_id FROM snapshot').fetchone()[0]==good
    assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==2
    db.close()
    assert not health(path)['healthy']

def test_private_access_fails_closed():
    expected=hashlib.sha256(b'test-only-long-password').hexdigest()
    assert verify_password('test-only-long-password',expected)
    assert not verify_password('wrong',expected)
    assert not verify_password('anything','')
