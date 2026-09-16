import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adversary.generate import NoRedirect, generate, validate_target


class GeneratorTests(unittest.TestCase):
    def test_fixture_repeats_exactly_without_network(self):
        with tempfile.TemporaryDirectory() as temp, patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network")):
            a, b = Path(temp) / "a", Path(temp) / "b"
            generate(a, fixture=True, seed=7)
            generate(b, fixture=True, seed=7)
            for name in ("manifest.json", "labels.jsonl", "requests.jsonl"):
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            requests = [json.loads(line) for line in (a / "requests.jsonl").read_text().splitlines()]
            self.assertTrue(requests)
            self.assertTrue(all("label" not in r and "scenario" not in r and "cookie" not in r for r in requests))

    def test_request_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = generate(Path(temp), fixture=True, max_requests=3)
            self.assertEqual(manifest["request_count"], 3)
            self.assertEqual(manifest["stop_reason"], "request_limit")

    def test_live_target_must_be_explicit_exact_https_origin(self):
        self.assertEqual(validate_target("https://lab.example/", "lab.example", True), "https://lab.example")
        for url, host, ack in [
            ("https://lab.example", "lab.example", False),
            ("https://other.example", "lab.example", True),
            ("http://lab.example", "lab.example", True),
            ("https://user:secret@lab.example", "lab.example", True),
            ("https://lab.example/path", "lab.example", True),
            ("https://lab.example?token=secret", "lab.example", True),
            ("https://lab.example:444", "lab.example", True),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_target(url, host, ack)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_bounds_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                generate(Path(temp), fixture=True, rate=100)
            generate(Path(temp), fixture=True)
            with self.assertRaises(ValueError):
                generate(Path(temp), fixture=True)


if __name__ == "__main__":
    unittest.main()
