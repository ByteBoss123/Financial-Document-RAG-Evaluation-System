"""Recompute published evaluation summaries from source and live-response fixtures."""
import json
from pathlib import Path
from cloud_finance.data import demo
from cloud_finance.analytics import anomalies
from cloud_finance.workflow import parse_response,execute

root=Path(__file__).parent
rows=demo()
truth={(r['day'],r['service']) for r in rows if r['injected'] and r['day']>='2026-05-01'}
pred={(r['day'],r['service']) for r in anomalies(rows,'2026-05-01','2026-09-30')}
expected=[{'variance','drivers','anomalies','forecast'},{'variance'},{'drivers'},{'anomalies','forecast'},{'anomalies'},{'forecast'}]
results={}
report=json.loads((root/'results/analysis.json').read_text())
for version in (1,2):
    cases=json.loads((root/f'results/planner_v{version}_live.json').read_text())['cases']
    details=[]
    for c,want in zip(cases,expected):
        try:
            plan=parse_response(c['response'])
            output=execute(report,plan)
            details.append({'question':c['question'],'valid':True,'exact_tools':set(plan['steps'])==want,'executed_tools':[t['tool'] for t in output['trace']]})
        except (ValueError,KeyError,TypeError):
            details.append({'question':c['question'],'valid':False,'exact_tools':False,'executed_tools':[]})
    results[f'planner_v{version}']={'valid':sum(c['valid'] for c in details),'exact_tools':sum(c['exact_tools'] for c in details),'cases':len(details),'details':details}
summary={'data':'synthetic, seeded, not production performance',
         'anomalies':{'true_positives':len(truth&pred),'false_positives':len(pred-truth),'false_negatives':len(truth-pred)},
         'planner':results,
         'limitations':'Six development prompts reused after prompt revision; not an independent generalization benchmark. Anomaly labels are injected spikes, not real waste.'}
(root/'results/evaluation.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
