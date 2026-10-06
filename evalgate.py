"""Offline JSONL regression gate. No network access or third-party dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
MAX_LINE = 1024 * 1024
MAX_CASES = 10000
MAX_DEPTH = 32
MAX_INPUT_BYTES = 32 * 1024 * 1024


class InputError(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _finite_constant(value):
    raise InputError(f"non-finite JSON number: {value}")


def _validate_value(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise InputError(f"JSON nesting exceeds {MAX_DEPTH}")
    if isinstance(value, float) and not math.isfinite(value):
        raise InputError("numeric overflow or non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _validate_value(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_value(item, depth + 1)


def load_cases(path: Path, role: str) -> dict[str, dict]:
    cases = {}
    allowed = {"id", "value"} if role == "reference" else {"id", "value", "duration_ms"}
    with path.open("rb") as stream:
        line_number = 0
        total_bytes = 0
        while True:
            raw = stream.readline(MAX_LINE + 1)
            if not raw:
                break
            line_number += 1
            total_bytes += len(raw)
            if total_bytes > MAX_INPUT_BYTES:
                raise InputError(f"{role} exceeds {MAX_INPUT_BYTES} input bytes")
            if len(raw) > MAX_LINE:
                raise InputError(f"{role} line {line_number} exceeds {MAX_LINE} bytes")
            if not raw.strip():
                raise InputError(f"{role} line {line_number} is blank")
            try:
                row = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=_finite_constant)
                _validate_value(row)
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise InputError(f"{role} line {line_number}: {exc}") from exc
            if not isinstance(row, dict) or set(row) - allowed or not {"id", "value"} <= set(row):
                raise InputError(f"{role} line {line_number}: expected id/value and permitted metadata only")
            key = row["id"]
            if not isinstance(key, str) or not key or len(key) > 256:
                raise InputError(f"{role} line {line_number}: id must be a nonempty string <=256 characters")
            if key in cases:
                raise InputError(f"{role}: duplicate case id {key!r}")
            if "duration_ms" in row:
                duration = row["duration_ms"]
                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 <= duration <= 86400000:
                    raise InputError(f"{role}: invalid duration_ms for {key!r}")
            cases[key] = row
            if len(cases) > MAX_CASES:
                raise InputError(f"{role} exceeds {MAX_CASES} cases")
    if not cases:
        raise InputError(f"{role} dataset is empty")
    return cases


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()


def _pointer(path: str, part: Any) -> str:
    return path + "/" + str(part).replace("~", "~0").replace("/", "~1")


def differences(expected: Any, actual: Any, absolute: float, relative: float,
                path: str = "", limit: int = 20) -> list[dict]:
    """Bounded exact-structure comparison; numeric tolerance never equates booleans."""
    result = []

    def walk(e, a, pointer):
        if len(result) >= limit:
            return
        numeric_e = isinstance(e, (int, float)) and not isinstance(e, bool)
        numeric_a = isinstance(a, (int, float)) and not isinstance(a, bool)
        if numeric_e and numeric_a:
            # Exact integer checks retain precision beyond IEEE-754's exact range.
            if e == a:
                return
            if absolute == relative == 0:
                result.append({"path": pointer, "reason": "numeric_mismatch"})
                return
            try:
                close = abs(e - a) <= max(absolute, relative * max(abs(e), abs(a)))
            except OverflowError:
                close = False
            if not close:
                result.append({"path": pointer, "reason": "numeric_mismatch"})
        elif type(e) is not type(a):
            result.append({"path": pointer, "reason": "type_mismatch"})
        elif isinstance(e, dict):
            for key in sorted(set(e) | set(a)):
                if key not in e or key not in a:
                    result.append({"path": _pointer(pointer, key), "reason": "missing_or_extra_key"})
                else:
                    walk(e[key], a[key], _pointer(pointer, key))
                if len(result) >= limit:
                    break
        elif isinstance(e, list):
            if len(e) != len(a):
                result.append({"path": pointer, "reason": "list_length_mismatch"})
            for index, (left, right) in enumerate(zip(e, a)):
                walk(left, right, _pointer(pointer, index))
                if len(result) >= limit:
                    break
        elif e != a:
            result.append({"path": pointer, "reason": "value_mismatch"})

    walk(expected, actual, path)
    return result


def percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    point = (len(ordered) - 1) * proportion
    low, high = math.floor(point), math.ceil(point)
    return ordered[low] + (ordered[high] - ordered[low]) * (point - low)


def evaluate(reference: dict, observed: dict, absolute: float = 0,
             relative: float = 0, max_duration_ms: float | None = None) -> dict:
    for tolerance in (absolute, relative):
        if not math.isfinite(tolerance) or tolerance < 0:
            raise InputError("tolerances must be finite and nonnegative")
    if max_duration_ms is not None and (not math.isfinite(max_duration_ms) or max_duration_ms < 0):
        raise InputError("duration limit must be finite and nonnegative")
    if not reference or not observed:
        raise InputError("empty reference or observations")
    config = {"version": VERSION, "absolute_tolerance": absolute,
              "relative_tolerance": relative, "max_duration_ms": max_duration_ms,
              "comparison": "exact_structure", "diff_limit_per_case": 20}
    details = []
    durations = []
    for key in sorted(set(reference) | set(observed)):
        if key not in observed:
            details.append({"id": key, "status": "missing"})
        elif key not in reference:
            details.append({"id": key, "status": "unexpected"})
        else:
            row = observed[key]
            diff = differences(reference[key]["value"], row["value"], absolute, relative)
            reasons = []
            duration = row.get("duration_ms")
            if duration is not None:
                durations.append(duration)
            if max_duration_ms is not None:
                if duration is None:
                    reasons.append("required_duration_missing")
                elif duration > max_duration_ms:
                    reasons.append("duration_limit_exceeded")
            details.append({"id": key, "status": "fail" if diff or reasons else "pass",
                            "differences": diff, "gate_reasons": reasons})
    functional = {"schema": "freez.evalgate.functional.v1", "config": config,
                  "config_sha256": canonical_hash(config),
                  "reference_sha256": canonical_hash({key: reference[key]["value"] for key in sorted(reference)}),
                  "observed_values_sha256": canonical_hash({key: observed[key]["value"] for key in sorted(observed)}),
                  "cases": details,
                  "counts": {status: sum(row["status"] == status for row in details)
                             for status in ("pass", "fail", "missing", "unexpected")}}
    return {"schema": "freez.evalgate.report.v1", "passed": all(row["status"] == "pass" for row in details),
            "functional": functional, "functional_sha256": canonical_hash(functional),
            "latency": {"source": "caller_supplied_measurements_not_independently_trusted",
                        "unit": "milliseconds", "sample_count": len(durations),
                        "individual_measurements": durations, "p50": percentile(durations, .5),
                        "p95": percentile(durations, .95)},
            "environment": {"python": platform.python_version(), "platform": platform.platform()}}


def atomic_json(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    filename = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".evalgate-", suffix=".tmp", delete=False) as stream:
            filename = stream.name
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, path)
        filename = None
    finally:
        if filename is not None:
            os.unlink(filename)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--absolute-tolerance", type=float, default=0)
    parser.add_argument("--relative-tolerance", type=float, default=0)
    parser.add_argument("--max-duration-ms", type=float)
    args = parser.parse_args(argv)
    try:
        if args.report.resolve() in {args.reference.resolve(), args.observed.resolve()}:
            raise InputError("report must not overwrite input data")
        report = evaluate(load_cases(args.reference, "reference"), load_cases(args.observed, "observed"),
                          args.absolute_tolerance, args.relative_tolerance, args.max_duration_ms)
        atomic_json(args.report, report)
        print(json.dumps({"passed": report["passed"], "counts": report["functional"]["counts"],
                          "functional_sha256": report["functional_sha256"]}, sort_keys=True))
        return 0 if report["passed"] else 1
    except (OSError, InputError) as exc:
        print(f"Input/report error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
