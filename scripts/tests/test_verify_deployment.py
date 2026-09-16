from argparse import Namespace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.verify_deployment import partition_filter, query_count, verify


def options(**kwargs):
    values = dict(edge="https://edge.example", origin="https://origin.example",
                  acknowledge_owned_target=True, reset=False, seed_file=None,
                  timeout=30, product_id="test", database="test", workgroup="test", region="us-east-1")
    values.update(kwargs)
    return Namespace(**values)


class Session:
    def __init__(self, origin_status=403):
        self.headers = {}
        self.cookies = []
        self.calls = []
        self.origin_status = origin_status

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 15
        body = {}
        status = 200
        if "origin.example" in url:
            status = self.origin_status
        elif "/products/verification-" in url:
            status = 404
        elif url.endswith("/products"):
            self.cookies.append(SimpleNamespace(name="session_id", secure=True))
        elif url.endswith("/cart"):
            status = 201
            body = {"reservation_id": "reservation"}
        elif url.endswith("/checkout"):
            body = {"order_id": "same-order"}
        return SimpleNamespace(status_code=status, headers={"apigw-requestid": "probe-request"}, json=lambda: body)


class Athena:
    def __init__(self):
        self.queries = []

    def start_query_execution(self, **kwargs):
        self.queries.append(kwargs["QueryString"])
        return {"QueryExecutionId": "query"}

    def get_query_execution(self, **kwargs):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, **kwargs):
        return {"ResultSet": {"Rows": [{"Data": []}, {"Data": [{"VarCharValue": "1"}]}]}}


def test_complete_smoke_requires_all_three_telemetry_sources():
    session, athena = Session(), Athena()
    report = verify(options(), session, athena)
    assert report["status"] == "passed"
    assert report["checks"]["telemetry"] == {"app_logs": 1, "apigw_logs": 1, "waf_logs": 1}
    assert len(athena.queries) == 3
    assert all("year=" in query for query in athena.queries)
    assert sum(url.endswith("/checkout") for url in session.calls) == 2


def test_origin_bypass_fails_before_shopping():
    session = Session(origin_status=200)
    with pytest.raises(RuntimeError, match="unexpected HTTP 200"):
        verify(options(), session, Athena())
    assert len(session.calls) == 1


@pytest.mark.parametrize("overrides", [
    {"acknowledge_owned_target": False}, {"reset": True},
    {"edge": "https://user:secret@edge.example"}, {"timeout": 10000},
])
def test_invalid_options_never_send_requests(overrides):
    session = Session()
    with pytest.raises(ValueError):
        verify(options(**overrides), session, Athena())
    assert not session.calls


def test_query_failure_does_not_claim_telemetry_success():
    class Failed(Athena):
        def get_query_execution(self, **kwargs):
            return {"QueryExecution": {"Status": {"State": "FAILED"}}}
    with pytest.raises(RuntimeError, match="failed"):
        verify(options(), Session(), Failed())


def test_partition_filter_spans_midnight():
    start = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, 0, 1, tzinfo=timezone.utc)
    value = partition_filter(start, end)
    assert "year='2026' AND month='12' AND day='31'" in value
    assert "year='2027' AND month='01' AND day='01'" in value
