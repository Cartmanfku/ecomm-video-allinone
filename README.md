# DeskClaw 电商视频全能独立版

`ecomm-video-allinone` 是一个可独立发布的电商视频生产技能。  
安装这一个目录，即可完成从参考视频拆解、脚本拆解、宫格生图、视频提示词到最终图片/视频下载的完整流程。

**平台说明：** 本技能**目前仅支持在 DeskClaw 中安装与使用**（含技能安装入口、账号与工作区、NodeStudio 网关等）。文档标注兼容 Claude Code / Cursor 阅读编排规则，但安装与运行仍以 DeskClaw 为准。

## 关于 DeskClaw

[DeskClaw](https://deskclaw.me/) 是面向桌面的 AI 全能助手产品，定位为 **「Worker，not Tools」**：不是偶尔问一句就走的「网友式工具」，而是长期驻留、可协作完成工作的 **「同事」**；官网也强调其 **桌面宠物形态** 与一体化助手体验。本技能在 DeskClaw 内作为 **电商视频生产** 的独立能力包使用，与账号、工作区、NodeStudio 等配置自然衔接。

## 技能架构

高度结构化的 **AI 视频生产编排器（Orchestrator）**：1 个主编排文件 + 8 个子能力文档 + 3 组执行脚本，协同驱动完整流水线。

| 模块 | 子能力 | 核心职责 |
|---|---|---|
| 0 | `video-analysis` | 参考视频 / 抖音链接拆解，输出原脚本或仿写脚本 |
| 1 | `script-analysis` | 脚本拆解为结构化 unit / segment / sub_shots |
| 2 | `grid-prompt` | 生成 4/6/9/12/16/25 格宫格生图指令 |
| 3 | `video-prompt` | 生成逐秒视频描述与段间衔接 |
| 4 | `face-bypass` | 5 种真人出镜过检方案与决策树 |
| 5 | `long-video` | >15s 多段拆分与一致性保障 |
| 6 | `image-generation` | 宫格图 submit / poll / download |
| 7 | `video-generation` | 视频 submit / poll / download |
| — | `SKILL.md` 主编排 | 总流程、路由规则、5 项轻量质检 |

- 协议：Apache-2.0

## 功能亮点

### 智能脚本拆解（script-analysis）

- **旁白驱动分镜**：旁白讲痛点时画面不提前出现品牌；讲解决方案时产品才登场
- **时长控制**：以 TTS 精确时长为准；单单元 ≤15s，超长自动在旁白自然停顿处切分为段 A / 段 B
- **节奏分配**：快切 1–1.5s（产品快闪）、标准 1.5–2s（多数分镜）、慢动作 2.5–3s（倒水、涂抹等）

### 宫格生图（grid-prompt）

一次生图调用将整段所需分镜以宫格排布在同一张图上，锁定视觉风格、角色外观与场景一致性，再作为视频生成参考输入。支持 6 种规格，按子分镜数量自动选型；例如 9 格标准布局：P1–P3 开场（Hook + 痛点）→ P4–P6 中段（卖点证明）→ P7–P9 收束（结果 / 品牌 / CTA）。

### 逐秒视频描述（video-prompt）

生成含镜头运动（推/拉/摇/跟）、主体动作、情绪节奏的专业描述；长视频后段自动写明「承接前段」画面状态，保证续接上下文正确。

### 长视频编排（long-video）

模型单次最多生成 15s，长视频需拆段再组合：

- **链式续接（chain_extend）**：前段完整视频作为后段输入，运动/光线/构图自然继承，一致性最强，适合同人物全程出镜
- **共享锚定（shared_anchor）**：各段共享参考图，可并行生成，速度最快，适合产品展示、多场景切换

### 轻量质检

输出资产包前自动执行 5 项检查：`ORDER_GAP`（分镜连续）、`ACTION_MISSING`（动作可执行）、`DRIFT`（主题不偏离）、`TEXT_OVERLOAD`（净画面合规）、`PROMPT_TOO_LONG`（描述长度合理）；不通过则自动修正一轮。

## 商业价值

1. **降本**：省去场地、演员、摄影团队与后期等成本，单条商业短视频成本可降低 70% 以上
2. **提效**：制作周期从「天」级压缩至「分钟」级，中小卖家日均产出可从数条提升至数十条乃至上百条
3. **保质**：内置商业叙事逻辑、专业镜头语言与 5 项质检，输出具有稳定下限的工业级广告成片，直接赋能转化

## 目录结构

- 主编排入口：`SKILL.md`
- 新用户引导：`docs/ONBOARDING.md`
- 版本记录：`CHANGELOG.md`
- 子能力索引：`docs/SUB_SKILLS_INDEX.md`
- 子能力文档：`docs/sub_skills/*.md`
- 执行脚本：
  - `scripts/video-analysis/main.py`
  - `scripts/image/{submit,poll,poll_until_done,download,models}.{py,sh}`
  - `scripts/video/{submit,poll,poll_until_done,download,models}.{py,sh}`

## 标准工作流

根据你手头的材料，选 **一种** 方式开始

| # | 入口 | 你需要提供 | 一句话示例 |
|---|---|---|---|
| **1** | 直接输入脚本 | 已定稿脚本文本 | 「这是我的广告脚本，帮我拆宫格并出视频提示词」 |
| **2** | 参考视频拆解 | 视频文件 / 抖音链接 / `video_id` | 「分析这个参考视频，输出原脚本并继续生成资产包」 |
| **3** | 产品图生成脚本 | 产品图 + 名称 + 卖点 | 「产品：电竞桌；卖点：L 型转角、升降功能；做 15 秒抖音广告」 |

### 方式 1：从脚本出发

1. 输入脚本文本
2. 脚本分析 → 宫格生图指令 → 视频描述 → 质检
3. 输出 `image_gen_input` + `video_gen_input`
4. （可选）执行图片/视频脚本出片

### 方式 2：从参考视频出发

1. 输入参考视频 / 抖音链接 / `video_id`
2. `scripts/video-analysis/main.py` 拆解并输出 `script_text`
3. 将 `script_text` 作为 `raw_script_text` 进入方式 1 的流程

### 方式 3：从产品信息出发

1. 输入产品图 + 名称 + 卖点 + 目标时长
2. 自动生成脚本
3. 进入方式 1 的流程

## 快速使用

### 0) 参考视频拆解

```bash
python scripts/video-analysis/main.py '{"action":"advance_workflow","file_path":"media/ref.mp4","original_script":true}'
python scripts/video-analysis/main.py '{"action":"download_douyin_video","douyin_url":"https://v.douyin.com/xxxx/"}'
```

依赖：`pip install -r requirements.txt`

### 1) 图片生成

```bash
python scripts/image/submit.py "{\"prompt\":\"一只橘猫趴在窗台\",\"model\":\"seedream\"}"
python scripts/image/poll_until_done.py <task_id> 240
python scripts/image/download.py "<image_url_or_json_array>" "cat"
```

### 2) 视频生成

```bash
python scripts/video/submit.py "{\"prompt\":\"一只橘猫在阳光下伸懒腰\",\"model\":\"fast\",\"duration\":5,\"aspect_ratio\":\"16:9\"}"
python scripts/video/poll_until_done.py <task_id> 540
python scripts/video/download.py "<video_url>" "cat_video" "" "<task_id>"
```

### 3) 长视频（>15s）

- 推荐先按 `docs/sub_skills/long-video.md` 生成分段资产包
- 一致性优先用 `chain_extend`
- 速度优先用 `shared_anchor`

## 模型建议

- 图片默认：`seedream`
- 图片高质量：`wan2.7-image-pro`
- 视频默认：`fast`（Seedance 2.0 Fast）
- 视频高质量：`pro`
- 视频 1080p：`1.5-pro`

## 环境与安全

- Python 依赖：`pip install -r requirements.txt`
  - `requests`、`yt-dlp` — 仅 `scripts/video-analysis/*` 需要（抖音抓取/下载、HTTP API）
  - `scripts/image/*`、`scripts/video/*` — 仅用 Python 标准库，无需额外 pip 包
- 系统工具（可选）：`curl` — 抖音页面抓取与直链下载回退；无 curl 时会降级为 `requests`
- Token 自动读取：`~/.deskclaw/deskclaw-settings.json` 或 `NODESTUDIO_TOKEN`
- API 地址默认：`https://nostudio-api.deskclaw.me`，可用 `NODESTUDIO_URL` 覆盖
- 下载目录默认：workspace 下 `outputs/`
- 安全限制：`download.py` 的 `output_dir` 仅允许写入 `workspace/outputs` 子目录

## 发布说明（源码仓库）

- 技能入口：`SKILL.md`
- 版本记录：[`CHANGELOG.md`](CHANGELOG.md)
- 许可证：`LICENSE`（Apache License 2.0）
- 源码可托管于 GitHub 等仓库；**安装与运行仍以 DeskClaw 为准**
- 仓库辅助文件：`.gitignore`、`.gitattributes`、`.editorconfig`
- 建议发布前自检：
  - 文档路径是否仍指向 `scripts/video-analysis/*`、`scripts/image/*` 与 `scripts/video/*`
  - 示例命令可直接运行
