# SUB_SKILL: Video Analysis

分析并拆解已有参考视频（本地附件、已上传 `video_id`、HTTPS 临时地址或抖音链接），输出可用于后续流水线的 `script_text` / `raw_script_text`。

## 在本 Skill 中的位置

| 阶段 | 职责 | 下游 |
|---|---|---|
| 入口（按需） | 上传/接入视频 → 启动拆解 → 输出原视频脚本或仿写脚本 | `script-analysis`（Step 1） |

**典型链路：**

```
参考视频 / 抖音链接
  → video-analysis（本 SUB_SKILL）
  → 得到 script_text
  → 作为 raw_script_text 进入 script-analysis → grid-prompt → video-prompt → 生成
```

## 执行入口

统一通过 `scripts/video-analysis/main.py` 的 `run(params)` 调用：

```bash
python scripts/video-analysis/main.py '{"action":"run_workflow_plan"}'
python scripts/video-analysis/main.py '{"action":"advance_workflow","file_path":"media/ref.mp4","original_script":true}'
python scripts/video-analysis/main.py '{"action":"download_douyin_video","douyin_url":"https://v.douyin.com/xxxx/"}'
python scripts/video-analysis/main.py '{"action":"wait_for_analysis_complete","task_id":"task_xxx","video_id":"video_xxx"}'
python scripts/video-analysis/main.py '{"action":"get_original_video_script","video_id":"video_xxx"}'
```

依赖安装（抖音下载需要）：

```bash
pip install -r requirements.txt
```

## 输入

至少提供一种视频来源：

| 字段 | 说明 |
|---|---|
| `file_path` | 本地视频路径；消息中的 `media/...mp4` 会自动补全为 workspace 路径 |
| `video_id` | DeskClaw 已上传视频 ID，优先 `attach_uploaded_video` |
| `file_url` | HTTPS 临时视频地址 |
| `douyin_url` | 抖音链接（`douyin.com` / `iesdouyin.com` / `v.douyin.com`） |

常用控制字段：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `action` | `run_workflow_plan` | 执行动作，见下表 |
| `original_script` | `false` | 为 `true` 时跳过仿写，直接输出原视频脚本 |
| `rewrite_brief` | — | 仿写 Brief；仅用户明确要求仿写/改写时使用 |
| `state` | `{}` | 工作流状态，`advance_workflow` 自动推进时使用 |

## 输出

流程终点为 `script_ready`，返回：

| 字段 | 说明 |
|---|---|
| `script_text` | 可直接展示的分镜/口播脚本文本 |
| `script_preview` | 紧凑预览（镜头数、口播摘要等） |
| `next_action` | 建议下一步；终点为 `script_ready` |

**对接主编排：** 将 `script_text` 作为 `raw_script_text` 传入 Step 1（`script-analysis`），继续宫格生图与视频生成流程。

## 常用 action

| action | 说明 |
|---|---|
| `advance_workflow` | 自动读取登录态并推进上传、拆解、仿写、脚本预览 |
| `run_workflow_plan` | 返回完整步骤清单 |
| `upload_video` | 上传本地视频（≤50 MB，≤5 分钟） |
| `attach_uploaded_video` | 接入已上传 `video_id` |
| `fetch_douyin_video_data` | 抓取抖音页面结构化 `douyin_report` |
| `download_douyin_video` | 抓取页面 → yt-dlp/curl 下载 → 上传；**不返回 script_text** |
| `create_clone_script` | 创建 clone 草稿 |
| `start_analysis` | 启动 `/video/analyze` 拆解 |
| `wait_for_analysis_complete` | 长等待拆解完成（优先于反复 `monitor_analysis_task`） |
| `get_original_video_script` | 从真实拆解结果整理原视频脚本 |
| `rewrite_script` | 基于拆解结果仿写（需明确 `rewrite_brief`） |
| `get_script_preview` | 返回脚本预览与 `script_text` |

## 使用原则

- 自动读取 DeskClaw 本地登录态：`~/.openclaw/deskclaw_login_sessions.json`（`auth_token` / `refresh_token`）。
- 消息中已有视频附件时，**直接使用** `media/...mp4` 路径，或兜底读取 `~/.deskclaw/nanobot/workspace/media/.assets.db` 最新用户视频，不要重复询问上传。
- 已有 `video_id` 时优先 `attach_uploaded_video`，Agent 不重复上传。
- **严禁**仅根据抖音页面标题、描述、互动数据猜测原视频脚本；必须基于真实视频拆解证据（已下载视频、ASR/字幕、逐镜头拆解结果）。
- 用户要「原脚本 / 原视频脚本」时，拆解完成后必须调用 `get_original_video_script`，**不能**把 `rewrite_script` 结果当原脚本。
- 只有用户明确说「仿写 / 改写 / 复刻」并提供产品/主题信息时，才进入 `rewrite_script`。
- 等待拆解优先 `wait_for_analysis_complete`；`monitor_analysis_task` 仅短轮询。
- 面向用户只输出简短中文状态，不展示 token、headers 或长 JSON。

## 抖音链接流程

```
douyin_url
  → fetch_douyin_video_data（页面基础信息 + douyin_report）
  → download_douyin_video（yt-dlp 或 play_addr 直链 → 上传）
  → create_clone_script → start_analysis
  → wait_for_analysis_complete
  → get_original_video_script 或 rewrite_script
  → script_ready
```

`douyin_report` 仅作背景材料；`script_text` 必须来自真实视频拆解。

## 与主编排对接示例

拆解完成后，将输出接入现有流水线：

```json
{
  "raw_script_text": "<video-analysis 返回的 script_text>",
  "platform": "douyin",
  "product_images": []
}
```

然后按 `SKILL.md` 执行 Step 0–5（长视频编排 → 脚本分析 → 宫格 → 视频描述 → 质检 → 资产包）。

## 常见场景

| 用户说法 | 执行动作 |
|---|---|
| 「分析这个视频并出脚本」 | `advance_workflow` + `original_script: true` |
| 「仿写这个抖音视频」 | 先拆解 → 确认 `rewrite_brief` → `rewrite_script` |
| 「这是抖音链接，帮我拆解」 | `download_douyin_video` → 等待拆解 → `get_original_video_script` |
| 「拆解完继续生成新视频」 | 取 `script_text` 作为 `raw_script_text` 进入主编排 |
| 「只要原脚本，不要仿写」 | `original_script: true`，跳过 `rewrite_script` |

## API 与环境

- API 默认：`https://nostudio-api.deskclaw.me/api/v1`
- 登录态：`~/.openclaw/deskclaw_login_sessions.json`
- 抖音下载：`requests` + `yt-dlp`（见项目根目录 `requirements.txt`）
- 上传限制：50 MB、5 分钟以内
