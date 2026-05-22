# 轻量版 Roadmap

## 定位

这个项目不是一个完整照片管理软件，也不是一个独立 Web/CLI 产品。

它的定位是：

```text
两个通用 agent skills + 一个本地风格知识库 + 少量可复用脚本 + 平台适配层
```

Agent host 是主要交互入口，可以是 Codex、Claude、OpenClaw 或其他支持本地工具调用的 agent。用户不会长期手动操作复杂 CLI，而是直接对 agent 说：

```text
帮我处理 /path/to/photos 里的照片，输出到 /path/to/output
```

然后 agent 调用照片处理 skill 完成筛选、调色、导出和记录。

风格库更新则由宿主平台的定时任务运行，调用风格库更新 skill，从社交媒体和视频教程里整理风格知识。

## 当前状态

更新时间：2026-05-22。

当前处于：

```text
Phase 1 照片处理最小闭环已跑通
→ 下一节点：补齐 darktable 可执行风格库，并把视频教程 transcript provider 抽象落地
```

已实现：

- `develop-photos` skill 已有基础工作流说明。
- `learn-styles` skill 已有 X 白名单更新工作流说明。
- 本地风格知识库已拆成 `knowledge/style_cards/*.json`、`knowledge/raw_profiles/*.pp3`。
- 照片处理闭环已实现：
  - `scripts/scan_raws.py` 扫描 RAW。
  - 识别 darktable `<raw filename>.xmp` 中的星级和颜色标签。
  - 识别 RawTherapee `<raw filename>.pp3` 中的 rank。
  - `scripts/render_raw.py` 支持 `darktable-cli` 和 `rawtherapee-cli` 两种后端。
  - `scripts/develop_photos.py` 串联扫描、筛选、选风格、渲染、记录输出。
  - 输出 `processing_records.json` 和 `processing_report.md`。
- `darktable-cli` 5.4.1 已在本机安装并通过真实 DNG 导出验证。
- 环境预检已实现：
  - `scripts/check_environment.py` 输出 JSON 形式依赖状态。
  - `requirements.txt` 固定当前/下一步轻量 Python 依赖。
- X 白名单来源拉取脚本已实现：
  - `scripts/update_x_sources.py` 使用官方 X API read-only 拉取白名单账号新帖子。
  - 支持 `since_id` 增量状态、幂等 source record 写入、dry-run。
- 自动化测试已覆盖照片处理核心脚本：
  - `tests/test_photo_pipeline.py` 覆盖 sidecar 解析、筛选逻辑、darktable 命令构造、dry-run 批处理记录。

尚未实现：

- darktable 可执行风格库：当前 style card 主要指向 RawTherapee `.pp3`，还没有沉淀 darktable style / XMP history。
- Agent 视觉判断到风格选择的自动化细化：当前批处理入口支持显式 `--style-id`，默认选 `clean_natural`。
- 视频教程入库脚本：`scripts/transcript_providers.py`、`scripts/ingest_tutorial.py` 尚未实现。
- X source record 到视觉摘要、style card 合并的 agent workflow 尚未落地。
- Codex / agent host 定时任务尚未配置。

## 核心组件

### 1. 照片处理 skill

职责：

1. 扫描用户指定目录里的 RAW 照片。
2. 识别用户已经标记/筛选的照片。
3. 读取风格库。
4. 让 agent 自主判断每张照片适合什么风格。
5. 调用 darktable CLI / RawTherapee CLI 执行处理。
6. 输出处理后的图片到用户指定目录。
7. 生成处理记录。

输入：

```text
源目录
输出目录
可选：只处理几星以上
可选：偏好的风格或排除的风格
```

输出：

```text
output/
├── IMG_001_cinematic.jpg
├── IMG_001_clean.jpg
├── processing_records.json
└── processing_report.md
```

处理记录应包含：

- 原始文件路径
- 输出文件路径
- 使用的风格
- 调用的 profile / CLI 参数
- agent 判断理由
- 失败原因，如果有

### 2. 风格库更新 skill

职责：

1. 从 X 等社交媒体拉取指定摄影师的新照片或帖子。
2. 反推调色风格，写入风格库。
3. 从 YouTube 等视频网站拉取调色教程。
4. 将教程转写成结构化调色 recipe。
5. 合并重复风格，保留来源和证据。

输入：

```text
摄影师账号白名单
教程频道/播放列表/视频链接
风格库路径
```

