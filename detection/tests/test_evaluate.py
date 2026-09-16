import json
import tempfile
import unittest
from pathlib import Path

from adversary.generate import generate
from detection.evaluate import FEATURES, evaluate, feature_vector, load_samples, metrics, probability, split_runs


class EvaluationTests(unittest.TestCase):
    def test_end_to_end_held_out_runs_and_saved_model(self):
        with tempfile.TemporaryDirectory() as temp:
            data, output = Path(temp) / "data", Path(temp) / "report"
            generate(data, fixture=True)
            report = evaluate([data], output)
            self.assertTrue(report["synthetic"])
            self.assertFalse(set(report["train_runs"]) & set(report["test_runs"]))
            self.assertFalse(set(report["train_actor_ids"]) & set(report["test_actor_ids"]))
            self.assertGreater(report["logistic_regression"]["recall"], .5)
            self.assertLess(report["logistic_regression"]["false_positive_rate"], .5)
            model = json.loads((output / "model.json").read_text())
            samples, _ = load_samples([data])
            self.assertTrue(all(0 <= probability(model, s["x"]) <= 1 for s in samples))
            self.assertIn("SYNTHETIC FIXTURE", (output / "report.md").read_text())

    def test_feature_allowlist_ignores_ground_truth_identifiers_and_outcomes(self):
        events = [{"route": "/products", "timestamp_seconds": 1, "status": 200},
                  {"route": "/cart", "timestamp_seconds": 3, "status": 201}]
        before = feature_vector(events)
        for event in events:
            event.update(label="bot", actor_id="secret", run_id="training", scenario="rapid", status=403)
        self.assertEqual(feature_vector(events), before)
        self.assertEqual(len(before), len(FEATURES))

    def test_scaler_uses_training_only(self):
        from detection.evaluate import train_model
        samples = [{"run_id": f"r{run}", "actor_id": f"{run}-{y}", "y": y, "x": [float(y)] * 4}
                   for run in range(3) for y in range(2)]
        train, test = split_runs(samples, 42)
        model = train_model(train)
        for sample in test:
            sample["x"] = [999999.0] * 4
        self.assertEqual(train_model(train), model)
        self.assertEqual(model["means"], [.5] * 4)

    def test_overlap_and_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            generate(data, fixture=True)
            with self.assertRaisesRegex(ValueError, "overlapping"):
                load_samples([data, data])
            # A malformed dataset must not silently produce attractive metrics.
            with (data / "requests.jsonl").open("a") as stream:
                stream.write("{}\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_samples([data])

    def test_missing_classes_and_entity_overlap_rejected(self):
        with self.assertRaises(ValueError):
            split_runs([{"run_id": "one", "actor_id": "a", "y": 0}], 1)
        with self.assertRaisesRegex(ValueError, "actor overlap"):
            split_runs([{"run_id": run, "actor_id": "same", "y": 0} for run in ("a", "b")], 1)

    def test_metrics_confusion_counts(self):
        result = metrics([0, 0, 1, 1], [0, 1, 0, 1])
        self.assertEqual(result["precision"], .5)
        self.assertEqual(result["recall"], .5)
        self.assertEqual(result["false_positive_rate"], .5)


if __name__ == "__main__":
    unittest.main()
