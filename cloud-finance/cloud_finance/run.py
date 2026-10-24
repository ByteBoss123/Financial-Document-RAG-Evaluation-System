import argparse
import json
from pathlib import Path
from .data import demo,from_cost_explorer
from .analytics import analyze
from .workflow import execute
from .pipeline import publish

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--aws-json',type=Path)
    p.add_argument('--start',default='2026-07-01')
    p.add_argument('--end',default='2026-09-30')
    p.add_argument('--budget',type=float)
    p.add_argument('--out',type=Path,default=Path('results'))
    args=p.parse_args()
    rows=from_cost_explorer(json.loads(args.aws_json.read_text())) if args.aws_json else demo()
    report=analyze(rows,args.start,args.end,args.budget)
    review=execute(report)
    args.out.mkdir(parents=True,exist_ok=True)
    publish(args.out/'history.db',rows,args.start,args.end,args.budget)
    for name,content in [('analysis.json',json.dumps(report,indent=2)),('qbr.md',review['markdown']),('audit.json',json.dumps(review,indent=2))]:
        target=args.out/name
        tmp=target.with_suffix(target.suffix+'.tmp')
        tmp.write_text(content)
        tmp.replace(target)
    print(json.dumps({'rows':report['rows'],'source':report['source'],'reconciliation_units':report['reconciliation_units'],'forecast_scores':report['forecast']['scores'] if report['forecast'] else None}))

if __name__=='__main__':
    main()
