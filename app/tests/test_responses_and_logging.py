from __future__ import annotations

import json

from common.responses import json_response
from common.logging import log_request


def test_json_response_shape():
    result = json_response(201, {"reservation_id": "abc"})
    assert result["statusCode"] == 201
    assert result["headers"]["Content-Type"] == "application/json"
    assert json.loads(result["body"]) == {"reservation_id": "abc"}


def test_log_request_emits_expected_fields(capsys):
    log_request(
        route="POST /cart",
        method="POST",
        status=201,
        start_time=0.0,
        session_id="sess-1",
        product_id="prod-1",
        outcome="reserved",
    )
    line = json.loads(capsys.readouterr().out.strip())
    assert set(line.keys()) == {
        "ts", "session_id", "route", "method", "status",
        "latency_ms", "product_id", "outcome",
    }
    assert line["route"] == "POST /cart"
    assert line["outcome"] == "reserved"
