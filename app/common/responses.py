from __future__ import annotations

import json
from typing import Any


def json_response(status: int, body: Any, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }
