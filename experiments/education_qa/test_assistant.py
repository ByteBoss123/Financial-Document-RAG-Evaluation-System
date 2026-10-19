import unittest
from assistant import Assistant, load_assistant
from evaluate import evaluate

class BehavioralTests(unittest.TestCase):
    def test_unknown_and_empty_queries_decline(self):
        for q in ('', 'the and of', 'xylophone nebula'):
            self.assertTrue(load_assistant().ask(q, 0)['abstained'])

    def test_citation_points_to_exact_source(self):
        model = load_assistant()
        response = model.ask('What is precision?', 0)
        source = next(d for d in model.documents if d['id'] == response['citation'])
        self.assertEqual(response['citation'], 'precision')
        self.assertEqual(response['answer'], source['text'])

    def test_abstention_has_no_citation(self):
        response = load_assistant().ask('What is precision?', 1)
        self.assertTrue(response['abstained'])
        self.assertIsNone(response['citation'])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError): Assistant([])
        with self.assertRaises(ValueError): load_assistant().ask('precision', -1)

    def test_metrics_do_not_reward_answering_unanswerable(self):
        rows = [('What is precision?', 'precision'), ('What is my precision grade?', None)]
        m = evaluate(load_assistant(), rows, 0)['metrics']
        self.assertEqual(m['coverage'], 1)
        self.assertEqual(m['unanswerable_false_answer_rate'], 1)
        self.assertEqual(m['decision_accuracy'], 0.5)

if __name__ == '__main__': unittest.main()
