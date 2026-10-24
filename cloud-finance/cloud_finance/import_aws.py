"""Read-only CE importer. Excludes current day; stores private output locally."""
import argparse
from datetime import date
import json
from pathlib import Path

def main():
    import boto3
    from botocore.config import Config
    p=argparse.ArgumentParser()
    p.add_argument('--start',required=True)
    p.add_argument('--end',default=date.today().isoformat(),help='Exclusive end date')
    p.add_argument('--out',type=Path,default=Path('private/cost-explorer.json'))
    a=p.parse_args()
    if not date.fromisoformat(a.start)<date.fromisoformat(a.end)<=date.today():
        raise ValueError('Require start < end <= today')
    client=boto3.client('ce',region_name='us-east-1',config=Config(connect_timeout=5,read_timeout=60,retries={'mode':'adaptive','total_max_attempts':3}))
    result={'GroupDefinitions':[{'Type':'DIMENSION','Key':'SERVICE'}],'ResultsByTime':[]}
    for page in client.get_paginator('get_cost_and_usage').paginate(TimePeriod={'Start':a.start,'End':a.end},Granularity='DAILY',Metrics=['UnblendedCost'],GroupBy=result['GroupDefinitions']):
        result['ResultsByTime'].extend(page['ResultsByTime'])
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2))
    a.out.chmod(0o600)
    print('Saved private billing export; charges may be estimated and revised by AWS.')

if __name__=='__main__':
    main()
