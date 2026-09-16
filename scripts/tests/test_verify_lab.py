from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.verify_lab import verify


def outputs(endpoint='https://abc.execute-api.us-east-1.amazonaws.com'):
    return {'app_api_endpoint': {'value': endpoint},
            'products_table_name': {'value': 'botdef-products'},
            'access_log_group_name': {'value': '/botdef/app/access-logs'}}


def clients(monkeypatch, same_order=True, logged=True):
    monkeypatch.setattr('scripts.verify_lab.time.sleep', lambda _: None)
    aws, http = Mock(), Mock()
    http.cookies = [SimpleNamespace(name='session_id', secure=True)]
    http.request.side_effect = [
        Mock(status_code=200),
        Mock(status_code=201, json=lambda: {'reservation_id': 'reservation'}),
        Mock(status_code=200, json=lambda: {'order_id': 'order'}),
        Mock(status_code=200, json=lambda: {'order_id': 'order' if same_order else 'duplicate'}),
        Mock(status_code=404, headers={'apigw-requestid': 'request'}),
    ]
    aws.client.return_value.filter_log_events.return_value = {'events': [{}] if logged else []}
    return aws, http


def test_lab_proves_checkout_retry_and_correlated_log(monkeypatch):
    aws, http = clients(monkeypatch)
    report = verify(outputs(), aws, http)
    assert report['status'] == 'passed'
    assert report['checks']['cloudwatch_access_log']
    assert aws.resource.return_value.Table.return_value.put_item.call_args.kwargs['ConditionExpression'] == 'attribute_not_exists(product_id)'
    assert aws.client.return_value.filter_log_events.call_args.kwargs['filterPattern'] == '"request"'
    assert all(call.kwargs['allow_redirects'] is False for call in http.request.call_args_list)


def test_duplicate_order_fails_verification(monkeypatch):
    aws, http = clients(monkeypatch, same_order=False)
    with pytest.raises(RuntimeError, match='same order'):
        verify(outputs(), aws, http)


@pytest.mark.parametrize('endpoint', ['http://abc.execute-api.us-east-1.amazonaws.com',
                                     'https://retailer.example',
                                     'https://abc.execute-api.us-east-1.amazonaws.com/path'])
def test_unexpected_target_never_seeds_or_requests(endpoint):
    aws, http = Mock(), Mock()
    with pytest.raises(ValueError):
        verify(outputs(endpoint), aws, http)
    aws.resource.assert_not_called()
    http.request.assert_not_called()


def test_missing_telemetry_fails(monkeypatch):
    aws, http = clients(monkeypatch, logged=False)
    monkeypatch.setattr('scripts.verify_lab.time.monotonic', Mock(side_effect=[0, 0, 0, 2]))
    with pytest.raises(TimeoutError):
        verify(outputs(), aws, http, timeout=1)
