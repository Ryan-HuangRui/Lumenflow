# Lumenflow

Portable photo styling skills for AI agents.

面向 AI agent 的个人 RAW 照片自动处理与风格学习 skills。

```text
三个照片工作流 agent skills + 一个本地风格知识库 + 少量可复用脚本 + 平台适配层
```

目标工作流：

1. 用户对 agent 说：“帮我处理某个目录里的照片”。
2. `curate-photos` 扫描 RAW、生成联系表，由 agent 使用视觉推理按用途选片并编排顺序。
3. 用户确认选片方案后，`develop-photos` 只处理确认照片。
4. Agent 结合风格库、照片预览和自主判断选择调色方向。
5. Agent 为每张照片生成编辑器无关的 `EditIntent v2`，并判断是否需要裁剪二次构图。
6. Skill 将意图编译为后端专用 `ExecutionPlan`，执行后输出可验证的 `ExecutionReceipt`。
7. Agent 复核首轮输出，必要时生成修订计划再渲染。
8. 输出处理记录，方便用户复盘选片、编排、风格、构图和参数决策。
9. 定时任务使用风格库更新 skill，从社交媒体和视频教程里更新风格库。

## MVP

第一阶段先做 skill 的本地处理闭环：

- 暂不接入社交平台。
- 内置 5 个手写风格卡，形成最小知识库。
- 支持扫描指定目录的 RAW、按拍摄日期限定候选集、生成预览和联系表。
- 让 agent 使用模型视觉能力按用途去重、选片、分配叙事角色并编排顺序，用户确认后再进入修图。
- 让 agent 根据风格库、照片预览和照片内容选择处理风格。
- 让每张开发预览通过 `PreviewProvider` 生成版本化 `PreviewArtifact`，绑定 RAW 内容、实际起始 profile/sidecar 状态和输出文件指纹。
- 让 agent 生成每张照片的动态调色计划，而不是固定套用 profile。
- 让 agent 在 plan 中记录裁剪判断，并在渲染后复核输出、必要时二次修改。
- 通过 RawTherapee CLI 优先渲染导出；darktable CLI 作为 legacy fallback；Lightroom Classic 可作为可选交互式处理引擎。
- 输出处理后的图片和 Markdown 处理记录。

## 项目结构

```text
lumenflow/
├── skills/
│   ├── develop-photos/          # 用户主动要求处理照片时使用
│   ├── curate-photos/           # 按用途主动选片、去重与编排
│   └── learn-styles/            # 定时任务或用户主动更新风格库时使用
├── knowledge/
│   ├── style_families/          # Layer 1 风格/方法家族，用于检索
│   ├── style_cards/             # 手写风格卡、教程 recipe 与 Layer 2 视频变体卡
│   │   ├── tutorial_recipes/     # 调色教程转写后的 recipe 与 transcript
│   │   └── tutorial_derived/     # Layer 2 视频级风格卡
│   ├── style_library_index.json # 风格库检索入口
│   ├── source_records/           # 社媒/教程来源记录
│   ├── raw_profiles/            # legacy/fallback RawTherapee profile
│   └── schemas/                 # adjustment_plan 等 JSON 合同
├── adapters/                     # Codex / Claude / OpenClaw 等平台适配说明
├── scripts/                      # skill 可调用的小工具脚本
└── docs/                         # 设计说明、roadmap 和 architecture notes
```

## Skill 设计

照片工作流拆成三个主要 skill：

- `curate-photos`：扫描候选 RAW、提取相机内嵌预览、生成联系表，由 agent 直接使用视觉推理理解用途、去除废片/重复片、选择并编排，输出待用户确认的 `selection_plan.json`。
- `develop-photos`：只处理用户已确认或直接指定的 RAW，由 agent 看图选择风格并生成动态参数，调用修图 CLI，输出图片和处理记录。
- `learn-styles`：从用户批准的教程来源更新本地私有风格库。

CLI 只作为调试和脚本复用入口，不是主交互界面。

## 风格库两层结构

教程来源进入风格库后固定分成两层：

- Layer 1：`knowledge/style_families/*.json`，用于检索、场景匹配和过滤。这里包含视觉风格家族，也包含方法/工具/非风格参考家族。
- Layer 2：`knowledge/style_cards/tutorial_derived/*.json`，一条成功视频对应一张视频级风格卡。
- 教程 recipe：`knowledge/style_cards/tutorial_recipes/*.json`，作为生成 Layer 2 卡片的来源证据。
- 检索入口：`knowledge/style_library_index.json`，agent 先读它，再决定读取哪些 Layer 1/Layer 2 文件。

这些教程派生文件是本地生成的私有数据，默认被 `.gitignore` 排除。公开仓库只提交生成脚本、schema、空目录占位和 `*.example.*` 模板，不提交从第三方教程生成的 transcript、recipe、视频级风格卡或 family index。

照片处理时，agent 先根据照片内容选择 Layer 1 `style_family`，再读取匹配的 Layer 2 视频变体作为调色思路。具体参数始终由 agent 看目标照片后写入 `adjustment_plan.json`，不把教程参数当作固定 preset。

