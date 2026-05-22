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

## 核心组件

### 1. 照片处理 skill

职责：

1. 扫描用户指定目录里的 RAW 照片。
2. 识别用户已经标记/筛选的照片。
3. 读取风格库。
4. 让 agent 自主判断每张照片适合什么风格。
5. 调用 RawTherapee / darktable CLI 执行处理。
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
│   ├── read_xmp_rating.py
│   ├── render_raw.py
│   └── write_processing_report.py
└── docs/
```

不保留产品化 CLI 和 Python package 入口。需要复用的能力沉到 `scripts/`，由 skill 编排调用。平台差异放进 `adapters/`，不要渗透到 `knowledge/` 和通用脚本。

## 落地阶段

### Phase 1：照片处理 skill 最小闭环

目标：用户对任意受支持 agent 说“帮我处理某个目录的照片”，agent 能跑完整流程。

范围：

- 创建 `skills/develop-photos/SKILL.md`
- 创建 `knowledge/style_cards/` 和 `knowledge/raw_profiles/`
- 脚本支持：
  - 扫描 RAW
  - 读取已筛选照片
  - 调用修图 CLI
  - 写处理报告
- 先不接社交媒体和视频教程

验收：

```text
用户输入：帮我处理 /photos/trip 里的照片，输出到 /photos/output
Agent 行为：
1. 使用 develop-photos skill
2. 扫描 RAW
3. 根据现有风格库选择风格
4. 调用 RawTherapee / darktable CLI
5. 输出 JPG
6. 生成 processing_report.md
```

### Phase 2：风格库文件格式稳定

目标：让 skill 能长期复用风格知识。

范围：

- 定义 style card JSON schema
- 定义 tutorial recipe JSON schema
- 定义 source record JSON schema
- 写 5 个初始风格卡
- 将现有 `metadata/style_library.json` 拆成独立风格卡文件

验收：

- 照片处理 skill 只依赖 `knowledge/`
- 新增一个风格卡不需要改代码

### Phase 3：视频教程入库 skill

目标：先做教程入库，因为它比社媒图片更容易转成调色步骤。

范围：

- 创建 `skills/learn-styles/SKILL.md`
- 支持用户提供 YouTube/Bilibili 视频链接或字幕文件
- Agent 提取教程中的调色步骤
- 写入 `knowledge/tutorial_recipes/`
- 可选地更新或生成 style card

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

目标：从指定摄影师账号定期拉取公开内容，沉淀风格卡。

范围：

- X 先行，Instagram 后置
- 使用账号白名单，不做任意平台抓取
- 保存来源链接、文本、图片摘要、视觉风格描述
- 反推风格特征并合并到 style card

验收：

```text
定时任务定期运行：
1. 拉取白名单摄影师新内容
2. 分析风格
3. 更新 knowledge/source_records/
4. 更新 knowledge/style_cards/
```

### Phase 5：定时自动更新

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

## 非目标

短期不做：

- Web UI
- 完整照片管理系统
- 复杂数据库
- 大规模社媒爬虫
- 从零训练风格模型
- 替代 Lightroom / darktable 的完整编辑体验

短期只做各类 agent host 都能稳定调用的技能化工作流。
