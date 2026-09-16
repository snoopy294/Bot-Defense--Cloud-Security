# Offline behavioral detection experiment

Standard-library Python logistic regression plus a fixed rule baseline. This is an offline
training/evaluation slice; real-time Lambda scoring and automatic WAF response are future work.

```powershell
python -m adversary.generate --fixture --output adversary/runs/fixture --seed 42
python -m detection.evaluate --input adversary/runs/fixture --output detection/reports/fixture
python -m unittest discover -s detection/tests -v
```

Run from the repository root. Python 3.10+ is sufficient; no ML packages or cloud credentials
are needed for the fixture. Use new directories for subsequent experiments. Multiple live
datasets can be supplied after `--input`; duplicate run/actor IDs and mixed live/synthetic data
are rejected. JSONL checksums are verified before feature extraction.

## What the model measures

One sample is one actor's complete history. The feature allowlist consists of request count,
mean inter-request interval, catalog-request fraction, and cart-request fraction. IDs, labels,
scenario names, cookies, HTTP outcomes, and checkout success are excluded from model inputs.
The baseline flags at least seven requests with at least 60% catalog requests. Logistic
regression learns standardized feature weights using full-batch gradient descent and L2
regularization. Scaling uses the training partition only; the threshold is fixed at 0.5.

Whole runs are randomly held out using a recorded seed (one third, rounded down; at least one
run). At least two runs and both classes in each partition are required. Actor overlap is
rejected. Hyperparameters are fixed before evaluation; there is no test-set tuning. More
independent runs and previously unseen scenarios are needed for a credible detection claim.

## Outputs

- `report.json`: dataset checksums, split membership, confusion counts, precision, recall,
  false-positive rate, and observed checkout success per actor for each class in the test set.
- `report.md`: compact metrics table with explicit experimental limitations.
- `model.json`: portable feature order, training-only means/scales, learned weights/bias,
  threshold, hyperparameters, and training run IDs. Load with JSON; no pickle execution.

Generated reports are ignored by Git. Synthetic fixtures test reproducibility and plumbing;
even perfect fixture scores do not prove real-world bot detection. Live outputs are
client-observed results and need correlation against WAF/application logs. The two scripted
behaviors are deliberately simple, checkout results depend on seeded stock, and this model
sees complete histories rather than detecting actors early. Collect baseline and enforced-WAF
runs, additional benign/bot strategies, and a time-held-out evaluation before publishing
defense-effectiveness claims or enabling automated blocking.