更新和检索的固定流程见 `docs/style_library_workflows.md`。

## 本机配置

机器相关路径不写进可提交配置。复制模板后在本机填写：

```bash
cp config/lumenflow.local.example.json config/lumenflow.local.json
```

`config/lumenflow.local.json` 已加入 `.gitignore`。当前用于放置照片处理输出根目录、Bilibili cookie 文件路径、豆包 ASR skill/私有配置路径、FunASR Python 路径、ASR 输出/缓存路径、模型名、本机工具命令名和 Lightroom 导出参数。ASR 顺序为平台字幕、豆包、FunASR。教程来源白名单使用本地 `knowledge/source_records/tutorial_sources.json`，该文件也被忽略；公开仓库只提交 `knowledge/source_records/tutorial_sources.example.json`。

照片处理默认输出到 `photos.output_root/<原照片所属目录名>/`。例如源文件位于 `negative_raw/2026五一港珠澳/P1034473.RW2` 时，最终图会进入 `photos.output_root/2026五一港珠澳/`。

## 脚本定位

`scripts/` 下的脚本只作为 skill 的工具函数，不是主交互界面。

典型调用会由 agent host 编排：

```text
用户请求
↓
Agent host 选择 skill
↓
skill 读取 knowledge/
↓
skill 按需调用 scripts/
↓
输出图片和处理记录
```

## 外部工具

计划依赖的本地工具：

- RawTherapee CLI：第一版主要 RAW 渲染引擎，使用 agent 生成的临时 `.pp3` profile。
- darktable CLI：备选渲染引擎，也可用于更强的 lighttable 筛选/标记工作流。
- Lightroom CLI：可选交互式引擎，要求 Lightroom Classic 已打开、Lightroom CLI Bridge 插件已启动，且目标照片已在 catalog 中。
- ExifTool：读取元数据和辅助验证。

## 预览合同

`scripts/create_previews.py` 默认使用 RawTherapee `PreviewProvider`。输出的
`preview_manifest.json` 不再只是文件路径列表；每一项都是
`lumenflow.preview_artifact.v1`，包含：

- RAW 的 SHA-256 与字节数。
- 实际参与预览的基础 profile 和同名 `.pp3` sidecar 内容指纹。
- 可复算的 `starting_state_hash` 和 `complete` / `partial` 完整度。
- 执行命令、状态以及成功输出的 SHA-256。

这使 agent 后续生成的编辑意图能够明确引用“看过的是哪张照片、基于什么起始状态”。
兼容字段 `source`、`preview`、`command` 和 `status` 仍然保留。

Lightroom 预览当前保持 fail-closed。只有 Bridge 同时声明并验证
`safe_object_develop_read` 和 `verified_state_bound_preview`，Lumenflow 才会越过预检；
完整的 Lightroom 状态绑定适配器仍需真机探针后实现。

## 后端能力合同

`scripts/backend_capabilities.py` 输出严格的
`lumenflow.backend_capabilities.v1` 合同。每项能力只有三种状态：
`supported`、`unsupported` 或 `unverified`；调用方必须通过 `require()` 显式检查，
不能把“命令存在”推断成“能力安全可用”。

```bash
python3 scripts/backend_capabilities.py rawtherapee
python3 scripts/backend_capabilities.py darktable
python3 scripts/backend_capabilities.py lightroom
python3 scripts/backend_capabilities.py lightroom --probe
```

当前合同明确区分：RawTherapee 的一等预览/渲染能力、darktable 的 legacy-only
命令路径，以及 Lightroom 必须由运行中 Bridge 证明确切读取、写入、导出和预览能力的
动态边界。未知能力、明确不支持的能力和尚未验证的能力分别返回不同的结构化错误码。

darktable 必须通过独立的真实 RAW 隔离导出探针，不能仅凭命令存在就升级能力：

```bash
python3 scripts/darktable_probe.py \
  --raw /photo-source/sentinel.NEF \
  --output-dir /photo-output/darktable-probe \
  --report-output /photo-output/darktable-probe/report.json
```

探针使用临时配置、临时缓存、内存 library，并强制 `write_sidecar_files=never`；只有导出
成功、RAW 与 sidecar 均未变化、输出可计算指纹时才返回 `passed`。本机实测安装状态及
后端升级门槛见 [docs/darktable_backend_spike.md](docs/darktable_backend_spike.md)。

## EditIntent 与执行收据

新主路径使用三个分离合同：

- `lumenflow.edit_intent.v2`：模型表达用途、风格、全局调整、构图和局部调整需求，不含编辑器命令。
- `lumenflow.execution_plan.v1`：编译器根据后端能力生成 profile、输出路径和无 shell 的 argv。
- `lumenflow.execution_receipt.v1`：执行器记录每个操作状态、RAW 前后指纹、输出指纹和失败原因。

