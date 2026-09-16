"""Compare a fixed rule and learned logistic model on completely held-out runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

FEATURES = ("request_count", "mean_interval_seconds", "catalog_fraction", "cart_fraction")


def feature_vector(events: list[dict]) -> list[float]:
    """Allowlisted behavior only: no IDs, labels, cookies, outcomes, or scenario names."""
    ordered = sorted(events, key=lambda row: row["timestamp_seconds"])
    intervals = [b["timestamp_seconds"] - a["timestamp_seconds"] for a, b in zip(ordered, ordered[1:])]
    count = len(ordered)
    if not count:
        raise ValueError("empty actor history")
    return [float(count), mean(intervals) if intervals else 0.0,
            sum(e["route"] == "/products" for e in events) / count,
            sum(e["route"] == "/cart" for e in events) / count]


def load_samples(inputs: list[Path]) -> tuple[list[dict], list[dict]]:
    samples, manifests, used_runs, used_actors = [], [], set(), set()
    for directory in inputs:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported dataset schema")
        for name in ("requests.jsonl", "labels.jsonl"):
            digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if digest != manifest.get("sha256", {}).get(name):
                raise ValueError(f"dataset checksum mismatch: {name}")
        events = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        labels = [json.loads(line) for line in (directory / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
        grouped = defaultdict(list)
        for event in events:
            grouped[(event["run_id"], event["actor_id"])].append(event)
        current_runs, current_actors, labeled = set(), set(), set()
        for label in labels:
            key = (label["run_id"], label["actor_id"])
            if key in labeled or key not in grouped or label["label"] not in ("human", "bot"):
                raise ValueError("duplicate, missing, or invalid ground truth")
            if label["actor_id"] in current_actors:
                raise ValueError("an actor may belong to only one run")
            labeled.add(key)
            current_runs.add(key[0])
            current_actors.add(key[1])
            history = grouped[key]
            samples.append({"run_id": key[0], "actor_id": key[1], "y": int(label["label"] == "bot"),
                            "x": feature_vector(history),
                            "checkout_attempted": any(e["route"] == "/checkout" for e in history),
                            "checkout_success": any(e["route"] == "/checkout" and e["status"] == 200 for e in history)})
        if set(grouped) != labeled:
            raise ValueError("request histories without ground truth")
        if used_runs & current_runs or used_actors & current_actors:
            raise ValueError("overlapping inputs: duplicate run or actor IDs")
        used_runs.update(current_runs)
        used_actors.update(current_actors)
        manifests.append(manifest)
    if len({manifest["synthetic"] for manifest in manifests}) != 1:
        raise ValueError("evaluate synthetic fixtures separately from live traffic")
    return samples, manifests


def split_runs(samples: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    runs = sorted({sample["run_id"] for sample in samples})
    if len(runs) < 2:
        raise ValueError("at least two distinct runs required")
    random.Random(seed).shuffle(runs)
    held_out = set(runs[:max(1, len(runs) // 3)])
    train = [s for s in samples if s["run_id"] not in held_out]
    test = [s for s in samples if s["run_id"] in held_out]
    if {s["actor_id"] for s in train} & {s["actor_id"] for s in test}:
        raise ValueError("actor overlap across train/test")
    if any({s["y"] for s in partition} != {0, 1} for partition in (train, test)):
        raise ValueError("both classes required in train and test; collect more complete runs")
    return train, test


def sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-max(-40, min(40, value))))


def train_model(train: list[dict]) -> dict:
    """Full-batch, L2-regularized logistic regression; scaler fit on training only."""
    means = [mean(s["x"][i] for s in train) for i in range(len(FEATURES))]
    scales = [pstdev(s["x"][i] for s in train) or 1.0 for i in range(len(FEATURES))]
    rows = [[(v - m) / sd for v, m, sd in zip(s["x"], means, scales)] for s in train]
    weights, bias = [0.0] * len(FEATURES), 0.0
    for _ in range(1000):
        errors = [sigmoid(bias + sum(w * x for w, x in zip(weights, row))) - sample["y"]
                  for row, sample in zip(rows, train)]
        bias -= .1 * mean(errors)
        weights = [w - .1 * (mean(error * row[i] for error, row in zip(errors, rows)) + .01 * w)
                   for i, w in enumerate(weights)]
    return {"algorithm": "stdlib-logistic-regression", "feature_names": list(FEATURES),
            "means": means, "scales": scales, "weights": weights, "bias": bias,
            "threshold": .5, "iterations": 1000, "learning_rate": .1, "l2": .01}


def probability(model: dict, vector: list[float]) -> float:
    return sigmoid(model["bias"] + sum(w * (v - m) / sd for w, v, m, sd in
                                      zip(model["weights"], vector, model["means"], model["scales"])))


def metrics(truth: list[int], predicted: list[int]) -> dict:
    tp = sum(y == 1 and p == 1 for y, p in zip(truth, predicted))
    fp = sum(y == 0 and p == 1 for y, p in zip(truth, predicted))
    tn = sum(y == 0 and p == 0 for y, p in zip(truth, predicted))
    fn = sum(y == 1 and p == 0 for y, p in zip(truth, predicted))
    return {"true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0}


def evaluate(inputs: list[Path], output: Path, seed: int = 42) -> dict:
    samples, manifests = load_samples(inputs)
    train, test = split_runs(samples, seed)
    model = train_model(train)
    truth = [s["y"] for s in test]
    # Predeclared baseline, never tuned using held-out labels.
    baseline = [int(s["x"][0] >= 7 and s["x"][2] >= .6) for s in test]
    learned = [int(probability(model, s["x"]) >= model["threshold"]) for s in test]
    checkout = {}
    for name, y in (("human", 0), ("bot", 1)):
        rows = [s for s in test if s["y"] == y]
        successes = sum(s["checkout_success"] for s in rows)
        checkout[name] = {"actors": len(rows), "attempted": sum(s["checkout_attempted"] for s in rows),
                          "succeeded": successes, "success_per_actor": successes / len(rows)}
    report = {"schema_version": 1, "synthetic": manifests[0]["synthetic"], "seed": seed,
              "limitations": ["Synthetic results validate plumbing, not real bot-defense efficacy." if manifests[0]["synthetic"]
                              else "Client-observed experiment; validate against server/WAF logs before drawing defense conclusions.",
                              "Only two scripted behaviors; held-out runs do not measure generalization to unseen bot strategies.",
                              "Whole-actor offline classification, not real-time scoring or automatic blocking."],
              "feature_names": list(FEATURES), "train_actors": len(train), "test_actors": len(test),
              "train_runs": sorted({s["run_id"] for s in train}),
              "test_runs": sorted({s["run_id"] for s in test}),
              "train_actor_ids": sorted(s["actor_id"] for s in train),
              "test_actor_ids": sorted(s["actor_id"] for s in test),
              "baseline": metrics(truth, baseline), "logistic_regression": metrics(truth, learned),
              "checkout_test_set": checkout,
              "datasets": [{"experiment_id": m["experiment_id"], "sha256": m["sha256"],
                            "stop_reason": m["stop_reason"]} for m in manifests]}
    if output.exists() and any(output.iterdir()):
        raise ValueError("report output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    model["training_runs"] = report["train_runs"]
    for name, data in (("report.json", report), ("model.json", model)):
        (output / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Bot-defense experiment", "", "SYNTHETIC FIXTURE" if report["synthetic"] else "LIVE CLIENT OBSERVATIONS", "",
             f"Train actors: {len(train)}; test actors: {len(test)}. Entire runs held out.", "",
             "| Detector | Precision | Recall | False-positive rate |", "|---|---:|---:|---:|"]
    for key in ("baseline", "logistic_regression"):
        item = report[key]
        lines.append(f"| {key} | {item['precision']:.3f} | {item['recall']:.3f} | {item['false_positive_rate']:.3f} |")
    lines += ["", "## Limits", ""] + [f"- {limit}" for limit in report["limitations"]]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        report = evaluate(args.input, args.output, args.seed)
        print(json.dumps({key: report[key] for key in ("synthetic", "baseline", "logistic_regression")}, indent=2))
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
