"""Run actual normalization work and retain measurements, not invented scores."""
import argparse
import json
import time
from pathlib import Path

from evalgate import atomic_json, evaluate, load_cases
from normalizer import normalize_order


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evidence"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    inputs = load_cases(root / "fixtures/input.jsonl", "reference")
    reference = load_cases(root / "fixtures/reference.jsonl", "reference")
    observed = {}
    warmup = 5
    for _ in range(warmup):
        for row in inputs.values():
            try:
                normalize_order(row["value"])
            except ValueError:
                pass
    for key in sorted(inputs):
        started = time.perf_counter_ns()
        try:
            value = {"ok": True, "record": normalize_order(inputs[key]["value"])}
        except ValueError as exc:
            value = {"ok": False, "error": str(exc)}
        observed[key] = {"id": key, "value": value, "duration_ms": (time.perf_counter_ns() - started) / 1e6}
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "observed.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in observed.values():
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    baseline = evaluate(reference, observed)
    baseline["measurement_method"] = {"clock": "time.perf_counter_ns", "warmup_passes": warmup,
                                      "measured_passes": 1, "execution": "local Python order normalization",
                                      "dataset": "self-authored functional fixtures, not a real product trial"}
    atomic_json(args.output / "baseline.json", baseline)
    altered = json.loads(json.dumps(observed))
    altered["usd-rounding"]["value"]["record"]["amount"] = "99.99"
    regression = evaluate(reference, altered)
    atomic_json(args.output / "intentional-regression.json", regression)
    repeated = evaluate(reference, observed)
    if not baseline["passed"] or regression["passed"] or repeated["functional_sha256"] != baseline["functional_sha256"]:
        raise SystemExit("baseline, regression detection or reproducibility assertion failed")
    print(json.dumps({"baseline": baseline["functional"]["counts"],
                      "regression": regression["functional"]["counts"],
                      "functional_sha256": baseline["functional_sha256"], "warmup_passes": warmup}, sort_keys=True))


if __name__ == "__main__":
    main()
