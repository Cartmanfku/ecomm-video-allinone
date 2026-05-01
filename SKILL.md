---
name: ecomm-video-allinone
slug: ecomm-video-allinone
version: 1.2.1
displayName: DeskClaw 电商视频全能独立版
summary: 以单技能方式提供完整视频流水线；主 SKILL 负责总流程与执行规范，细分能力通过 7 个 SUB_SKILL 文档引导。
tags: deskclaw, video-pipeline, standalone, e-commerce, image-generation, video-generation
description: "DeskClaw 电商视频全能独立版：单技能安装即可使用。主 SKILL 负责编排和执行，细节规则请按 SUB_SKILL 文档分层查阅。"
license: Apache-2.0
compatibility:
  - Claude Code
  - Cursor
  - DeskClaw
allowed-tools: Read Write
metadata:
  deskhub:
    tier: 2
    category: "AI视频"
    tags: ["DeskClaw", "全流程", "独立技能", "SUB_SKILL"]
    emoji: "🚀"
    author: "DeskClaw"
    requires:
      env: []
      bins: []
      skills: []
    model_compatibility:
      min_model: "haiku"
    automation_level: "assisted"
    automation_type: "content"
    collection: "deskclaw-video-script-expert"
---

# DeskClaw 电商视频全能独立版

从脚本或产品信息一键生成完整视频资产包。这是单技能独立版编排器，端到端流程仅依赖本目录文档与脚本。

## 文档结构

- 主入口（当前文件）：
  - `SKILL.md`：总流程、执行规范、路由规则
- 子能力文档：
  - `docs/SUB_SKILLS_INDEX.md`
  - `docs/sub_skills/script-analysis.md`
  - `docs/sub_skills/grid-prompt.md`
  - `docs/sub_skills/video-prompt.md`
  - `docs/sub_skills/face-bypass.md`
  - `docs/sub_skills/long-video.md`
  - `docs/sub_skills/image-generation.md`
  - `docs/sub_skills/video-generation.md`
- 可执行脚本：
  - `scripts/image/*`
  - `scripts/video/*`


## SUB_SKILL 说明

本技能通过 `docs/sub_skills/*.md` 组织细分能力文档，不依赖外部 skill 安装。

**上游（领域知识 + 结构化输出）：**

| SUB_SKILL | 职责 | 本 Skill 中的阶段 |
|---|---|---|
| `script-analysis` | 脚本拆解为结构化单元/分镜 | Step 1 |
| `grid-prompt` | 生成宫格生图指令 | Step 3 |
| `video-prompt` | 生成逐秒视频描述 | Step 4 |
| `face-bypass` | 人脸过检方案 | Step 2（按需） |
| `long-video` | 长视频多段编排 | Step 0（按需） |

**下游（执行生成）：**

| 执行模块 | 职责 | 消费的输出字段 |
|---|---|---|
| `scripts/image/*` | 生成宫格图 | `image_gen_input` JSON |
| `scripts/video/*` | 生成视频 | `video_gen_input` JSON |

## 输入

### 有脚本模式（主要）

```json
{
  "raw_script_text": "客户已通过的脚本文本（含镜号、旁白、画面描述、时长等）"
}
```

可选字段：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `platform` | `douyin` | 目标平台 |
| `clean_screen_level` | `L1` | 净画面等级（L0/L1/L2） |
| `product_images` | `[]` | 产品参考图 |
| `tts_durations` | `[]` | 各镜号 TTS 精确时长（秒） |
| `grid_size` | `auto` | 宫格尺寸 |

### 无脚本模式（产品图 → 脚本 → 资产包）

```json
{
  "product_images": ["product.jpg"],
  "product_name": "电竞桌",
  "selling_points": ["L型转角", "升降功能", "理线槽"],
  "duration_target": 15,
  "platform": "douyin"
}
```

无脚本时系统先自动生成脚本（时长决定镜头数 → 镜头数决定宫格尺寸），再进入完整流程。

| 目标时长 | 建议镜头数 | 建议宫格 |
|---|---|---|
| 5-8s | 3-4 镜 | 4 格（2x2） |
| 10s | 5-6 镜 | 6 格（2x3） |
| 15s | 7-9 镜 | 9 格（3x3） |
| 20s | 10-12 镜 | 12 格（3x4） |
| 30s | 15-20 镜 | 16-25 格 |

## 全流程

```
完整脚本 / 产品信息
  │
  ▼ Step 0: 判断是否需要长视频编排（>15s → 拆单元）
  │
  ▼ Step 1: 脚本分析（判题 + 拆单元 + 判型 + 分镜）
  │         → 参考 docs/sub_skills/script-analysis.md
  │
  ▼ Step 2: 人脸检测（脚本是否涉及人物出镜？）
  │         → 参考 docs/sub_skills/face-bypass.md
  │
  ▼ Step 3: 生成宫格生图指令
  │         → 参考 docs/sub_skills/grid-prompt.md（每个单元/段各一套）
  │
  ▼ Step 4: 生成视频描述
  │         → 参考 docs/sub_skills/video-prompt.md（每个单元/段各一套）
  │
  ▼ Step 5: 轻量质检（5 项）
  │
  ▼ 输出完整资产包
```

## Step 5：轻量质检