输出：

```text
knowledge/style_cards/*.json
knowledge/tutorial_recipes/*.json
knowledge/source_records/*.json
```

风格库更新不直接处理照片，也不生成最终图片。它只负责沉淀“风格知识”。

### 3. 本地风格知识库

知识库是普通文件，不需要一开始上数据库。

建议结构：

```text
knowledge/
├── style_cards/
│   ├── cinematic_moody.json
│   ├── clean_natural.json
│   └── fuji_travel_muted.json
├── tutorial_recipes/
│   └── youtube_cinematic_city_001.json
├── source_records/
│   ├── x_photographer_post_001.json
│   └── youtube_video_001.json
└── raw_profiles/
    ├── cinematic_moody.pp3
    └── clean_natural.pp3
```

风格卡只记录抽象后的风格，不把社媒图片复制成训练集。

## 仓库建议结构

```text
lumenflow/
├── skills/
│   ├── develop-photos/
│   │   └── SKILL.md
│   └── learn-styles/
│       └── SKILL.md
├── knowledge/
│   ├── style_cards/
│   ├── tutorial_recipes/
│   ├── source_records/
│   └── raw_profiles/
├── adapters/
│   ├── codex/
│   ├── claude/
│   └── openclaw/
├── scripts/
│   ├── scan_raws.py
│   ├── develop_photos.py
│   ├── render_raw.py
│   ├── update_x_sources.py
│   └── write_processing_report.py
├── tests/
│   └── test_photo_pipeline.py
└── docs/
```

不保留产品化 CLI 和 Python package 入口。需要复用的能力沉到 `scripts/`，由 skill 编排调用。平台差异放进 `adapters/`，不要渗透到 `knowledge/` 和通用脚本。

## 环境依赖与安装路线

### 当前环境快照

最近一次检查：2026-05-22，本机 macOS + Homebrew 环境。

已具备：

- 基础环境：Homebrew、Python 3.10、pip、Node.js 22、npm、git、curl、sqlite3。
- 元数据读取：`exiftool` 13.55。
- 视频/音频处理：`ffmpeg` / `ffprobe` 8.0.1。
- 视频获取：`yt-dlp` 2025.12.08 CLI。
- RAW 渲染：`darktable-cli` 5.4.1 已安装并通过包装脚本进入 `/opt/homebrew/bin/darktable-cli`。
- Python 基础库：`Pillow`、`pydantic`、`requests`。

当前缺口：

- RAW 渲染：`rawtherapee-cli` 已在 `/opt/homebrew/bin/rawtherapee-cli`，但当前 macOS 环境下 `rawtherapee-cli -v` 5 秒内不返回，尚未通过自动化运行验收；照片处理 MVP 先走 darktable。
- JSON 辅助工具：`jq` 未安装。
- 本地转写：`whisper-cpp` / `whisper-cli` 未安装，也没有 Whisper GGML 模型文件；Python `whisper` / `faster-whisper` 未安装。
- 模型能力调用：交互式 Codex 或基于 agent host 的定时任务可以直接使用宿主 agent 的视觉/推理能力；只有 headless 脚本独立运行时，才需要 Python `openai` SDK/API key 或其他模型 provider 配置。
- YouTube 教程入库：第一步只需要 Python `youtube-transcript-api` 或 YouTube transcript MCP；当前 Python `youtube-transcript-api` 未安装，`google-api-python-client` 仅作为批量元数据可选依赖。
- X 社媒接入：已采用标准库脚本调用官方 X API；还没有本机 `X_BEARER_TOKEN`、实际白名单账号配置和增量同步状态文件。
- Instagram / Bilibili：不作为默认自动抓取依赖；优先走用户提供链接、字幕、转写或官方/授权接口。

### Phase 0：依赖预检和项目虚拟环境

目标：在实现功能前，让 agent 能明确判断哪些能力可用、哪些能力只能 dry-run。

安装建议：

