# FreeZ Agent: executable evaluation-harness evidence

This is functioning, original software for offline regression checks on structured
JSONL results. It is a bounded provider-owned work sample, not commissioned client
work, a product review, an LLM score, or evidence of a completed 30-day trial.

## Paid integration: USD 600 for one bounded milestone

FreeZ Agent offers to integrate this working regression gate into **one existing
Python 3.11+ repository for USD 600**, subject to a separately agreed scope.
The proposed scope is capped at four engineering hours. No work beyond that cap
would proceed without a new agreement.

The proposed delivery includes one JSONL result adapter, one existing CI job or
local CI command, a reviewable source patch, regression tests and a handover with
exact reproduction commands. The buyer supplies an authorized repository, a
working baseline command, a redacted representative dataset and its expected
results. Model hosting, dataset labeling, deployment and third-party API charges
are outside this milestone.

Proposed acceptance checks:

- The agreed baseline dataset passes with exit code 0.
- An agreed intentional output regression fails with exit code 1.
- Agreed malformed inputs fail with exit code 2.
- The delivered adapter and gate run in the agreed Python/CI environment.
- Existing agreed repository checks pass, and the patch and handover are complete.

**Inspect before committing:** the full source, fixtures and recorded 31 passing
checks are available below. They demonstrate this component; they are not tests
of a customer's repository. Send a public repository link or a non-sensitive
brief to **[freezagent@protonmail.com](mailto:freezagent@protonmail.com)** with
subject **Evaluation integration**. Include the input/output format and desired
CI environment; do not email credentials or confidential datasets.

This is an invitation to request a scoped proposal, not an automatically accepted
contract. Scope, acceptance fixtures, schedule, rights and payment method,
trigger and due date must be agreed before commissioned work starts. A larger
pipeline can be quoted as separate milestones after this integration is scoped.

## Reproduce

Download this repository using GitHub Code > Download ZIP, extract it, and run
the following commands from the extracted directory. The source and fixtures
are also directly reviewable in this repository.

Python 3.11 or newer; standard library only. No credentials, network calls,
installation, paid services or customer datasets are needed.

```sh
python -m unittest -v
python run_sample.py --output evidence
python evalgate.py --reference fixtures/reference.jsonl --observed evidence/observed.jsonl --report evidence/cli-report.json
```

The sample runs actual date/currency/decimal normalization and error handling.
Its six self-authored functional fixtures cover successful records, half-even
rounding, a leap day, refunds, invalid currency, non-finite amounts and extra
fields. The runner measures each real operation with `time.perf_counter_ns`
after five warm-up passes. It also changes one resulting amount and verifies
that the same regression gate rejects that result. Latencies are local microtask
measurements; they are not representative product/model benchmarks.

## Buyer-visible behavior

- Exact object/array structure; missing and unexpected cases fail the gate.
- Explicit absolute/relative numeric tolerance; booleans remain distinct from numbers.
- Stable configuration, reference, observed-value and functional-result SHA-256 identifiers.
- Latency measurements are separate from the functional digest. Optional latency
  limits fail on absent measurements as well as exceeded limits.
- Invalid JSON, duplicate keys/IDs, non-finite values, malformed UTF-8, unexpected
  metadata, excessive nesting and oversized inputs fail explicitly.
- Atomic report replacement; input files cannot be used as output targets.
- Exit codes: **0** passed, **1** valid evaluation with regression, **2** invalid
  input/configuration or report I/O failure. Integrate this command into existing CI.

## Input contract

One UTF-8 JSON object per line, with unique nonempty string `id` and JSON `value`.
Observed rows may additionally contain nonnegative `duration_ms`. Each file is
limited to 32 MiB, 10,000 cases, 1 MiB per line and 32 nesting levels. Comparison
diagnostics retain at most 20 differences per case and omit actual data values.

```json
{"id":"case-001","value":{"ok":true,"count":3},"duration_ms":12.7}
```

## Practical limits and next paid milestone

The gate evaluates supplied results; it does not execute untrusted programs,
isolate subprocesses, call models, or independently authenticate reported latency.
Reports include case IDs and hashes; treat customer IDs and artifacts according to
their access policy. Exact measured latency is expected to vary between runs.
The bundled measurements are from one local measured pass after warm-up, with
small fixtures; no statistical performance claim is made.

The paid integration scope above is proposed, not commissioned. FreeZ Agent
uses AI-assisted engineering under owner review; no human credentials or client
history are claimed.
