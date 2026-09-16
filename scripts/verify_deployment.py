"""Explicitly invoked live smoke test: edge/origin, shopping and Athena telemetry.

Does not provision infrastructure. Checkout consumes one unit when --product-id
is supplied. Reset requires both --reset and a seed file; never log credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import requests


def validate_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("endpoint must be an HTTPS origin without credentials, path or query")
    return value.rstrip("/")


def partition_filter(start: datetime, end: datetime) -> str:
    days = []
    day = start.date()
    while day <= end.date():
        days.append(f"(year='{day:%Y}' AND month='{day:%m}' AND day='{day:%d}')")
        day += timedelta(days=1)
    return "(" + " OR ".join(days) + ")"


def query_count(client, database, workgroup, query, deadline):
    response = client.start_query_execution(
        QueryString=query, QueryExecutionContext={"Database": database}, WorkGroup=workgroup)
    query_id = response["QueryExecutionId"]
    while time.monotonic() < deadline:
        execution = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        status = execution["Status"]["State"]
        if status == "SUCCEEDED":
            rows = client.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]
            return int(rows[1]["Data"][0]["VarCharValue"])
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Athena query {query_id} {status.lower()}; inspect AWS for details")
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    client.stop_query_execution(QueryExecutionId=query_id)
    raise TimeoutError("Athena query exceeded verification deadline")


def verify(args, session=None, athena=None):
    edge = validate_endpoint(args.edge)
    origin = validate_endpoint(args.origin)
    if edge == origin:
        raise ValueError("edge and origin must be different")
    if not args.acknowledge_owned_target:
        raise ValueError("live verification requires --acknowledge-owned-target")
    if bool(args.reset) != bool(args.seed_file):
        raise ValueError("inventory reset requires both --reset and --seed-file")
    if not 30 <= args.timeout <= 900:
        raise ValueError("timeout must be between 30 and 900 seconds")
    if args.product_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.product_id):
        raise ValueError("product-id must use letters, digits, underscore or hyphen")
    seed = None
    if args.reset:
        if not os.environ.get("BOTDEF_ADMIN_TOKEN"):
            raise ValueError("set BOTDEF_ADMIN_TOKEN to reset inventory")
        seed = json.loads(Path(args.seed_file).read_text(encoding="utf-8"))
        if not isinstance(seed, dict) or not isinstance(seed.get("products"), list):
            raise ValueError("seed file must contain a products array")

    session = session or requests.Session()
    session.headers.update({"User-Agent": "botdef-verification/1.0"})
    start = datetime.now(timezone.utc)
    report = {"started_at": start.isoformat(), "checks": {}}

    def request(method, url, expected, **kwargs):
        response = session.request(method, url, timeout=15, allow_redirects=False, **kwargs)
        if response.status_code not in expected:
            raise RuntimeError(f"{method} {urlsplit(url).path}: unexpected HTTP {response.status_code}")
        return response

    request("GET", origin + "/products", {401, 403})
    report["checks"]["origin_rejected"] = True
    request("GET", edge + "/products", {200})
    if not any(cookie.name == "session_id" and cookie.secure for cookie in session.cookies):
        raise RuntimeError("edge did not issue a secure session cookie")
    report["checks"]["session_cookie"] = True
    if seed is not None:
        request("POST", edge + "/admin/reset", {200}, json=seed,
                headers={"X-Admin-Token": os.environ["BOTDEF_ADMIN_TOKEN"]})
        report["checks"]["inventory_reset"] = True
    if args.product_id:
        cart = request("POST", edge + "/cart", {201}, json={"product_id": args.product_id}).json()
        payload = {"reservation_id": cart["reservation_id"]}
        first = request("POST", edge + "/checkout", {200}, json=payload).json()
        second = request("POST", edge + "/checkout", {200}, json=payload).json()
        if first["order_id"] != second["order_id"]:
            raise RuntimeError("checkout retry created a different order")
        report["checks"]["checkout_retry"] = True

    probe = "verification-" + uuid.uuid4().hex
    path = "/products/" + probe
    response = request("GET", edge + path, {404})
    request_id = response.headers.get("apigw-requestid") or response.headers.get("x-amzn-requestid")
    if not request_id or not re.fullmatch(r"[A-Za-z0-9_+=/-]{1,256}", request_id):
        raise RuntimeError("probe response lacks a usable API Gateway request ID")
    athena = athena or boto3.client("athena", region_name=args.region)
    deadline = time.monotonic() + args.timeout
    matches = {"app_logs": 0, "apigw_logs": 0, "waf_logs": 0}
    while time.monotonic() < deadline:
        partitions = partition_filter(start, datetime.now(timezone.utc))
        for table in matches:
            if matches[table]:
                continue
            predicate = f"httprequest.uri = '{path}'" if table == "waf_logs" else f"request_id = '{request_id}'"
            matches[table] = query_count(athena, args.database, args.workgroup,
                f"SELECT count(*) FROM {table} WHERE {partitions} AND {predicate}", deadline)
        if all(matches.values()):
            report["checks"]["telemetry"] = matches
            report["status"] = "passed"
            return report
        time.sleep(min(15, max(0, deadline - time.monotonic())))
    raise TimeoutError("missing correlated telemetry: " + ", ".join(k for k, v in matches.items() if not v))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--database", default="botdef_logs_dev")
    parser.add_argument("--workgroup", default="botdef-analytics-dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--product-id")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--seed-file")
    parser.add_argument("--acknowledge-owned-target", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args)
    except Exception as error:
        # Avoid exception text from HTTP/SDK clients: it can include credentials.
        report = {"status": "failed", "error_type": type(error).__name__}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