```bash
brew install jq
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

仓库需要补充：

- Done：`requirements.txt` 固定当前/下一步轻量 Python 包。
- Done：`scripts/check_environment.py` 输出 JSON 形式的依赖状态。
- Done：在 `adapters/codex/README.md` 写明 Codex 运行前的环境检查命令。

验收：

```bash
python scripts/check_environment.py
```

输出应能区分：

- `available`：当前可执行。
- `missing_required`：当前 Phase 必须补齐。
- `missing_optional`：后续 Phase 才需要。

### Phase 1 依赖：本地照片处理闭环

优先安装：

```bash
brew install --cask darktable
```

darktable cask 安装的是 macOS App。若 `darktable-cli` 没有自动进入 `PATH`，需要在适配层提供 wrapper，例如：

```bash
printf '%s\n' '#!/bin/sh' 'exec /Applications/darktable.app/Contents/MacOS/darktable-cli "$@"' > /opt/homebrew/bin/darktable-cli
chmod +x /opt/homebrew/bin/darktable-cli
```

可选安装：

```bash
brew install --cask rawtherapee
```

说明：darktable 是第一版照片筛选/标记/CLI 导出闭环。RawTherapee 只作为 `.pp3` profile 备选引擎，前提是本机 `rawtherapee-cli` 能通过运行验收。

验收：

```bash
exiftool -ver
darktable-cli --help
python scripts/scan_raws.py /path/to/photos --selected-only --min-rating 1
python scripts/develop_photos.py /path/to/photos --output-dir /tmp/lumenflow-test --engine darktable --style-id clean_natural --dry-run
```

### Phase 3 依赖：视频教程入库

第一步采用轻量 transcript provider 抽象：视频教程入库脚本不直接绑定本地转写引擎，而是先把“从 URL 获取 transcript”封装成可替换 provider。默认优先接 YouTube transcript MCP 或 Python `youtube-transcript-api`，让 agent 拿到 transcript 后再抽取调色 recipe。

默认路线：

1. YouTube transcript MCP：适合 Codex / agent host 编排，输入 YouTube URL，返回 transcript / timed transcript / video metadata。
2. `youtube-transcript-api`：适合 repo 内 Python 脚本轻量调用，优先获取官方字幕或自动字幕。
3. 用户提供 transcript / 字幕文件：作为最稳定的人工补入口。
4. 云端 ASR provider：用于没有字幕的视频，后续可接 AssemblyAI / Deepgram / Gladia 等远程转写服务。
5. 本地 `yt-dlp + ffmpeg + whisper-cpp`：只作为最后 fallback，不作为第一版默认依赖。

第一步必须安装：

```bash
python -m pip install youtube-transcript-api
```

如果教程入库由 Codex 定时任务或其他 agent 框架 cron 编排，transcript 到 recipe 的结构化提取可以直接使用宿主 agent 的模型能力，不要求项目安装 `openai` SDK。只有把 `scripts/ingest_tutorial.py` 做成无人值守 headless 脚本时，才需要额外安装 `openai` 或其他模型 provider SDK。

可选安装：

```bash
brew install ffmpeg yt-dlp whisper-cpp
python -m pip install google-api-python-client
```

说明：

- `ffmpeg` / `yt-dlp` / `whisper-cpp` 只用于本地 fallback。
- `google-api-python-client` 只在需要 YouTube Data API 查询频道、播放列表或批量视频元数据时安装。
- Whisper 模型不会随 `whisper-cpp` 自动安装，需要单独下载 GGML 模型文件，并在配置中记录路径。建议从小模型开始：

```text
models/whisper/ggml-base.bin
```

教程入库优先级：

1. YouTube transcript MCP 或 `youtube-transcript-api` 获取官方字幕 / 自动字幕。
2. 用户手动提供 transcript / 字幕文件。
3. 云端 ASR provider 远程转写。
4. `yt-dlp` 获取允许下载的字幕。
5. `ffmpeg` 抽音频 + `whisper-cpp` 本地转写。

仓库需要补充：

- `scripts/ingest_tutorial.py`：把视频链接、字幕文件或 transcript 转成 `knowledge/tutorial_recipes/*.json`。
- `scripts/transcript_providers.py`：封装轻量 provider 接口，第一版至少支持 `youtube_transcript_api`，预留 `mcp_youtube_transcript`、`cloud_asr`、`local_whisper`。
- `knowledge/source_records/` 中的视频来源记录 schema。
- provider 配置示例：默认无密钥；云端 ASR / YouTube Data API / 本地 Whisper 模型路径都作为可选配置，不把模型文件和密钥提交进仓库。

验收：

```bash
python -c "import youtube_transcript_api"
python scripts/ingest_tutorial.py --url "https://www.youtube.com/watch?v=..." --transcript-provider youtube_transcript_api --dry-run
```

### Phase 4 依赖：社交媒体风格更新

X 先行。当前 `scripts/update_x_sources.py` 使用 Python 标准库直接调用官方 X API，脚本本身不强制依赖 `tweepy`。如后续改用 SDK，可选安装：

```bash
python -m pip install tweepy
```

如果社媒风格更新由 Codex 定时任务或其他 agent 框架 cron 编排，图片风格摘要、风格卡合并和更新说明可以直接使用宿主 agent 的视觉/推理能力，不要求项目安装 `openai` SDK。只有把社媒更新做成纯脚本后台任务时，才需要配置 `openai` 或其他模型 provider。

当前实现采用官方 X API read-only 路线，基础脚本为：

```bash
cp knowledge/source_records/x_sources.example.json knowledge/source_records/x_sources.json
export X_BEARER_TOKEN="..."
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json --dry-run
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json
```

说明：`scripts/update_x_sources.py` 只负责白名单账号解析、timeline 增量拉取、媒体元数据展开、source record 写入和 `since_id` 状态维护；风格摘要和 style card 合并由宿主 agent 在 `learn-styles` workflow 中完成。

还需要用户提供：

- X API bearer token 或等价授权方式。
- 摄影师账号白名单。
- 增量同步状态文件位置，例如 `knowledge/source_records/x_sync_state.json`。

实现约束：

- 只拉取白名单账号和公开可授权内容。
- 只保存来源链接、文本、媒体元数据、视觉摘要和抽象风格特征。
- 不把社媒图片复制为训练集。
- 每次运行必须幂等：已处理 source id 不重复写入。

Instagram / Bilibili：

- 不作为第一版 cron 自动抓取目标。
- 优先支持用户提供链接、字幕、截图或 transcript。
- 如后续接官方/授权接口，接入逻辑放在 `adapters/` 或独立 connector，不污染通用 `knowledge/` 格式。

验收：

```bash
python scripts/update_x_sources.py --print-config-example
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json --dry-run
```

### Phase 5 依赖：定时自动更新

Codex 适配层需要补充：

- 定时任务如何调用 `learn-styles`。
- 环境变量和凭据注入方式。
- cron / automation 日志输出位置。
- 失败时如何记录到 `knowledge/source_records/`，并避免破坏已有风格库。

验收：

```text
定时任务运行后：
1. 生成本次 update summary。
2. 写入或更新 source_records / tutorial_recipes / style_cards。
3. 没有凭据或平台限流时，输出失败原因并保持已有知识库不变。
```

## 落地阶段

### Phase 1：照片处理 skill 最小闭环

状态：Done / 可继续增强。

目标：用户对任意受支持 agent 说“帮我处理某个目录的照片”，agent 能跑完整流程。

已完成：

- 创建 `skills/develop-photos/SKILL.md`。
- 创建 `knowledge/style_cards/` 和 `knowledge/raw_profiles/`。
- 脚本支持：
  - 扫描 RAW
  - 读取 darktable `.xmp` 星级 / 颜色标签
  - 读取 RawTherapee `.pp3` rank
  - 调用 `darktable-cli` 或 `rawtherapee-cli`
  - 写 `processing_records.json` 和 `processing_report.md`
- darktable 路线已通过真实 DNG 副本导出验证。
- 先不接社交媒体和视频教程。

待增强：

- 把 style card 的抽象风格真正映射成 darktable style / XMP history，而不是只依赖默认 pipeline。
- 让 agent 根据照片内容自动选择 style id，而不是主要依赖显式 `--style-id` 或默认 `clean_natural`。
- NAS Photo 目录挂载后，用真实用户 RAW 副本再跑一次端到端验证。

验收：

```text
用户输入：帮我处理 /photos/trip 里的照片，输出到 /photos/output
Agent 行为：
1. 使用 develop-photos skill
2. 扫描 RAW
3. 根据现有风格库选择风格
4. 调用 darktable CLI / RawTherapee CLI
5. 输出 JPG
6. 生成 processing_records.json 和 processing_report.md
```

### Phase 2：风格库文件格式稳定

状态：In progress。

目标：让 skill 能长期复用风格知识。

已完成：

- `knowledge/style_cards/` 已有 5 个初始风格卡。
- `knowledge/raw_profiles/` 已有对应 RawTherapee `.pp3` profile。
- 照片处理脚本已能读取 style card 并解析 `raw_profiles`。

待完成：

- 定义 style card JSON schema
- 定义 tutorial recipe JSON schema
- 定义 source record JSON schema
- 补充 darktable 可执行风格字段，例如 `darktable_style` 或引用可执行 XMP history。
- 将 style card 中“抽象风格”和“执行 profile”分层，避免 `.pp3` 绑死 RawTherapee。

验收：

- 照片处理 skill 只依赖 `knowledge/`
- 新增一个风格卡不需要改代码

### Phase 3：视频教程入库 skill

状态：Next。

目标：先做教程入库，因为它比社媒图片更容易转成调色步骤。

已完成：

- `skills/learn-styles/SKILL.md` 已存在。
- roadmap 已明确轻量 transcript provider 抽象路线：
  - 默认 YouTube transcript MCP / `youtube-transcript-api`
  - 云端 ASR 和本地 Whisper 作为后置 fallback

待完成：

- 实现 `scripts/transcript_providers.py`。
- 实现 `scripts/ingest_tutorial.py`。
- 支持用户提供 YouTube/Bilibili 视频链接或字幕文件。
- Agent 提取教程中的调色步骤。
- 写入 `knowledge/tutorial_recipes/`。
- 可选地更新或生成 style card。

验收：

```text
用户输入：把这个调色教程入库：https://...
Agent 行为：
1. 使用 learn-styles skill
2. 获取字幕或提示用户提供 transcript
3. 提取结构化 recipe
4. 写入知识库
```

### Phase 4：社交媒体风格更新

状态：In progress。

目标：从指定摄影师账号定期拉取公开内容，沉淀风格卡。

已完成：

- X 先行路线已确定：官方 X API read-only，不依赖浏览器登录态。
- `scripts/update_x_sources.py` 已实现：
  - 摄影师账号白名单配置
  - 用户名解析
  - timeline 增量拉取
  - media metadata 展开
  - `x_sync_state.json` 状态维护
  - 幂等写入 `knowledge/source_records/x_{username}_{post_id}.json`
  - dry-run 和配置示例输出
- `knowledge/source_records/x_sources.example.json` 已存在。

待完成：

- 配置本机私有 `knowledge/source_records/x_sources.json`。
- 配置 `X_BEARER_TOKEN` 并跑通一次真实白名单拉取。
- Agent 读取 `analysis.status=pending_agent_review` 的 source records，生成视觉摘要。
- 反推风格特征并合并到 style card。
- Instagram 后置；不做任意平台抓取。

验收：

```text
定时任务定期运行：
1. 拉取白名单摄影师新内容
2. 分析风格
3. 更新 knowledge/source_records/
4. 更新 knowledge/style_cards/
```

### Phase 5：定时自动更新

状态：Not started。

目标：把风格库更新变成定时任务。

范围：

- 创建宿主平台定时任务适配
- 每周或每天运行 learn-styles skill
- 输出更新摘要
- 失败时记录原因，不破坏已有知识库

验收：

- 定时任务能独立运行
- 风格库更新有日志和 diff
- 用户可以在对话里问“最近风格库更新了什么”

## 下一步 TODO

按当前依赖关系，建议下一步这样排：

1. 补 darktable 可执行风格库
   - 为 5 个现有 style card 增加 `darktable_style` 或可执行 XMP history。
   - 让 `scripts/develop_photos.py` 不只是调用 darktable default pipeline，而是能真正应用风格。

2. 实现视频教程入库最小闭环
   - 新增 `scripts/transcript_providers.py`。
   - 新增 `scripts/ingest_tutorial.py`。
   - 先支持 `youtube-transcript-api` 和用户提供 transcript。
   - 输出 `knowledge/tutorial_recipes/*.json`。

3. 跑通 X 真实白名单增量
   - 配置 `X_BEARER_TOKEN` 和 `x_sources.json`。
   - 生成一批 `source_records/x_*.json`。
   - 用 agent 处理 `pending_agent_review`，更新 style cards。

4. 接 Codex / agent host 定时任务
   - 定期运行 `learn-styles`。
   - 输出 update summary。
   - 失败时写明原因，不破坏已有知识库。

## 非目标

短期不做：

- Web UI
- 完整照片管理系统
- 复杂数据库
- 大规模社媒爬虫
- 从零训练风格模型
- 替代 Lightroom / darktable 的完整编辑体验

短期只做各类 agent host 都能稳定调用的技能化工作流。
