# Lumenflow

面向视觉模型的本地优先 RAW 选片、编排与修图工作流。

Lumenflow 把“审美判断”交给具备视觉能力的 agent，把扫描、预览、合同校验、渲染和审计交给确定性代码。它不是另一个照片管理器，也不是一组固定滤镜；它是一套可移植的 agent skills、JSON 合同和本地工具链。

> 当前状态：可用于本地实验和个人工作流。RawTherapee 是目前唯一的一等渲染后端；darktable 与 Lightroom 仍处于受限兼容/验证阶段。项目尚未发布稳定版本。

## 目录

- [为什么做 Lumenflow](#为什么做-lumenflow)
- [核心能力](#核心能力)
- [工作流](#工作流)
- [快速开始](#快速开始)
- [用 agent 完成一次选片](#用-agent-完成一次选片)
- [用 agent 完成一次修图](#用-agent-完成一次修图)
- [后端支持状态](#后端支持状态)
- [架构与数据合同](#架构与数据合同)
- [风格知识库](#风格知识库)
- [隐私与安全边界](#隐私与安全边界)
- [配置](#配置)
- [测试](#测试)
- [常见问题](#常见问题)
- [项目状态与路线图](#项目状态与路线图)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

## 为什么做 Lumenflow

传统批处理通常依赖评分器、预设或固定参数，但真实的摄影工作流需要理解用途和整组照片之间的关系：哪张适合作为开场、哪些是近重复、哪些值得保留为备选、某张图是否应该裁剪，以及一组照片应如何形成节奏。

Lumenflow 的分工是：

- **视觉模型负责判断**：理解用户用途，比较候选照片，识别表达、构图和氛围，选择风格并复核成片。
- **脚本负责事实与执行**：读取 RAW 元数据、提取预览、生成联系表、校验 JSON 合同、调用 RAW 引擎并记录可验证收据。
- **用户保留决定权**：agent 的选片结果只是提案；只有用户明确确认后，照片才会进入修图流程。

## 核心能力

- 按日期、用途和数量范围扫描 RAW 候选集。
- 从 RAW 提取相机内嵌 JPEG，生成带文件标识的联系表。
- 使用宿主模型的原生视觉能力去废片、比较近重复、分配叙事角色并编排顺序。
- 通过 `selection_plan.json` 固化提案，并要求用户显式确认。
- 根据目标照片和本地风格知识生成逐图 `EditIntent v2`，而不是批量套用固定 preset。
- 将编辑意图编译为后端专用 `ExecutionPlan`，执行后生成带输入/输出指纹的 `ExecutionReceipt`。
- 绑定实际成片进行复核，默认最多两轮有界修订。
- 只把最终接受的编辑写入本地个人范例库，供后续个性化检索。
- 用独立的 benchmark 合同区分执行可靠性与视觉质量。
- 从批准的教程来源构建本地私有风格证据，再生成可公开、去来源化的语义风格知识。

支持扫描的 RAW 扩展名包括：`.3fr`、`.arw`、`.cr2`、`.cr3`、`.dng`、`.nef`、`.orf`、`.raf`、`.raw` 和 `.rw2`。

## 工作流

```text
用户描述用途与照片目录
        ↓
curate-photos：扫描 → 内嵌预览 → 联系表
        ↓
视觉模型：去重、选片、分配角色、编排顺序
        ↓
用户确认 selection_plan
        ↓
develop-photos：预览证据 → EditIntent → ExecutionPlan
        ↓
RawTherapee 渲染 → ExecutionReceipt
        ↓
视觉模型复核成片 → 接受或有限修订
        ↓
输出成片、报告；可选写入个人范例库
```

四个可移植 skill 位于 [`skills/`](skills/)：

| Skill | 职责 |
| --- | --- |
| [`curate-photos`](skills/curate-photos/SKILL.md) | 按用途选片、去重、分配叙事角色和编排顺序 |
| [`develop-photos`](skills/develop-photos/SKILL.md) | 对用户已确认的照片生成逐图编辑意图、渲染并复核 |
| [`learn-styles`](skills/learn-styles/SKILL.md) | 从用户批准的来源更新本地风格知识库 |
| [`fetch-bilibili-subtitles`](skills/fetch-bilibili-subtitles/SKILL.md) | 获取已有字幕，供私有教程摄取流程使用 |

CLI 是 skill 调用的确定性工具，不是主要交互界面。审美选择不会由脚本中的固定分数替代。

## 快速开始

### 1. 获取代码

```bash
git clone https://github.com/Ryan-HuangRui/Lumenflow.git
cd Lumenflow
```

### 2. 创建 Python 环境

需要 Python 3.11 或更高版本。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

教程 ASR 是可选能力；只有需要本地语音识别时才安装：

```bash
python -m pip install -r requirements-asr.txt
```

### 3. 安装外部工具

当前完整照片主路径需要：

- [ExifTool](https://exiftool.org/)：读取元数据并提取 RAW 内嵌预览。
- [RawTherapee](https://rawtherapee.com/)：提供 `rawtherapee-cli`，用于状态绑定预览和一等 RAW 渲染。

可选工具包括 `darktable-cli`、Lightroom CLI Bridge、`ffmpeg`、`ffprobe` 和 `yt-dlp`。只有启用对应功能时才需要安装。

### 4. 创建本机配置

```bash
cp config/lumenflow.local.example.json config/lumenflow.local.json
```

至少把 `photos.output_root` 改为本机的绝对输出目录。`config/lumenflow.local.json` 已被 Git 忽略。

### 5. 检查环境

```bash
python scripts/check_environment.py --fail-on-missing-required
```

输出是 JSON；`summary.overall_status` 为 `ready` 表示当前必需依赖可用。可选工具缺失不会阻止不依赖它们的流程。

### 6. 让 agent 使用仓库

当前尚未提供一键安装包。请让支持本地文件和视觉输入的 agent host 读取本仓库的 `skills/`、`knowledge/` 与 `scripts/`。各宿主的适配说明位于 [`adapters/`](adapters/)；Codex 可直接从仓库运行这些 skill。

可以直接对 agent 说：

```text
请使用这个仓库的 curate-photos skill，
从 /path/to/raws 中选出 12 张照片，编排成一组城市旅行故事。
先给我选片提案，得到我确认后再修图。
```

## 用 agent 完成一次选片

准备 curation workspace：

```bash
python scripts/curate_photos.py prepare /path/to/raws \
  --output-dir /path/to/output/curation \
  --date-from 2026-06-01 \
  --date-to 2026-06-30
```

该命令会生成：

- `candidate_manifest.json`：RAW、元数据、预览和失败记录之间的可追踪映射。
- `previews/`：从 RAW 提取的相机内嵌 JPEG。
- `contact_sheets/`：供视觉模型完整浏览候选集的联系表。

随后，agent 应查看所有联系表；对焦点、表情或近重复选择不确定时，再查看单张高分辨率预览。它会依据 [`selection_plan.schema.json`](knowledge/schemas/selection_plan.schema.json) 写出 `selection_plan.json`。

校验并打包提案：

```bash
python scripts/curate_photos.py finalize \
  /path/to/output/curation/candidate_manifest.json \
  /path/to/output/curation/selection_plan.json
```

输出包括有序预览、规范化计划和 `selection_report.md`。此时计划状态仍应是 `agent_recommended_pending_user_confirmation`；用户确认后，agent 才能将其改为 `user_confirmed` 并交给 `develop-photos`。

`curate-photos` 不会修改 RAW、sidecar、Lightroom 评分或集合成员。

## 用 agent 完成一次修图

修图主路径以视觉模型生成的 [`EditIntent v2`](knowledge/schemas/edit_intent.schema.json) 为输入。该意图必须绑定：

- 用户确认的授权引用；
- RAW 内容指纹；
- 模型实际查看过的 `PreviewArtifact`；
- 生成预览时的起始状态哈希。

编译为 RawTherapee 执行计划：

```bash
python scripts/edit_intent.py compile /path/to/photo.edit_intent.json \
  --backend rawtherapee \
  --output-dir /path/to/output \
  --plan-output /path/to/output/photo.execution_plan.json
```

先进行 dry-run：

```bash
python scripts/edit_intent.py execute /path/to/output/photo.execution_plan.json \
  --allowed-output-dir /path/to/output \
  --receipt-output /path/to/output/photo.execution_receipt.json \
  --dry-run
```

检查计划后，移除 `--dry-run` 执行真实渲染。执行器会再次检查 RAW 指纹、能力合同、profile 内容、命令和输出目录边界；不满足条件时会拒绝运行。

首次成片不是自动接受的最终稿。宿主模型应查看实际输出，写入 [`ReviewResult v1`](knowledge/schemas/review_result.schema.json)，然后推进有界复核会话：

```bash
python scripts/review_loop.py start /path/to/photo.edit_intent.json \
  --max-revisions 2 \
  --state-output /path/to/output/photo.review_session.json

python scripts/review_loop.py advance \
  /path/to/output/photo.review_session.json \
  /path/to/output/photo.execution_plan.json \
  /path/to/output/photo.execution_receipt.json \
  /path/to/output/photo.review_result.json \
  --state-output /path/to/output/photo.review_session.json \
  --next-intent-output /path/to/output/photo.edit_intent.r2.json
```

完整职责与证据规则见 [`docs/review_loop.md`](docs/review_loop.md)。

## 后端支持状态

| 后端 | 当前定位 | 预览 | EditIntent v2 | 真实执行 |
| --- | --- | --- | --- | --- |
| RawTherapee | 推荐的一等后端 | 支持，绑定 RAW 与起始 profile/sidecar 状态 | 支持 | 支持 |
| darktable | legacy/实验路径 | 尚无一等状态绑定 provider | 尚无编译器 | 仅在隔离探针通过后评估，不自动升级能力 |
| Lightroom Classic | 交互式兼容路径 | 尚未完成可信状态绑定 | 仍使用旧 `adjustment_plan.v1` 路径 | 默认 fail-closed；当前只应 dry-run |

后端能力由 `lumenflow.backend_capabilities.v1` 明确声明为 `supported`、`unsupported` 或 `unverified`。命令存在不等于能力已经安全可用：

```bash
python scripts/backend_capabilities.py rawtherapee
python scripts/backend_capabilities.py darktable
python scripts/backend_capabilities.py lightroom --probe
```

darktable 的隔离验证方法见 [`docs/darktable_backend_spike.md`](docs/darktable_backend_spike.md)。Lightroom 只有在 CLI Bridge 对对象级读取、写入、导出和状态绑定预览完成真机验证后，才会开放非 dry-run 自动写入。

## 架构与数据合同

```text
Lumenflow/
├── skills/                 # agent 工作流与判断边界
├── scripts/                # 扫描、预览、校验、执行、复核等确定性工具
├── knowledge/
│   ├── schemas/            # 可版本化 JSON 合同
│   ├── style_families/     # 可公开的去来源化语义知识
│   ├── style_cards/        # 手写 starter cards；私有生成物位于被忽略子目录
│   ├── raw_profiles/       # legacy/fallback profile 位置
│   └── source_records/     # 仅提交示例配置
├── adapters/               # Codex、Claude、OpenClaw 宿主适配说明
├── docs/                   # 架构、benchmark、roadmap 与工作流说明
└── tests/                  # 标准库 unittest 测试
```

关键合同：

| 合同 | 作用 |
| --- | --- |
| `CandidateManifest` | 记录候选 RAW、预览与失败，防止静默漏片 |
| `SelectionPlan v1` | 固化用途、顺序、角色、理由、备选和用户确认状态 |
| `PreviewArtifact v1` | 绑定 RAW 指纹、起始编辑状态、命令和预览输出字节 |
| `BackendCapabilities v1` | 明确后端能力边界，未知或未验证能力默认拒绝 |
| `EditIntent v2` | 表达与编辑器无关的视觉目标和逐图判断 |
| `ExecutionPlan v1` | 保存编译后的 profile、输出边界与无 shell argv |
| `ExecutionReceipt v1` | 记录执行状态、RAW 前后指纹和输出指纹 |
| `ReviewResult v1` | 将接受/修订/拒绝判断绑定到实际输出字节 |

更详细的设计见 [`docs/architecture_notes.md`](docs/architecture_notes.md) 和 [`docs/portability.md`](docs/portability.md)。

## 风格知识库

Lumenflow 区分“可复用知识”和“私有来源证据”：

- `knowledge/style_families/*.json` 是去来源化的语义风格族，可提交、可检索。
- `knowledge/style_library_index.json` 是运行时公开检索入口。
- `knowledge/style_cards/tutorial_recipes/`、`tutorial_derived/` 和 `knowledge/private_provenance/` 保存本地证据与溯源，默认由 Git 忽略。

照片处理时，agent 先看目标照片，再选择语义风格卡，并根据当前照片推理具体参数。风格卡是指导，不是可以直接复制到所有照片的 preset。完整更新与检索规则见 [`docs/style_library_workflows.md`](docs/style_library_workflows.md)。

## 隐私与安全边界

Lumenflow 默认遵循以下边界：

- 不覆盖原始 RAW，不在用户未授权时修改 sidecar、Lightroom catalog、评分或集合。
- 选片提案不等于用户确认；未确认计划不能进入自动修图。
- 执行计划必须声明允许写入的输出根目录，并拒绝路径逃逸和已有输出覆盖。
- RAW、渲染结果、benchmark 语料、SQLite 任务状态和个人范例库应放在仓库外，或放在已忽略的 `runs/`、`tmp/`、`local/` 中。
- 本机配置、cookie、真实来源白名单、transcript、教程 recipe 和私有溯源映射不应提交。
- 个人范例库不保存 RAW/JPEG 像素、原始文件路径或授权引用；只接受最终 `accepted` 的编辑记录。
- Lightroom 和其他未验证后端采用 fail-closed 策略，不会因为检测到一个命令就开放写入。

提交前建议运行：

```bash
git status --short
git ls-files | grep -E 'lumenflow\.local\.json|(^|/)local/|(^|/)runs/|(^|/)tmp/'
```

第二条命令正常情况下不应输出任何内容。若曾经提交过真实凭据，仅从当前版本删除文件并不够；还需要轮换凭据并清理 Git 历史。

## 配置

[`config/lumenflow.local.example.json`](config/lumenflow.local.example.json) 是完整模板。常用字段：

| 字段 | 用途 |
| --- | --- |
| `photos.output_root` | 照片工作区和成片的默认根目录 |
| `workflow.task_store` | 本地任务、确认状态与幂等操作数据库 |
| `workflow.personal_example_store` | 仅保存最终接受编辑的本地范例库 |
| `tools.*` | 覆盖本机 `rawtherapee-cli`、`darktable-cli`、`lr`、`ffmpeg` 等命令路径 |
| `lightroom.*` | Lightroom 导出参数与严格的实验开关 |
| `asr.*` | 私有教程的字幕/语音识别缓存与模型配置 |
| `env.*` | 环境变量名称，不应直接写入密钥值 |

若未显式传入 `--output-dir`，照片输出会写入：

```text
<photos.output_root>/<源照片目录名>/
```

## 测试

项目测试使用 Python 标准库 `unittest`：

```bash
python -m unittest discover -s tests
```

当前主分支包含 166 个测试。部分用例会打印 dry-run 命令和 JSON 摘要，这是预期行为；测试不会处理真实照片。

改动 JSON 合同、执行器或安全边界时，还应运行：

```bash
python scripts/check_environment.py
python scripts/backend_capabilities.py rawtherapee
git diff --check
```

## 常见问题

### 它能脱离视觉模型独立完成审美选片吗？

不能，也不打算用固定评分器冒充审美判断。脚本会准备完整、可追踪的视觉材料；理解用途、比较照片和编排叙事由宿主模型完成。

### 为什么选片使用内嵌 JPEG，而修图预览另有 PreviewArtifact？

选片阶段需要快速、无副作用地浏览整个候选集，适合使用相机内嵌预览。修图阶段必须知道模型看到的是哪一份渲染和哪一个起始编辑状态，所以使用带指纹的状态绑定预览。

### 为什么 Lightroom 默认不能自动写入？

Lightroom 是有 catalog 和活动照片状态的交互式应用。只验证“命令成功”不足以证明写到了正确照片、没有覆盖并发手工修改、也没有重复操作。真机安全门通过前，Lumenflow 会拒绝非 dry-run 写入。

### 可以用 darktable 替代 RawTherapee 吗？

目前不能作为等价的一等后端。仓库提供隔离 RAW 导出探针和 legacy 命令路径，但还缺少状态绑定预览 provider、EditIntent 编译器和完整收据能力。

### 依赖检查通过，但某个可选流程仍不可用？

环境检查只把当前主照片路径的依赖标为必需。教程摄取、ASR、社交来源更新和 Lightroom 各有额外依赖，请查看对应 skill 和本机配置。

## 项目状态与路线图

已落地的主干包括：

- 用途驱动的主动选片、去重与编排。
- 用户确认门和仅处理确认照片的边界。
- 状态绑定预览、后端能力合同和 RawTherapee 意图执行链。
- 最多两轮的成片复核闭环。
- benchmark/回归合同与本地个人编辑范例库。
- 可公开的语义风格层与私有来源证据分离。

当前重点是扩大 RawTherapee 参数覆盖、完成 clean-clone/host packaging、验证真实 Lightroom 安全边界，并在满足 provider/compiler/receipt 条件后评估其他后端。详见 [`docs/roadmap.md`](docs/roadmap.md)。

## 参与贡献

欢迎提交 issue、设计讨论和 pull request。请保持当前架构边界：

1. 审美判断属于 agent，确定性扫描、校验和执行属于脚本。
2. 新后端必须先定义并验证能力合同，不能从“命令可执行”推断“安全可用”。
3. 新功能应补充测试；涉及合同变化时同步更新 schema 和文档。
4. 不要提交 RAW、成片、cookie、API key、真实来源清单、transcript 或个人数据库。
5. 提交 PR 前运行完整测试与 `git diff --check`。

仓库暂未提供正式贡献者指南或行为准则；在这些文件补齐前，请通过 GitHub issue 先讨论较大的设计变更。

## 许可证

当前仓库尚未包含 `LICENSE` 文件。代码公开可见并不自动授予复制、修改或分发权；维护者需要在正式接受外部使用与贡献前选择并添加开源许可证。
