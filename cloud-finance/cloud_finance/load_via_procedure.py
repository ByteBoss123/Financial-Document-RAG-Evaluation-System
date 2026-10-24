"""Submit a private Cost Explorer export to LOAD_COST_EXPLORER_SNAPSHOT with a bound
parameter, then refresh reporting. Credentials come from a named connection."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--connection', required=True)
    p.add_argument('--aws-json', type=Path, default=Path('private/cost-explorer.json'))
    p.add_argument('--prefix', default='CLOUDLEDGER.CLOUD_FINANCE_BI')
    a = p.parse_args()
    import snowflake.connector
    payload = json.dumps(json.loads(a.aws_json.read_text()), separators=(',', ':'))
    with snowflake.connector.connect(connection_name=a.connection) as con:
        cur = con.cursor()
        cur.execute(f'CALL {a.prefix}.LOAD_COST_EXPLORER_SNAPSHOT(%s)', (payload,))
        print(cur.fetchone()[0])
        cur.execute(f"CALL {a.prefix}.REFRESH_REPORTING(FALSE, 'cli')")
        print(cur.fetchone()[0])


if __name__ == '__main__':
    main()
