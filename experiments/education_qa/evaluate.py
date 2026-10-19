"""Select threshold on development data, then report both policies on test data."""
import hashlib
import json
from assistant import ROOT, load_assistant


def evaluate(model, rows, threshold):
    predictions = []
    for question, gold in rows:
        result = model.ask(question, threshold)
        result.update(gold_citation=gold, correct=result['citation'] == gold)
        predictions.append(result)
    answered = [r for r in predictions if not r['abstained']]
    unanswerable = [r for r in predictions if r['gold_citation'] is None]
    answerable = [r for r in predictions if r['gold_citation'] is not None]
    ratio = lambda numerator, denominator: numerator / denominator if denominator else None
    metrics = {
        'n': len(rows),
        'decision_accuracy': ratio(sum(r['correct'] for r in predictions), len(rows)),
        'coverage': ratio(len(answered), len(rows)),
        'citation_accuracy_when_answered': ratio(sum(r['correct'] for r in answered), len(answered)),
        'unanswerable_false_answer_rate': ratio(sum(not r['abstained'] for r in unanswerable), len(unanswerable)),
        'answerable_correct_response_rate': ratio(sum(r['correct'] for r in answerable), len(answerable)),
    }
    return {'metrics': metrics, 'predictions': predictions}


def main():
    data = json.loads((ROOT / 'benchmark.json').read_text())
    assert not ({q for q, _ in data['dev']} & {q for q, _ in data['test']}), 'Split overlap'
    model = load_assistant()
    for split in ('dev', 'test'):
        assert all(g is None or g in {d['id'] for d in model.documents} for _, g in data[split])
    grid = [i/20 for i in range(21)]
    sweep = [{'threshold': t, **evaluate(model, data['dev'], t)['metrics']} for t in grid]
    # Maximize dev decision accuracy; prefer greater coverage, then lower threshold.
    selected = max(sweep, key=lambda r: (r['decision_accuracy'], r['coverage'], -r['threshold']))['threshold']
    report = {'selected_threshold': selected, 'selection': 'Development decision accuracy, ties by coverage then lower threshold',
              'provenance': data['provenance'],
              'sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                         for name in ('course_notes.json', 'benchmark.json', 'assistant.py', 'evaluate.py')},
              'development_sweep': sweep,
              'test_always_retrieve': evaluate(model, data['test'], 0),
              'test_selective': evaluate(model, data['test'], selected)}
    (ROOT/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v['metrics'] for k,v in report.items() if k.startswith('test_')}, indent=2))
    print('Selected threshold:', selected)

if __name__ == '__main__':
    main()
