import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import evalgate
from normalizer import normalize_order

ROOT = Path(__file__).resolve().parent


def cases(value, **metadata):
    return {"one": {"id": "one", "value": value, **metadata}}


class GateTests(unittest.TestCase):
    def test_nested_exact_pass(self):
        value = {"rows": [1, "one", None, True, {"x": 2.5}]}
        self.assertTrue(evalgate.evaluate(cases(value), cases(copy.deepcopy(value)))["passed"])

    def test_numeric_tolerance(self):
        self.assertTrue(evalgate.evaluate(cases(100), cases(100.5), relative=.01)["passed"])
        self.assertFalse(evalgate.evaluate(cases(100), cases(102), relative=.01)["passed"])
        self.assertTrue(evalgate.evaluate(cases(0), cases(.001), absolute=.002)["passed"])

    def test_boolean_is_not_number(self):
        self.assertFalse(evalgate.evaluate(cases(True), cases(1))["passed"])

    def test_large_integers_do_not_lose_precision(self):
        self.assertFalse(evalgate.evaluate(cases(2**80), cases(2**80 + 1))["passed"])

    def test_missing_case_and_unexpected_case_fail(self):
        actual = {"two": {"id": "two", "value": 1}}
        report = evalgate.evaluate(cases(1), actual)
        self.assertEqual(report["functional"]["counts"], {"pass": 0, "fail": 0, "missing": 1, "unexpected": 1})

    def test_exact_object_keys_and_array_length(self):
        self.assertFalse(evalgate.evaluate(cases({"x": None}), cases({}))["passed"])
        self.assertFalse(evalgate.evaluate(cases([1]), cases([1, 2]))["passed"])

    def test_json_pointer_escaping(self):
        result = evalgate.differences({"a~/b": 1}, {"a~/b": 2}, 0, 0)
        self.assertEqual(result[0]["path"], "/a~0~1b")

    def test_bounded_diagnostics(self):
        result = evalgate.differences(list(range(100)), [-1] * 100, 0, 0)
        self.assertEqual(len(result), 20)

    def test_latency_limit_requires_measurement(self):
        self.assertFalse(evalgate.evaluate(cases(1), cases(1), max_duration_ms=5)["passed"])
        self.assertFalse(evalgate.evaluate(cases(1), cases(1, duration_ms=6), max_duration_ms=5)["passed"])
        self.assertTrue(evalgate.evaluate(cases(1), cases(1, duration_ms=5), max_duration_ms=5)["passed"])

    def test_functional_digest_excludes_latency_without_a_gate(self):
        left = evalgate.evaluate(cases(1), cases(1, duration_ms=.1))
        right = evalgate.evaluate(cases(1), cases(1, duration_ms=20))
        self.assertEqual(left["functional_sha256"], right["functional_sha256"])
        self.assertNotEqual(left["latency"], right["latency"])

    def test_order_independent_hash(self):
        rows = {"b": {"id": "b", "value": 2}, "a": {"id": "a", "value": 1}}
        reverse = dict(reversed(list(rows.items())))
        self.assertEqual(evalgate.evaluate(rows, rows)["functional_sha256"], evalgate.evaluate(reverse, reverse)["functional_sha256"])

    def test_nonfinite_and_negative_configuration(self):
        for value in (float("nan"), float("inf"), -1):
            with self.subTest(value=value), self.assertRaises(evalgate.InputError):
                evalgate.evaluate(cases(1), cases(1), absolute=value)

    def test_percentile_interpolation_and_empty(self):
        self.assertIsNone(evalgate.percentile([], .5))
        self.assertEqual(evalgate.percentile([1, 3], .5), 2)


