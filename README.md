# Lumenflow

Portable photo styling skills for AI agents.

面向 AI agent 的个人 RAW 照片自动处理与风格学习 skills。

```text
两个通用 agent skills + 一个本地风格知识库 + 少量可复用脚本 + 平台适配层
```

目标工作流：

1. 用户对 agent 说：“帮我处理某个目录里的照片”。
2. Agent 使用照片处理 skill 扫描 RAW、识别已筛选照片。
3. Agent 结合风格库、照片预览和自主判断选择调色方向。
4. Agent 为每张照片生成具体 `adjustment_plan.json` 参数，并判断是否需要裁剪二次构图。
5. Skill 将调色计划转成临时 RawTherapee `.pp3` 并导出处理后的图片。
6. Agent 复核首轮输出，必要时生成修订计划再渲染。
7. 输出处理记录，方便用户复盘每张图用了什么风格、判断理由、构图决策和参数。
8. 定时任务使用风格库更新 skill，从社交媒体和视频教程里更新风格库。

## MVP

第一阶段先做 skill 的本地处理闭环：

- 暂不接入社交平台。
- 内置 5 个手写风格卡，形成最小知识库。
- 支持扫描指定目录的 RAW，并识别已筛选/标记照片。
- 让 agent 根据风格库、照片预览和照片内容选择处理风格。
- 让 agent 生成每张照片的动态调色计划，而不是固定套用 profile。
- 让 agent 在 plan 中记录裁剪判断，并在渲染后复核输出、必要时二次修改。
- 通过 RawTherapee CLI 优先渲染导出；darktable CLI 作为 legacy fallback。
- 输出处理后的图片和 Markdown 处理记录。

## 项目结构

```text
lumenflow/
├── skills/
│   ├── develop-photos/          # 用户主动要求处理照片时使用
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

计划拆成两个 skill：

- `develop-photos`：扫描指定目录，筛选 RAW，生成预览，由 agent 看图选择风格并生成动态参数，调用修图 CLI，输出图片和处理记录。
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

`config/lumenflow.local.json` 已加入 `.gitignore`。当前用于放置照片处理输出根目录、Bilibili cookie 文件路径、FunASR Python 路径、ASR 输出/缓存路径、模型名和本机工具命令名。教程来源白名单使用本地 `knowledge/source_records/tutorial_sources.json`，该文件也被忽略；公开仓库只提交 `knowledge/source_records/tutorial_sources.example.json`。

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
- ExifTool：读取元数据和辅助验证。
