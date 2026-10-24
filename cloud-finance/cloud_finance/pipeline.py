"""Transactional snapshot publishing with durable run history and last-good retention."""
from datetime import datetime,timezone
import json
import sqlite3
import uuid
from .analytics import analyze
from .workflow import execute

def publish(db_path,rows,start,end,budget=None):
    db=sqlite3.connect(db_path,timeout=30)
    db.executescript('''
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, finished_at TEXT,
        status TEXT, source_hash TEXT, error TEXT);
      CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1),
        run_id TEXT, analysis_json TEXT, review_json TEXT);
    ''')
    run_id=str(uuid.uuid4())
    now=datetime.now(timezone.utc).isoformat()
    try:
        report=analyze(rows,start,end,budget)
        review=execute(report)
        if report['reconciliation_units']!=0:
            raise ValueError('Reconciliation failed')
        with db:
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(run_id,now,'success',report['source_sha256'],None))
            db.execute('INSERT INTO snapshot VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,analysis_json=excluded.analysis_json,review_json=excluded.review_json',
                       (run_id,json.dumps(report),json.dumps(review)))
        return run_id
    except Exception as exc:
        with db:
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(run_id,now,'failure',None,type(exc).__name__))
        raise
    finally:
        db.close()

def health(db_path,max_age_hours=48):
    db=sqlite3.connect(db_path)
    try:
        row=db.execute('SELECT runs.finished_at FROM snapshot JOIN runs USING(run_id) WHERE snapshot.id=1').fetchone()
        latest=db.execute('SELECT status FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
        if row is None:
            return {'healthy':False,'reason':'No successful snapshot'}
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(row[0])).total_seconds()/3600
        return {'healthy':age<=max_age_hours and latest[0]=='success','snapshot_age_hours':age,'latest_run_status':latest[0]}
    finally:
        db.close()
