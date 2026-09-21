# RawTherapee 5.11 live verification

Run date: 2026-09-22 (local macOS host)

The inputs below are local copies in
`/private/tmp/lumenflow-raw-fixtures/bangkok-2026`.  No NAS file is used as an
output target and the source SHA-256 was identical before and after each run.
The preview used the installed RawTherapee 5.11 profile
`Standard Film Curve - ISO Medium.pp3`; the execution PP3 embedded that
preview's explicit base-profile bytes and added the tested global adjustments.

| RAW | source SHA-256 | preview | final JPEG SHA-256 / bytes | source unchanged |
| --- | --- | --- | --- | --- |
| `P1034631.RW2` | `1124595cf9e669f56f724636ef26fe45fb564a893336d849db8c0f5e48c9df51` | success | `9cb2cc189af2d1bd6f197ef880f61a85ec0f6fdc9e6ececfc4470fff7c8e91a3` / 4,831,521 | yes |
| `P1034748.RW2` | `40ff5e34965e5252ffab02244d2b336f69f5c8c7681ff0a1e2203ae30d52443a` | success | `1cfc3ac4dd9554b825cbd615f2b64e286a2237733e12741feed4c19e71d70a8b` / 3,380,203 | yes |
| `P1034812.RW2` | `e62187c516083dd31797021bc81c853c6650e2e0b6945b109936177bd0503b02` | success | `539016982a166b27bb903fd41256a52b47e6f7888d7f56ba2c7f4ff41ac0ce7a` / 9,841,912 | yes |

Representative commands (the other two fixtures use the same shape):

```text
rawtherapee-cli -o .../previews/P1034631.jpg -Y -p '.../Standard Film Curve - ISO Medium.pp3' -j92 -c .../P1034631.RW2
rawtherapee-cli -o .../exports/P1034631_live-p1034631_r1.jpg -Y -p .../exports/profiles/P1034631_live-p1034631_r1.pp3 -j92 -c .../P1034631.RW2
```

Each receipt is `status=success`, contains a verified output fingerprint, and
records the same source SHA-256 before and after execution.  The full command
argv and receipt data remain in the local fixture output directory rather than
in git.

One additional live export of `P1034631.RW2` used `-tz -b16` and produced a
16-bit compressed TIFF (`117,409,096` bytes,
SHA-256 `0e8dd6f8a759c997b68b5ea7cf9e46ed66e59707a4fb334049a1f816f433d3d7`)
with the same unchanged source hash.