| 检查项 | 判定规则 | 失败处理 |
|---|---|---|
| `ORDER_GAP` | P1 到 P{N} 连续、无跳号 | 补齐缺失格 |
| `ACTION_MISSING` | 每个时间段有可执行动作 | 补充动作词 |
| `DRIFT` | 是否偏离脚本主题 | 回拉到原主题 |
| `TEXT_OVERLOAD` | 净画面是否合规 | 删除多余文字描述 |
| `PROMPT_TOO_LONG` | 视频描述是否超过合理长度 | 精简冗余句 |

质检通过即输出；不通过则自动修正一轮后输出。

## 输出格式

### 短视频（<=15s，单单元）

```json
{
  "script_info": {
    "brand": "品牌名",
    "topic": "大容量保温杯",
    "product_category": "水杯",
    "style_anchor": "写实商业摄影",
    "total_duration": 15,
    "total_units": 1,
    "total_asset_packages": 1
  },
  "global_materials": [
    { "id": "G1", "name": "产品正面高清图", "source": "客户提供", "used_in": [1] }
  ],
  "units": [
    {
      "unit_id": "unit_01",
      "shot_ids": [1, 2, 3, 4, 5, 6, 7],
      "tts_duration": 15,
      "segments": [
        {
          "segment_id": "full",
          "time_range": "0-15s",
          "grid_size": "3x3",
          "image_gen_input": {"prompt":"以保温杯为主体，生成一个3x3的九宫格图片...","model":"nano2","aspect_ratio":"16:9","resolution":"1K"},
          "video_gen_input": {"prompt":"这是大容量保温杯的15秒电商广告...","model":"fast","aspect_ratio":"16:9","duration":15}
        }
      ],
      "input_materials": [
        { "name": "产品正面图", "global_id": "G1", "panels": ["P3", "P5", "P9"] }
      ]
    }
  ]
}
```

### 长视频（>15s，多单元）

```json
{
  "script_info": {
    "brand": "品牌名",
    "total_duration": 129,
    "total_units": 8,
    "total_asset_packages": 11
  },
  "global_materials": [
    { "id": "G1", "name": "创始人半身照", "source": "客户提供", "used_in": [1,2,3,5,6,7,8] },
    { "id": "G2", "name": "产品瓶身图", "source": "客户提供", "used_in": [1,2,3,4,5,6,7,8] }
  ],
  "units": [
    {
      "unit_id": "unit_01",
      "shot_ids": [1],
      "tts_duration": 24,
      "segments": [
        {
          "segment_id": "seg_a",
          "time_range": "0-15s",
          "grid_size": "3x3",
          "image_gen_input": {"prompt":"段A九宫格指令...","model":"nano2","aspect_ratio":"16:9","resolution":"1K"},
          "video_gen_input": {"prompt":"段A逐秒描述...","model":"fast","aspect_ratio":"16:9","duration":15}
        },
        {
          "segment_id": "seg_b",
          "time_range": "15-24s",
          "grid_size": "2x3",
          "image_gen_input": {"prompt":"段B六宫格指令...","model":"nano2","aspect_ratio":"16:9","resolution":"1K"},
          "video_gen_input": {"prompt":"段B逐秒描述（承接前段）...","model":"fast","aspect_ratio":"16:9","duration":9},
          "continuation_from": "seg_a"
        }
      ],
      "input_materials": [...]
    }
  ],
  "consistency_refs": {
    "character_ref": {
      "type": "preprocessed",
      "method": "fishnet_prompt",
      "description": "渔网袜 prompt 自动处理"
    },
    "product_ref": "产品参考图描述",
    "scene_ref": "场景参考图描述"
  },
  "recommended_method": "chain_extend"
}
```

## 常见场景映射

| 用户说法 | 执行动作 |
|---|---|
| "把脚本拆成宫格" | 自动选宫格尺寸，输出 image_gen_input + video_gen_input |
| "用 4 格就够了" | 强制 2x2 布局 |
| "要详细点，用 25 格" | 强制 5x5 布局 |
| "扔脚本直接出提示词" | 自动选尺寸，默认走 auto |
| "脚本太长，超过 15 秒" | 拆单元，每单元独立出资产包 |
| "只要生图指令，不要视频描述" | 只输出 image_gen_input |
| "我有产品图，没有脚本" | 先生成脚本，再走全流程 |

## 下游执行

本 Skill 输出的资产包中，每个 segment 都包含 `image_gen_input` 和 `video_gen_input` 两个 compact JSON，可直接传给本目录脚本执行。

### 执行流程

```
资产包输出
  │
  ▼ 1. 取 image_gen_input → 传给 scripts/image/*
  │    submit.py → poll_until_done.py → download.py → 得到宫格图
  │
  ▼ 2. 将宫格图路径填入 video_gen_input.image_url
  │
  ▼ 3. 取 video_gen_input → 传给 scripts/video/*
  │    submit.py → poll_until_done.py → download.py → 得到视频
  │
  ▼ 4. 长视频：按段重复，链式续接时后段 image_url 引用前段结果
```

### 短视频（<=15s）

```bash
python scripts/image/submit.py '<image_gen_input的compact JSON>'
python scripts/image/poll_until_done.py <task_id>
python scripts/image/download.py '<url>' '<name>'

python scripts/video/submit.py '<video_gen_input的compact JSON，补上image_url>'
python scripts/video/poll_until_done.py <task_id>
python scripts/video/download.py '<url>' '<name>' '' '<task_id>'
```

### 长视频（>15s）

按 segment 顺序（链式续接）或并行（共享锚定）执行上述流程。详见 `docs/sub_skills/long-video.md`。


