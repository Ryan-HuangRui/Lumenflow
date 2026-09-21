# darktable Backend Feasibility Gate

## Decision

darktable remains a legacy-only backend. Lumenflow must not advertise `intent.compile.v2`,
state-bound previews, or first-class rendering until a full isolated export probe passes on a
supported installation and the missing compiler/provider work is implemented.

The presence of a `darktable-cli` path is not sufficient evidence. Run:

```bash
python3 scripts/darktable_probe.py \
  --raw /absolute/path/to/sentinel.NEF \
  --output-dir /absolute/path/to/probe-output \
  --report-output /absolute/path/to/darktable-probe.json
```

The report uses `lumenflow.darktable_probe.v1`. A `passed` result requires all of the following:

- the executable returns a parseable version response;
- a real RAW exports through a fresh temporary config and cache;
- the command uses an in-memory library and `write_sidecar_files=never`;
- the RAW fingerprint is identical before and after execution;
- existing sidecars are unchanged and no standard darktable XMP sidecar appears;
- the output exists and has a recorded SHA-256 fingerprint.

A version-only check is `inconclusive`, not `passed`. Any missing executable, non-zero exit,
missing output, source drift, or sidecar drift fails closed.

## Local evidence on 2026-09-21

The available `/opt/homebrew/bin/darktable-cli` was a wrapper targeting
`/Applications/darktable.app/Contents/MacOS/darktable-cli`, but that application executable was
absent. A Homebrew cask reinstall was attempted and Homebrew refused installation because the
cask had been disabled on 2026-09-01 for failing macOS Gatekeeper checks.

Lumenflow does not bypass Gatekeeper as part of this probe. This host therefore cannot provide
the real-RAW passing evidence required to promote darktable. The probe and its schema preserve
the exact gate so it can be rerun after a trusted, supported darktable installation is available.

## Promotion work still required

Even after the probe passes, darktable remains legacy-only until all of these land:

1. a state-bound preview provider that fingerprints the complete history-stack input;
2. an EditIntent v2 compiler mapping only explicitly supported modules;
3. an execution plan/receipt adapter with exact command reconstruction;
4. regression fixtures proving no RAW, sidecar, or catalog mutation;
5. review-loop and benchmark evidence comparable to the RawTherapee path.

Only then may `scripts/backend_capabilities.py` promote individual darktable capabilities from
`unsupported` to `supported`.
