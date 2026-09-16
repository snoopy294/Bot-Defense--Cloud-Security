from __future__ import annotations

import json
import hashlib
import time


def log_request(
    *,
    route: str,
    method: str,
    status: int,
    start_time: float,
    session_id: str | None,
    product_id: str | None,
    outcome: str,
    request_id: str | None,
) -> None:
    print(json.dumps({
        "ts": time.time(),
        "request_id": request_id,
        "session_id": hashlib.sha256(session_id.encode()).hexdigest() if session_id else None,
        "route": route,
        "method": method,
        "status": status,
        "latency_ms": round((time.time() - start_time) * 1000, 2),
        "product_id": product_id,
        "outcome": outcome,
    }))
