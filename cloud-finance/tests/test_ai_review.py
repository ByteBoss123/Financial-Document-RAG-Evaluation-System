from cloud_finance.ai_review import check, parse_response, evidence_queries

EV = {'E1_service_change_28d': [{'SERVICE': 'Amazon S3', 'LAST_28D_USD': 12.34, 'PRIOR_28D_USD': 2.0, 'CHANGE_USD': 10.34}]}

def test_supported_recommendation_passes():
    r = check({'text': 'Confirm why Amazon S3 rose by 10.34 USD in the last 28 days.', 'evidence_ids': ['E1_service_change_28d']}, EV)
    assert r['passed'], r

def test_fabricated_number_fails():
    r = check({'text': 'S3 rose by 99.99 USD.', 'evidence_ids': ['E1_service_change_28d']}, EV)
    assert not r['passed'] and 'numbers not in cited evidence' in r['issues'][0]

def test_uncited_or_unknown_evidence_fails():
    assert not check({'text': 'Check S3.', 'evidence_ids': []}, EV)['passed']
    assert not check({'text': 'Check S3.', 'evidence_ids': ['E9']}, EV)['passed']

def test_savings_and_actions_rejected():
    assert not check({'text': 'Delete unused S3 buckets to save money.', 'evidence_ids': ['E1_service_change_28d']}, EV)['passed']

def test_parse_rejects_bad_shapes():
    import pytest
    bad = {'output': {'message': {'content': [{'text': '{"recommendations": []}'}]}}}
    with pytest.raises(ValueError):
        parse_response(bad)

def test_queries_are_schema_qualified():
    q = evidence_queries('CLOUDLEDGER.CLOUD_FINANCE_BI')
    assert all('CLOUDLEDGER.CLOUD_FINANCE_BI.COST_DAILY' in v for v in q.values())

def test_service_names_with_digits_are_not_numbers():
    r = check({'text': 'Review Amazon EC2 and S3 usage; S3 rose by 10.34 USD over 28 days.', 'evidence_ids': ['E1_service_change_28d']}, EV)
    assert r['passed'], r