当前首个编译器覆盖 RawTherapee 的全局曝光、亮度、对比度、高光恢复、阴影提升、
黑位、饱和度、白平衡和像素裁剪。编译阶段不写文件；执行阶段要求调用方显式提供
允许写入的输出根目录，并再次验证 RAW 指纹、能力合同、profile 内容、路径边界和完整命令。

```bash
python3 scripts/edit_intent.py compile intent.json \
  --backend rawtherapee \
  --output-dir /photo-output/bangkok \
  --plan-output /photo-output/bangkok/execution_plan.json

python3 scripts/edit_intent.py execute /photo-output/bangkok/execution_plan.json \
  --allowed-output-dir /photo-output/bangkok \
  --receipt-output /photo-output/bangkok/execution_receipt.json \
  --dry-run
```

旧 `lumenflow.adjustment_plan.v1` 和 `scripts/render_adjustment_plan.py` 继续保留，作为兼容路径；
新功能不再向该合同加入后端特定字段。

## Lightroom 引擎

Lightroom 支持通过 fork 后的 `lightroom-cli` 接入。它不是无头 CLI 渲染器。当前自动写入采用 fail-closed 策略：只有运行中的插件通过版本、协议和能力握手，并明确声明对象级写入与导出结果已经过真机验证，非 dry-run 才会继续。

运行前需要：

1. Lightroom Classic 已启动。
2. `Lightroom CLI Bridge` 插件已安装并启动。
3. `lr system ping` 能返回 `pong: True`。
4. 要处理的 RAW 已在 Lightroom catalog 中。

`adjustment_plan.json` 可以在顶层或单个 variant 下声明 Lightroom photo id。真正执行时还必须提供由外层任务状态生成的 `base_state_hash` 和 `operation_id`；下面为了简化只展示修图内容：

```json
{
  "schema_version": "lumenflow.adjustment_plan.v1",
  "source": "/path/to/IMG_0001.DNG",
  "lightroom": {"photo_id": "123"},
  "variants": [
    {
      "variant_id": "best",
      "style_id": "clean_natural",
      "rationale": "Use Lightroom as the rendering engine.",
      "adjustments": {
        "exposure_compensation": 0.35,
        "saturation": -4,
        "temperature": 5400,
        "hsl": {
          "orange": {"saturation": -5, "luminance": 8},
          "green": {"hue": -10, "saturation": -20}
        },
        "tone_curve": {
          "parametric": {"shadows": -8, "lights": 6},
          "point": [[0, 0], [64, 58], [128, 132], [255, 255]]
        },
        "color_grading": {
          "shadows": {"hue": 210, "saturation": 8},
          "highlights": {"hue": 42, "saturation": 10},
          "balance": 5
        },
        "calibration": {
          "blue": {"hue": -8, "saturation": 12}
        }
      },
      "composition": {
        "decision": "no_crop",
        "reason": "The source framing is already intentional."
      },
      "mask_decision": {
        "decision": "manual_recommendation",
        "reason": "The bright sky may need a local recovery pass, but Lightroom AI masks require overlay verification before execution.",
        "recommended_masks": [
          {
            "type": "sky",
            "rationale": "Recover bright sky detail without darkening the subject.",
            "settings": {
              "highlights": -35,
              "dehaze": 12
            }
          }
        ]
      }
    }
  ]
}
```

渲染命令：

```bash
python3 scripts/render_adjustment_plan.py output/plans/IMG_0001.adjustment_plan.json --engine lightroom
```

如果 plan 没有 `lightroom.photo_id`，非 dry-run 时会尝试用 `lr -o json catalog find-by-path <source>` 从 catalog 中解析照片 id。Lightroom 引擎把参数编译为绝对目标值，并通过 `lr develop apply-verified` 的预留安全契约执行，再调用 `lr export photo`。当前 Bridge 会对 `apply-verified` 明确返回 `CAPABILITY_NOT_VERIFIED`，且能力握手保持关闭，因此只能 dry-run；必须通过隔离 catalog 真机探针后才能放开。

任务、用途提案、用户冻结确认、catalog 照片实例、起始状态快照和幂等操作记录由 `scripts/task_store.py` 保存到本地 SQLite，默认路径为被 git 忽略的 `local/lumenflow_tasks.sqlite3`。这些工作流状态不进入单图 `adjustment_plan`。

Lightroom 路径的全局参数支持基础曝光/色温/质感参数，也支持 Lightroom-only 的 `hsl`、`color_mixer`、`tone_curve`、`color_grading`、`calibration`。这些高级参数会写入 Lightroom catalog，便于后续在 Lightroom 里继续调整；RawTherapee 路径目前不执行这些高级 Lightroom 字段。

当前 Lightroom AI mask 批处理路径默认禁用。现有 `lightroom-cli`/Bridge 的 `develop ai batch <type> --photos <photo_id>` 可能在 Develop/Masking 上下文切换未完成时把 AI 蒙版写到错误照片。能力握手未通过期间，即使本地开启实验性蒙版开关，非 dry-run 仍会被全局安全闸门拒绝。
