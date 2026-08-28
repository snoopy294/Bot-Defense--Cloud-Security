from __future__ import annotations

import os
import re
import time
import uuid

import boto3

SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SESSION_TTL_SECONDS = 3600


def _table():
    return boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])


def _extract_session_id(event: dict) -> str | None:
    for cookie in event.get("cookies") or []:
        name, _, value = cookie.partition("=")
        if name == "session_id":
            return value
    return None


def handler(event: dict, context) -> dict:
    session_id = _extract_session_id(event)

    if session_id is not None and not SESSION_ID_RE.match(session_id):
        return {"isAuthorized": False}

    table = _table()
    now = int(time.time())

    if session_id is not None:
        existing = table.get_item(Key={"session_id": session_id}).get("Item")
        if existing is not None:
            table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET request_count = request_count + :one",
                ExpressionAttributeValues={":one": 1},
            )
            return {
                "isAuthorized": True,
                "context": {"session_id": session_id, "is_new_session": "false"},
            }

    session_id = session_id or str(uuid.uuid4())
    table.put_item(Item={
        "session_id": session_id,
        "created_at": now,
        "ttl": now + SESSION_TTL_SECONDS,
        "request_count": 1,
    })
    return {
        "isAuthorized": True,
        "context": {"session_id": session_id, "is_new_session": "true"},
    }
