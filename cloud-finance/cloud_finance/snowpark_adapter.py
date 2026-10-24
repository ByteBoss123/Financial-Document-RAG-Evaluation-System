"""Run the existing DB-API loader (snowflake_backend.load_snapshot) inside a
Snowflake Python stored procedure. The adapter only translates cursor calls to
Snowpark; validation, reconciliation and the transactional publish stay in
load_snapshot so the procedure and the local CLI share one code path."""
from datetime import date
from decimal import Decimal
import hashlib
import json


def _bind(value):
    # Decimal and date are sent as strings so NUMBER(28,10)/DATE casts are exact.
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value


class SnowparkCursor:
    def __init__(self, session):
        self.session = session
        self._rows = []

    def execute(self, sql, params=None):
        if params is None:
            self._rows = self.session.sql(sql).collect()
        else:
            self._rows = self.session.sql(sql.replace('%s', '?'),
                                          params=[_bind(v) for v in params]).collect()

    def executemany(self, sql, seq, batch=200):
        head, sep, tail = sql.partition('VALUES')
        if not sep:
            raise ValueError('executemany requires an INSERT ... VALUES statement')
        width = tail.count('%s')
        group = '(' + ','.join(['?'] * width) + ')'
        seq = list(seq)
        for i in range(0, len(seq), batch):
            chunk = seq[i:i + batch]
            self.session.sql(head + 'VALUES ' + ','.join([group] * len(chunk)),
                             params=[_bind(v) for row in chunk for v in row]).collect()

    def fetchone(self):
        return tuple(self._rows[0]) if self._rows else None

    def close(self):
        self._rows = []


class SnowparkConnection:
    def __init__(self, session):
        self.session = session

    def cursor(self):
        return SnowparkCursor(self.session)


def load_procedure(session, payload, database='CLOUDLEDGER', schema='CLOUD_FINANCE_BI'):
    """Stored-procedure handler: keep the raw payload, load via load_snapshot,
    and record any failure without touching the published snapshot."""
    from .data import from_cost_explorer
    from .snowflake_backend import identifier, load_snapshot
    prefix = identifier(database) + '.' + identifier(schema)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    try:
        session.sql(f'INSERT INTO {prefix}.RAW_COST_EXPLORER (PAYLOAD_SHA256, PAYLOAD) '
                    'SELECT ?, PARSE_JSON(?)', params=[digest, payload]).collect()
        rows = from_cost_explorer(json.loads(payload))
        result = load_snapshot(SnowparkConnection(session), rows, database, schema)
        result['payload_sha256'] = digest
        return json.dumps(result)
    except Exception as exc:
        session.sql(f'INSERT INTO {prefix}.LOAD_FAILURES (PAYLOAD_SHA256, ERROR_MESSAGE) '
                    'VALUES (?, ?)', params=[digest, f'{type(exc).__name__}: {exc}'[:4000]]).collect()
        raise


def procedure_handler(session, payload):
    """Handler for LOAD_COST_EXPLORER_SNAPSHOT(PAYLOAD VARCHAR); Snowflake requires
    the handler signature to match the procedure arguments exactly."""
    return load_procedure(session, payload)
