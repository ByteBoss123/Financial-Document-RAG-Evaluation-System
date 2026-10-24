"""Snowflake snapshot loader. No embedded credentials; dedicated schema only."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
from .data import from_cost_explorer, validate, fingerprint

def identifier(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('Use simple unquoted Snowflake identifiers')
    return value.upper()

def setup(cursor,database,schema):
    prefix=identifier(database)+'.'+identifier(schema)
    cursor.execute(f'CREATE SCHEMA IF NOT EXISTS {prefix}')
    cursor.execute(f'''CREATE TABLE IF NOT EXISTS {prefix}.COST_DAILY (
      USAGE_DATE DATE NOT NULL, ACCOUNT_KEY VARCHAR NOT NULL, SERVICE VARCHAR NOT NULL,
      TEAM VARCHAR NOT NULL, UNBLENDED_COST NUMBER(28,10) NOT NULL,
      CURRENCY VARCHAR NOT NULL, ESTIMATED BOOLEAN NOT NULL, SOURCE_SNAPSHOT VARCHAR NOT NULL)''')
    cursor.execute(f'''CREATE TABLE IF NOT EXISTS {prefix}.LOAD_AUDIT (
      SOURCE_SNAPSHOT VARCHAR, LOADED_AT TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
      ROW_COUNT NUMBER, SOURCE_TOTAL NUMBER(28,10), START_DATE DATE, END_DATE DATE)''')
    cursor.execute(f'''CREATE OR REPLACE VIEW {prefix}.DAILY_COST AS
      SELECT USAGE_DATE,SUM(UNBLENDED_COST) ACTUAL_COST,BOOLOR_AGG(ESTIMATED) HAS_ESTIMATES
      FROM {prefix}.COST_DAILY GROUP BY 1''')
    cursor.execute(f'''CREATE OR REPLACE VIEW {prefix}.MONTHLY_SERVICE_TEAM_COST AS
      SELECT DATE_TRUNC('MONTH',USAGE_DATE) USAGE_MONTH,SERVICE,TEAM,CURRENCY,
      SUM(UNBLENDED_COST) ACTUAL_COST,BOOLOR_AGG(ESTIMATED) HAS_ESTIMATES
      FROM {prefix}.COST_DAILY GROUP BY 1,2,3,4''')
    return prefix

def load_snapshot(connection,rows,database,schema):
    validate(rows)
    if {r['source'] for r in rows}!={'aws-cost-explorer'}:
        raise ValueError('Real AWS records required for the Snowflake production-data loader')
    expected=sum(Decimal(r['amount']) for r in rows)
    digest=fingerprint(rows)
    cursor=connection.cursor()
    try:
        prefix=setup(cursor,database,schema)
        # Stage DDL happens BEFORE BEGIN; Snowflake DDL implicitly commits.
        cursor.execute(f'CREATE TEMP TABLE {prefix}.COST_STAGE LIKE {prefix}.COST_DAILY')
        insert=f'INSERT INTO {prefix}.COST_STAGE VALUES (%s,%s,%s,%s,%s,%s,%s,%s)'
        values=[(r['day'],r['account'],r['service'],r['team'],Decimal(r['amount']),r['currency'],r['estimated'],digest) for r in rows]
        cursor.executemany(insert,values)
        cursor.execute(f'SELECT COUNT(*),SUM(UNBLENDED_COST) FROM {prefix}.COST_STAGE')
        count,total=cursor.fetchone()
        if count!=len(rows) or Decimal(total)!=expected:
            raise ValueError('Snowflake staging reconciliation failed')
        cursor.execute(f'''SELECT COUNT(*) FROM (SELECT USAGE_DATE,ACCOUNT_KEY,SERVICE
          FROM {prefix}.COST_STAGE GROUP BY 1,2,3 HAVING COUNT(*)>1)''')
        if cursor.fetchone()[0]:
            raise ValueError('Duplicate Snowflake grain')
        # Full, validated snapshot replacement. Readers retain the previous committed
        # snapshot until COMMIT. Use one scheduled writer per schema.
        cursor.execute('BEGIN')
        try:
            cursor.execute(f'DELETE FROM {prefix}.COST_DAILY')
            cursor.execute(f'INSERT INTO {prefix}.COST_DAILY SELECT * FROM {prefix}.COST_STAGE')
            cursor.execute(f'''INSERT INTO {prefix}.LOAD_AUDIT
              (SOURCE_SNAPSHOT,ROW_COUNT,SOURCE_TOTAL,START_DATE,END_DATE)
              VALUES (%s,%s,%s,%s,%s)''',
              (digest,len(rows),expected,min(r['day'] for r in rows),max(r['day'] for r in rows)))
            cursor.execute('COMMIT')
        except Exception:
            cursor.execute('ROLLBACK')
            raise
        return {'rows':len(rows),'source_sha256':digest,'reconciled':True}
    finally:
        cursor.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--connection',required=True,help='Named Snowflake connector connection')
    p.add_argument('--database',required=True,help='Existing database you own')
    p.add_argument('--schema',default='CLOUD_FINANCE_BI',help='Dedicated schema; snapshot replaced on each load')
    p.add_argument('--aws-json',required=True,type=Path)
    a=p.parse_args()
    import snowflake.connector
    rows=from_cost_explorer(json.loads(a.aws_json.read_text()))
    with snowflake.connector.connect(connection_name=a.connection) as connection:
        print(json.dumps(load_snapshot(connection,rows,a.database,a.schema)))

if __name__=='__main__':
    main()
