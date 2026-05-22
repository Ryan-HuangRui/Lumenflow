# Codex Adapter

Use the portable `skills/`, `knowledge/`, and `scripts/` directly.

Codex-specific work should stay here:

- Skill installation notes.
- Automation setup for scheduled style-library updates.
- Credential handling notes for local runs.

## Environment Check

Run this before photo processing or scheduled style-library updates:

```bash
python scripts/check_environment.py
```

The output is JSON. `summary.overall_status=ready` means no required dependency
is missing; optional providers can still be absent until their phase is used.

## X Style Source Updates

Use Codex automation or an agent-framework cron to run the portable `learn-styles` workflow.

Local setup:

```bash
cp knowledge/source_records/x_sources.example.json knowledge/source_records/x_sources.json
export X_BEARER_TOKEN="..."
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json --dry-run
```

Scheduled run:

```bash
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json
```

The script only fetches and records source material. Codex should then review new
`knowledge/source_records/x_*.json` files with `analysis.status=pending_agent_review`,
summarize visual style traits, and update `knowledge/style_cards/*.json` with provenance.

Do not store `X_BEARER_TOKEN` in repo files. Use the host's environment or secret store.