class InputTests(unittest.TestCase):
    def load(self, content, role="reference"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rows.jsonl"
            path.write_bytes(content)
            return evalgate.load_cases(path, role)

    def test_valid_utf8_jsonl(self):
        self.assertEqual(self.load('{"id":"café","value":"été"}\n'.encode())["café"]["value"], "été")

    def test_duplicate_ids(self):
        with self.assertRaises(evalgate.InputError):
            self.load(b'{"id":"a","value":1}\n{"id":"a","value":2}\n')

    def test_duplicate_object_keys(self):
        with self.assertRaises(evalgate.InputError):
            self.load(b'{"id":"a","value":{"x":1,"x":2}}\n')

    def test_non_finite_or_overflow_json(self):
        for token in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(token=token), self.assertRaises(evalgate.InputError):
                self.load(('{"id":"a","value":' + token + '}\n').encode())

    def test_malformed_utf8_and_json(self):
        for content in (b'\xff\n', b'not json\n'):
            with self.subTest(content=content), self.assertRaises(evalgate.InputError):
                self.load(content)

    def test_empty_or_blank_input(self):
        for content in (b'', b'\n'):
            with self.subTest(content=content), self.assertRaises(evalgate.InputError):
                self.load(content)

    def test_schema_enforced(self):
        for row in ([1], {"id": "a"}, {"id": 1, "value": 1}, {"id": "", "value": 1}, {"id": "a", "value": 1, "extra": 1}):
            with self.subTest(row=row), self.assertRaises(evalgate.InputError):
                self.load((json.dumps(row) + '\n').encode())

    def test_duration_schema(self):
        for duration in (True, -1, "1", 86400001):
            with self.subTest(duration=duration), self.assertRaises(evalgate.InputError):
                self.load((json.dumps({"id": "a", "value": 1, "duration_ms": duration}) + '\n').encode(), "observed")

    def test_depth_limit(self):
        value = 0
        for _ in range(40):
            value = [value]
        with self.assertRaises(evalgate.InputError):
            self.load((json.dumps({"id": "a", "value": value}) + '\n').encode())

    def test_line_and_file_size_limits(self):
        with patch.object(evalgate, "MAX_LINE", 10), self.assertRaises(evalgate.InputError):
            self.load(b'{"id":"a","value":1}\n')
        with patch.object(evalgate, "MAX_INPUT_BYTES", 10), self.assertRaises(evalgate.InputError):
            self.load(b'{"id":"a","value":1}\n')

    def test_case_count_limit(self):
        with patch.object(evalgate, "MAX_CASES", 1), self.assertRaises(evalgate.InputError):
            self.load(b'{"id":"a","value":1}\n{"id":"b","value":2}\n')


class NormalizerTests(unittest.TestCase):
    def test_decimal_rounding_and_leap_day(self):
        row = normalize_order({"order_id": " A ", "date": "2024-02-29", "amount": "12.345", "currency": "usd"})
        self.assertEqual(row, {"order_id": "A", "date": "2024-02-29", "amount": "12.34", "currency": "USD"})

    def test_bad_dates(self):
        for value in ("2025-02-29", "20261006", "2026-2-01", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_order({"order_id": "A", "date": value, "amount": "1", "currency": "USD"})

    def test_invalid_amounts(self):
        for value in ("NaN", "Infinity", "1000000000000", " 1", "bad", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_order({"order_id": "A", "date": "2026-10-06", "amount": value, "currency": "USD"})


class IntegrationTests(unittest.TestCase):
    def test_real_sample_baseline_regression_and_repeatability(self):
        with tempfile.TemporaryDirectory() as folder:
            cmd = [sys.executable, str(ROOT / "run_sample.py"), "--output", folder]
            subprocess.run(cmd, check=True, capture_output=True, timeout=15)
            baseline = json.loads((Path(folder) / "baseline.json").read_text())
            regression = json.loads((Path(folder) / "intentional-regression.json").read_text())
            self.assertEqual(baseline["functional"]["counts"]["pass"], 6)
            self.assertEqual(regression["functional"]["counts"]["fail"], 1)
            subprocess.run(cmd, check=True, capture_output=True, timeout=15)
            second = json.loads((Path(folder) / "baseline.json").read_text())
            self.assertEqual(baseline["functional_sha256"], second["functional_sha256"])

    def test_cli_exit_codes_and_atomic_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ref, obs, report = (root / name for name in ("reference.jsonl", "observed.jsonl", "report.json"))
            ref.write_text('{"id":"a","value":1}\n')
            command = [sys.executable, str(ROOT / "evalgate.py"), "--reference", str(ref), "--observed", str(obs), "--report", str(report)]
            for content, expected in (('{"id":"a","value":1}\n', 0), ('{"id":"a","value":2}\n', 1), ('invalid\n', 2)):
                obs.write_text(content)
                result = subprocess.run(command, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)
            self.assertFalse(json.loads(report.read_text())["passed"])
            self.assertEqual(list(root.glob(".evalgate-*.tmp")), [])

    def test_cli_does_not_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reference.jsonl"
            content = '{"id":"a","value":1}\n'
            path.write_text(content)
            result = subprocess.run([sys.executable, str(ROOT / "evalgate.py"), "--reference", str(path), "--observed", str(path), "--report", str(path)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_text(), content)

    def test_failed_atomic_replace_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(evalgate.os, "replace", side_effect=OSError("injected replacement failure")), self.assertRaises(OSError):
                evalgate.atomic_json(Path(folder) / "report.json", {"ok": True})
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
