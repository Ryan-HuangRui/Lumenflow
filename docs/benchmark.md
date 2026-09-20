# Photo-agent Benchmark

The benchmark answers two separate questions:

1. Did the runtime preserve identity, RAW bytes, and output evidence?
2. Did the rendered image satisfy the photographic purpose and visual rubric?

The first is deterministic and mandatory. The second is authored by the host model after it sees
the exact rendered JPEG. A high visual score can never compensate for an execution or integrity
failure.

## Private corpus

Keep RAW files, previews, outputs, assessments, and reports outside the public repository, for
example under the ignored `runs/benchmark/` tree. A committed schema describes each case without
requiring Lumenflow to publish personal photos.

Build a small representative suite before expanding it. Include daylight, night, skin tones,
high dynamic range, mixed light, strong color, and composition-sensitive frames. Each
`lumenflow.benchmark_case.v1` fixes:

- purpose;
- RAW fingerprint;
- preview/state basis;
- target style;
- searchable scene tags.

Do not reuse the same near-duplicate capture as several independent cases.

## Visual rubric

After the normal compile, execute, and bounded-review workflow, the host model emits
`lumenflow.visual_assessment.v1` for the exact output fingerprint. The five 1–5 dimensions are:

- technical quality;
- purpose fit;
- style coherence;
- composition;
- naturalness.

It also makes explicit boolean checks for highlight detail, shadow detail, color integrity,
composition intent, and visible artifacts. The `model_id` is recorded so comparisons do not hide
a judge change.

## Recording and reporting

```bash
python3 scripts/benchmark_eval.py record \
  case.json execution_plan.json execution_receipt.json \
  --session review_session.json \
  --assessment visual_assessment.json \
  --runtime-ms 1840 \
  --output observation.json
```

For failed execution, omit `--session` and `--assessment`. It is still recorded and counts against
the acceptance and integrity gates. Dry runs are excluded.

Collect observations into one JSON array, then build a report:

```bash
python3 scripts/benchmark_eval.py report observations.json \
  --minimum-cases 5 \
  --minimum-acceptance-rate 0.8 \
  --minimum-mean-score 4.0 \
  --minimum-check-pass-rate 1.0 \
  --output candidate-report.json
```

The default gate requires zero integrity failures. Observation ids hash all recorded runtime and
score content; report generation rejects a changed observation unless a new id is deliberately
computed. This detects stale or accidental edits but is not a signature or external attestation.

Compare a candidate against a previously accepted baseline:

```bash
python3 scripts/benchmark_eval.py compare candidate-report.json baseline-report.json \
  --maximum-acceptance-drop 0.05 \
  --maximum-score-drop 0.25 \
  --output comparison.json
```

Backend capability promotion requires both its own implementation gates and a passing benchmark.
Benchmark success alone never changes `backend_capabilities.py`.
