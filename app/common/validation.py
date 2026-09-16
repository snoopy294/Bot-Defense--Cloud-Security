"""Small shared HTTP payload boundary; validate before touching persistent state."""
import base64
import json
from functools import wraps

from common.responses import json_response


class InvalidRequest(ValueError):
    pass


def body_object(event):
    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        value = json.loads(body)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InvalidRequest("invalid_json") from exc
    if not isinstance(value, dict):
        raise InvalidRequest("expected_object")
    return value


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise InvalidRequest("invalid_identifier")
    return value


def endpoint(fn):
    @wraps(fn)
    def wrapped(event, context):
        try:
            result = fn(event, context)
        except InvalidRequest as exc:
            from common.logging import log_request
            import time
            log_request(route=event.get("routeKey", fn.__module__), method="POST",
                        status=400, start_time=time.time(), session_id=None,
                        product_id=None, outcome=str(exc),
                        request_id=event.get("requestContext", {}).get("requestId"))
            result = json_response(400, {"error": str(exc)})
        auth = event.get("requestContext", {}).get("authorizer", {}).get("lambda", {})
        if auth.get("is_new_session") == "true":
            result["cookies"] = [
                f"session_id={auth['session_id']}; Path=/; Max-Age=3600; Secure; HttpOnly; SameSite=Lax"
            ]
        return result
    return wrapped
