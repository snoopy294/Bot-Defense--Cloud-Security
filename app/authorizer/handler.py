from __future__ import annotations

import os
import re
import time
import uuid
import hmac
from http.cookies import SimpleCookie, CookieError

import boto3

from common.logging import log_request

SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SESSION_TTL_SECONDS = 3600


def _table():
    return boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])


def _extract_session_id(event: dict) -> str | None:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    for cookie in event.get("cookies") or [headers.get("cookie", "")]:
        parsed = SimpleCookie()
        try:
            parsed.load(cookie)
        except CookieError:
            continue
        if "session_id" in parsed:
            return parsed["session_id"].value
    return None


def handler(event: dict, context) -> dict:
    start = time.time()
    origin_secret = os.environ.get("ORIGIN_SECRET")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if origin_secret is not None and (not origin_secret or not hmac.compare_digest(
            headers.get("x-origin-verify", "").encode(), origin_secret.encode())):
        return {"isAuthorized": False}
    session_id = _extract_session_id(event)
    request_id = event.get("requestContext", {}).get("requestId")

    if session_id is not None and not SESSION_ID_RE.fullmatch(session_id):
        log_request(route="authorizer", method="AUTH", status=401, start_time=start,
                    session_id=session_id, product_id=None, outcome="invalid_session",
                    request_id=request_id)
        return {"isAuthorized": False}

    table = _table()
    now = int(time.time())

    if session_id is not None:
        existing = table.get_item(Key={"session_id": session_id}, ConsistentRead=True).get("Item")
        if existing is not None and int(existing["ttl"]) > now:
            table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET request_count = request_count + :one",
                ExpressionAttributeValues={":one": 1},
            )
            log_request(route="authorizer", method="AUTH", status=200, start_time=start,
                        session_id=session_id, product_id=None, outcome="existing_session",
                        request_id=request_id)
            return {
                "isAuthorized": True,
                "context": {"session_id": session_id, "is_new_session": "false"},
            }

    session_id = str(uuid.uuid4())
    table.put_item(Item={
        "session_id": session_id,
        "created_at": now,
        "ttl": now + SESSION_TTL_SECONDS,
        "request_count": 1,
    })
    log_request(route="authorizer", method="AUTH", status=200, start_time=start,
                session_id=session_id, product_id=None, outcome="new_session",
                request_id=request_id)
    return {
        "isAuthorized": True,
        "context": {"session_id": session_id, "is_new_session": "true"},
    }
