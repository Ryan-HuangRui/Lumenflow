# Lumenflow

Portable photo styling skills for AI agents.

面向 AI agent 的个人 RAW 照片自动处理与风格学习 skills。

```text
两个通用 agent skills + 一个本地风格知识库 + 少量可复用脚本 + 平台适配层
```

目标工作流：

1. 用户对 agent 说：“帮我处理某个目录里的照片”。
2. Agent 使用照片处理 skill 扫描 RAW、识别已筛选照片。
3. Agent 结合风格库和自主判断选择调色方向。
4. Skill 调用 darktable CLI 或 RawTherapee CLI 导出处理后的图片。
5. 输出处理记录，方便用户复盘每张图用了什么风格和参数。
6. 定时任务使用风格库更新 skill，从社交媒体和视频教程里更新风格库。

## MVP

第一阶段先做 skill 的本地处理闭环：

- 暂不接入社交平台。
- 内置 5 个手写风格卡，形成最小知识库。
- 支持扫描指定目录的 RAW，并识别已筛选/标记照片。
- 让 agent 根据风格库和照片内容选择处理风格。
- 通过 darktable CLI 优先渲染导出；RawTherapee CLI 作为 `.pp3` profile 备选。
- 输出处理后的图片和 Markdown 处理记录。

## 项目结构

```text
lumenflow/
├── skills/
│   ├── develop-photos/          # 用户主动要求处理照片时使用
│   └── learn-styles/            # 定时任务或用户主动更新风格库时使用
├── knowledge/
│   ├── style_cards/             # 抽象后的风格卡
│   ├── tutorial_recipes/         # 调色教程转写后的 recipe
│   ├── source_records/           # 社媒/教程来源记录
│   └── raw_profiles/             # RawTherapee / darktable 可执行参数
├── adapters/                     # Codex / Claude / OpenClaw 等平台适配说明
├── scripts/                      # skill 可调用的小工具脚本
└── docs/                         # 设计说明、roadmap 和 handoff
```

## Skill 设计

计划拆成两个 skill：

- `develop-photos`：扫描指定目录，筛选 RAW，选择风格，调用修图 CLI，输出图片和处理记录。
- `learn-styles`：从 X 等社交媒体和 YouTube 等教程来源更新风格库。

CLI 只作为调试和脚本复用入口，不是主交互界面。

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

- darktable CLI：第一版主要 RAW 筛选/标记/渲染闭环。
- RawTherapee CLI：`.pp3` profile 备选渲染引擎。
- ExifTool：读取元数据和辅助验证。
