"""Generate a reproducible fixture or bounded traffic against an owned drop app."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward cookies or traffic outside the approved origin.


def validate_target(target: str, allow_host: str, acknowledged: bool) -> str:
    parsed = urlsplit(target)
    if not acknowledged:
        raise ValueError("live traffic requires --acknowledge-owned-target")
    if (parsed.scheme != "https" or not parsed.hostname or parsed.hostname != allow_host
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port not in (None, 443)):
        raise ValueError("target must be an HTTPS origin matching --allow-host exactly")
    return target.rstrip("/")


def session_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def generate(output: Path, *, seed: int = 42, runs: int = 4, sessions: int = 6,
             fixture: bool = False, target: str = "", allow_host: str = "",
             acknowledged: bool = False, max_requests: int = 400, rate: float = 2,
             timeout: float = 10, max_seconds: float = 300) -> dict:
    if not (2 <= runs <= 20 and 2 <= sessions <= 50 and 1 <= max_requests <= 2000
            and 0 < rate <= 10 and 0 < timeout <= 30 and 0 < max_seconds <= 1800):
        raise ValueError("invalid bounds: runs 2..20, sessions 2..50, requests 1..2000, rate (0,10], timeout (0,30], seconds (0,1800]")
    if not fixture:
        target = validate_target(target, allow_host, acknowledged)
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty; use a new experiment directory")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    # Live run identity must not collide when the same seed is reused.
    experiment = f"fixture-{seed}" if fixture else str(uuid.uuid4())
    requests, labels = [], []
    started, last_request = time.monotonic(), None
    logical_time = 0.0
    opener = build_opener(NoRedirect())
    stop_reason = "completed"

    def send(run_id, session_id, method, route, payload, delay):
        nonlocal logical_time, last_request, stop_reason
        if len(requests) >= max_requests:
            stop_reason = "request_limit"
            return None
        if not fixture:
            remaining = max_seconds - (time.monotonic() - started)
            pause = max(delay, 0 if last_request is None else 1 / rate - (time.monotonic() - last_request))
            if remaining <= pause:
                stop_reason = "time_limit"
                return None
            time.sleep(pause)
            last_request = time.monotonic()
            remaining = max_seconds - (last_request - started)
            req = Request(target + route, method=method,
                          data=None if payload is None else json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "User-Agent": "botdef-owned-lab/1.0",
                                   "X-Lab-Run-Id": run_id})
            before = time.monotonic()
            status, body, request_id = 0, {}, None
            try:
                with opener.open(req, timeout=min(timeout, remaining)) as response:
                    status = response.status
                    request_id = response.headers.get("apigw-requestid") or response.headers.get("x-amzn-requestid")
                    raw = response.read(1_000_001)
                    if len(raw) <= 1_000_000:
                        try:
                            body = json.loads(raw)
                        except (ValueError, UnicodeDecodeError):
                            pass
            except HTTPError as exc:
                status = exc.code
                request_id = exc.headers.get("apigw-requestid") or exc.headers.get("x-amzn-requestid")
                exc.close()
            except (URLError, TimeoutError, OSError):
                pass
            latency = (time.monotonic() - before) * 1000
            timestamp = before - started
        else:
            logical_time += delay
            timestamp, latency = logical_time, round(rng.uniform(15, 90), 3)
            status, request_id = 200, f"synthetic-{len(requests)}"
            body = [{"product_id": "fixture-product"}]
            if route == "/cart":
                status, body = 201, {"reservation_id": "synthetic-reservation"}
            elif route == "/checkout":
                status, body = (200, {"order_id": "synthetic-order"}) if rng.random() > .15 else (409, {})
        requests.append({"run_id": run_id, "actor_id": session_id, "method": method,
                         "route": route, "timestamp_seconds": round(timestamp, 6),
                         "latency_ms": round(latency, 3), "status": status, "request_id": request_id})
        return status, body

    for run in range(runs):
        run_id = f"{experiment}-run-{run}"
        for index in range(sessions):
            if stop_reason != "completed":
                break
            kind = "human" if index % 2 == 0 else "bot"
            # Fixture sessions deterministic; live sessions unique even with a repeated seed.
            sid = session_uuid(rng) if fixture else str(uuid.uuid4())
            opener = build_opener(NoRedirect(), HTTPCookieProcessor(CookieJar()))
            first = len(requests)
            def pause():
                return rng.uniform(.8, 2.5) if kind == "human" else rng.uniform(.05, .2)
            result = send(run_id, sid, "GET", "/products", None, pause())
            product_id = None
            if result and result[0] == 200 and isinstance(result[1], list) and result[1]:
                product_id = result[1][0].get("product_id")
            # The only variable URL is from server data, encoded as one path segment.
            if product_id:
                for _ in range(rng.randint(1, 3) if kind == "human" else rng.randint(5, 9)):
                    route = f"/products/{quote(str(product_id), safe='')}" if kind == "human" else "/products"
                    if send(run_id, sid, "GET", route, None, pause()) is None:
                        break
                if stop_reason == "completed":
                    cart = send(run_id, sid, "POST", "/cart", {"product_id": product_id}, pause())
                    if cart and cart[0] == 201 and isinstance(cart[1], dict) and cart[1].get("reservation_id"):
                        send(run_id, sid, "POST", "/checkout", {"reservation_id": cart[1]["reservation_id"]}, pause())
            if len(requests) > first:
                labels.append({"run_id": run_id, "actor_id": sid, "label": kind,
                               "scenario": "browse-shop" if kind == "human" else "rapid-poll-shop"})
    write_jsonl(output / "requests.jsonl", requests)
    write_jsonl(output / "labels.jsonl", labels)
    manifest = {"schema_version": 1, "synthetic": fixture, "experiment_id": experiment,
                "seed": seed, "requested_runs": runs, "sessions_per_run": sessions,
                "request_count": len(requests), "session_count": len(labels), "stop_reason": stop_reason,
                "target": None if fixture else target,
                "limits": {"requests": max_requests, "requests_per_second": rate,
                           "timeout_seconds": timeout, "duration_seconds": max_seconds},
                "sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                           for name in ("requests.jsonl", "labels.jsonl")}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--target", default="")
    parser.add_argument("--allow-host", default="")
    parser.add_argument("--acknowledge-owned-target", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--sessions-per-run", type=int, default=6)
    parser.add_argument("--max-requests", type=int, default=400)
    parser.add_argument("--rate", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-seconds", type=float, default=300)
    args = vars(parser.parse_args())
    args["sessions"] = args.pop("sessions_per_run")
    args["acknowledged"] = args.pop("acknowledge_owned_target")
    try:
        print(json.dumps(generate(**args), indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
