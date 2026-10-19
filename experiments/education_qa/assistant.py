"""Offline extractive educational QA baseline. Python 3.10+, standard library only."""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STOP = set('a an the is are was were how what why when where which do does can could should would i we you my to of in on for and or with it its be by as this that explain me about'.split())

def tokens(text):
    return [w for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in STOP]

class Assistant:
    def __init__(self, documents):
        if not documents or len({d['id'] for d in documents}) != len(documents):
            raise ValueError('Supply nonempty documents with unique IDs')
        self.documents = documents
        counts = [Counter(tokens(d['title'] + ' ' + d['text'])) for d in documents]
        df = Counter(w for c in counts for w in c)
        self.idf = {w: math.log((1 + len(counts)) / (1 + n)) + 1 for w, n in df.items()}
        self.vectors = [self.vector(c) for c in counts]

    def vector(self, counts):
        raw = {w: n * self.idf.get(w, 0) for w, n in counts.items()}
        norm = math.sqrt(sum(v*v for v in raw.values())) or 1
        return {w: v/norm for w, v in raw.items()}

    def ask(self, question, threshold=0.25):
        if not 0 <= threshold <= 1:
            raise ValueError('Threshold must be between zero and one')
        query = self.vector(Counter(tokens(question)))
        scores = [sum(v * doc.get(w, 0) for w, v in query.items()) for doc in self.vectors]
        index = max(range(len(scores)), key=scores.__getitem__)
        score = scores[index]
        doc = self.documents[index]
        abstained = score <= 0 or score < threshold
        return {'question': question, 'answer': 'Insufficient evidence in the supplied notes.' if abstained else doc['text'],
                'citation': None if abstained else doc['id'], 'source_title': None if abstained else doc['title'],
                'abstained': abstained, 'retrieval_score': score}

def load_assistant():
    return Assistant(json.loads((ROOT / 'course_notes.json').read_text(encoding='utf-8')))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question')
    parser.add_argument('--threshold', type=float, default=None)
    args = parser.parse_args()
    threshold = args.threshold
    if threshold is None:
        result = ROOT / 'results.json'
        threshold = json.loads(result.read_text())['selected_threshold'] if result.exists() else 0.25
    print(json.dumps(load_assistant().ask(args.question, threshold), indent=2))
