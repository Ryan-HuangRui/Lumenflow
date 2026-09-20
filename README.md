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
5. Agent 为每张照片生成具体 `adjustment_plan.json` 参数，并判断是否需要裁剪二次构图。
6. Skill 将调色计划转成修图引擎可执行的参数并导出处理后的图片。
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
│   ├── style_families/          # 可提交、去来源化的可复用风格知识
│   ├── style_cards/             # 手写风格卡与私有教程中间产物
│   │   ├── tutorial_recipes/     # 私有 recipe 与 transcript
│   │   └── tutorial_derived/     # 私有视频级证据卡，不参与运行时检索
│   ├── private_provenance/      # 私有来源映射，Git 忽略
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

## 风格知识结构

教程来源进入风格库后分成公开知识层和私有证据层：

- 可复用知识：`knowledge/style_families/*.json`，按语义家族合并，供检索、场景匹配和调色推理；不含视频 ID、标题、URL、转写原句或时间戳。
- 检索入口：`knowledge/style_library_index.json`，只索引可复用知识，可随代码提交。
- 私有中间证据：`knowledge/style_cards/tutorial_recipes/` 与 `knowledge/style_cards/tutorial_derived/`，保留转写、分类和审计所需信息，但不参与照片处理时的运行时检索。
- 私有溯源：`knowledge/private_provenance/style_source_map.json`，把语义知识映射回来源，仅用于本地审计并由 Git 忽略。

公开知识只保留跨照片可复用的视觉特征、适用/避用场景、操作顺序、参数推理策略和聚合计数。第三方教程的 transcript、recipe、视频级证据卡和来源映射继续由 `.gitignore` 排除。

照片处理时，agent 根据目标照片直接选择一张可复用语义知识卡。具体参数始终由 agent 看目标照片后写入 `adjustment_plan.json`，不读取私有视频证据，也不把教程参数当作固定 preset。

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
