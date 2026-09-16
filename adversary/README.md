# Owned-target traffic experiments

Python 3.10+; standard library only. Run commands from the repository root.

## Offline smoke test

```powershell
python -m adversary.generate --fixture --output adversary/runs/fixture --seed 42
python -m detection.evaluate --input adversary/runs/fixture --output detection/reports/fixture
python -m unittest discover -s adversary/tests -v
python -m unittest discover -s detection/tests -v
```

The default fixture contains four runs of six actors, alternating scripted human browsing
and rapid bot polling. All fixture responses and outcomes are **synthetic**. Identical arguments
produce identical files; no requests leave the process. Use a fresh output directory each time.

## Live owned-app experiment

Seed the owned app with a live, stocked product using its admin runbook first. This command
creates real reservations and orders in that lab, consuming stock. It does not reset inventory.

```powershell
python -m adversary.generate --target https://YOUR-DISTRIBUTION.cloudfront.net --allow-host YOUR-DISTRIBUTION.cloudfront.net --acknowledge-owned-target --output adversary/runs/live-01 --runs 4 --sessions-per-run 6 --max-requests 400 --rate 2 --timeout 10 --max-seconds 300
python -m detection.evaluate --input adversary/runs/live-01 --output detection/reports/live-01
```

The target must be an HTTPS origin whose hostname exactly matches `--allow-host`. Ownership
is explicitly acknowledged by the operator; this is not an ownership-verification service.
Redirects are refused. Each actor uses its own in-memory cookie jar, retaining the app's
server-minted session cookie across catalog, cart, and checkout. Cookies and response bodies
are never written to the dataset. Both classes use the same User-Agent. There is no browser
evasion, proxy rotation, or third-party retailer adapter in this generator.

Requests are sequential, with at most ten starts per second, 2,000 requests, a 30-second socket
timeout, and an 1,800-second run budget. Defaults are smaller. The run deadline prevents starting
additional requests; an in-flight response can take up to its timeout. Responses are capped at
1 MB. A failed catalog request or empty catalog skips that actor's purchase; a failed cart skips
checkout. No automatic retry amplifies rejected traffic. Inspect `stop_reason` and class counts;
a budget-truncated experiment may need more runs before it can be evaluated.

## Dataset contract

- `manifest.json`: schema version, synthetic flag, seed, independent experiment ID, bounds,
  counts, stop reason, and SHA-256 checksums for both JSONL files.
- `requests.jsonl`: run ID, noncredential actor ID, method, route, relative timestamp, latency,
  HTTP status (`0` means transport failure), and API request ID when available.
- `labels.jsonl`: independent actor/run ground truth (`human` or `bot`) and scripted scenario.

Live experiment/actor IDs are unique even when the random seed repeats. Fixture IDs are
deterministic. Run IDs are sent as `X-Lab-Run-Id`; labels are never sent. API response request
IDs can support subsequent server-log correlation. These files are client observations, not
an implemented Athena/WAF log ingestion pipeline. Generated runs are ignored by Git.
