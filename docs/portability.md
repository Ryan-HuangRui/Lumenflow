# Portability Design

## Goal

This repository should be useful outside a single agent platform.

Supported hosts should be able to use the same core assets:

- `skills/*/SKILL.md`
- `knowledge/`
- `scripts/`

Platform-specific behavior belongs in `adapters/`.

## Boundaries

### Portable Core

The portable core contains:

- Skill instructions written without platform-specific assumptions.
- JSON style cards and tutorial recipes.
- RawTherapee / darktable profiles.
- Small scripts that run from a normal shell.

The portable core must not depend on Codex-only concepts such as a specific automation schema, thread id, or workspace metadata.

### Host Adapters

Adapters may describe:

- How to install or register skills in a host.
- How to schedule style-library updates.
- How to expose local shell scripts to the agent.
- How to provide credentials for X, YouTube, or other sources.

Adapters should stay thin. They should not duplicate style logic.

## Host Targets

### Codex

Codex can use `skills/` directly and can run scheduled updates through Codex automations.

### Claude

Claude-facing setup should map the same `SKILL.md` workflow and `scripts/` tools into Claude's available local-tool or project-instruction model.

### OpenClaw

OpenClaw-facing setup should expose the same scripts and knowledge directory through its agent/tool configuration.

## Rule

If a change improves one host but makes another host harder to support, put it behind an adapter instead of changing the portable core.
