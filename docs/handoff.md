# Lumenflow Handoff

> 当前仓库已从“独立 CLI 产品”收敛为“两个通用 agent skills + 一个本地风格知识库 + 少量脚本 + 平台适配层”的结构。最新落地路线以 `docs/roadmap.md` 为准。

## Goal

Build an agent-driven personal photography workflow:

1. User manually selects or rates RAW photos, similar to Lightroom.
2. An agent host periodically builds a style library from approved sources:
   - X / Instagram photographers or curated social links.
   - YouTube / Bilibili color-grading tutorials.
3. During processing, the agent analyzes selected photos, retrieves matching style cards and tutorial recipes, generates executable RAW adjustment parameters, and exports 2-3 variants per photo.

## Core Decision

Use the agent host as the orchestrator and RawTherapee or darktable as the RAW execution layer.

Recommended MVP stack:

- Rating/tagging: digiKam or darktable.
- Metadata reading: XMP sidecars, ExifTool, Python parser.
- RAW rendering: RawTherapee CLI first, darktable CLI later if needed.
- Style knowledge base: local files plus SQLite/vector index.
- Agent runtime: portable skill instructions, small scripts, and optional host adapters for Codex, Claude, OpenClaw, or MCP-compatible tools.
- Vision/LLM: start with OpenAI vision model or another multimodal model for analysis.

RawTherapee is preferred for the first executable prototype because `.pp3` processing profiles are text-like, composable, and CLI-friendly.

## MVP Scope

Do not start with full social ingestion. Build this first:

1. Local project layout.
2. Manual style cards for 5 starter styles:
   - `clean_natural`
   - `cinematic_moody`
   - `warm_sunset`
   - `soft_portrait`
   - `fuji_travel_muted`
3. Read selected RAWs from a folder and optional XMP rating metadata.
4. Generate JPEG previews.
5. Analyze each preview.
6. Match one style card.
7. Choose an existing `.pp3` profile and produce three variants:
   - natural
   - matched style
   - social/high-impact
8. Produce a Markdown review report per batch.

## Source Strategy

### X

Most feasible official social source for automation. Use following list and user post endpoints, with media fields and incremental sync. Needs API token, rate-limit handling, caching, and deduplication.

### Instagram

Do not assume arbitrary followed-account scraping is available. Treat Instagram as constrained:

- Prefer explicit photographer whitelist.
- Prefer professional / creator public accounts where official API access is available.
- Store source URLs and style abstractions.
- Avoid non-official bulk scraping as the default design.

### YouTube

High-value source because tutorials map directly to grading recipes. Use official metadata/caption APIs where possible; if caption download is not permitted for third-party videos, use user-provided links plus local ASR.

### Bilibili

Use cautious, user-provided links and local transcript/ASR path first. Avoid depending on unofficial large-scale APIs.

## Recommended Next Step

Start with a local-only MVP:

- No social connector yet.
- No Instagram/Bilibili scraping.
- Use 5 hand-written style cards and placeholder `.pp3` profiles.
- Prove the photo selection, preview generation, style matching, RawTherapee CLI invocation, and report loop.

After the local loop works, add source-ingest connectors as independent plugins or skills.
