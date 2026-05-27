# 版本更新记录

本文件记录 `ecomm-video-allinone` 的版本变更。版本号与 `SKILL.md` 中的 `version` 字段保持一致。

---

## [1.3.0] — 2026-05-27

### 新增

- **SUB_SKILL `video-analysis`**：合并 `content-video-analysis-script` v1.2.3，支持参考视频 / 抖音链接 上传拆解，输出原视频脚本或仿写脚本
- **`scripts/video-analysis/main.py`**：视频拆解与脚本生成执行入口（`advance_workflow`、抖音抓取下载、拆解轮询等）
- **根目录 `requirements.txt`**：统一声明 Python 依赖（`requests`、`yt-dlp`）
- **`docs/ONBOARDING.md`**：三种使用方式新用户引导（直接脚本 / 参考视频 / 产品图卖点）
- **`SKILL.md` ONBOARDING 摘要**：Agent 可根据用户材料自动识别入口，无需手动选模式

### 变更

- SUB_SKILL 数量由 7 个扩展为 **8 个**（新增 `video-analysis`）
- 主编排流程增加「参考视频拆解」入口分支：`script_text` → `raw_script_text` → Step 0–5
- 新增「有视频模式」输入契约与常见场景映射
- `README.md` 标准工作流重组为方式 1 / 2 / 3，与环境依赖说明对齐

### 说明

- `scripts/image/*`、`scripts/video/*` 仍仅依赖 Python 标准库
- 抖音相关能力需 `pip install -r requirements.txt`；`curl` 为可选系统工具（无则降级为 `requests`）

---

## [1.2.1] — 2026-05-27

### 新增

- 单技能独立版首发：安装本目录即可使用完整电商视频流水线
- **7 个 SUB_SKILL 文档**：`script-analysis`、`grid-prompt`、`video-prompt`、`face-bypass`、`long-video`、`image-generation`、`video-generation`
- **`scripts/image/*`**：NodeStudio 宫格图 submit / poll / download
- **`scripts/video/*`**：NodeStudio 视频 submit / poll / download
- 两种输入模式：**有脚本**（`raw_script_text`）、**无脚本**（产品图 + 卖点自动生成脚本）
- Step 0–5 主编排：长视频拆段 → 脚本分析 → 人脸过检 → 宫格指令 → 视频描述 → 轻量质检
- 资产包输出：`image_gen_input` + `video_gen_input` compact JSON，可直接传给执行脚本

### 说明

- 兼容 DeskClaw / Cursor / Claude Code
- Token 自动读取 `~/.deskclaw/deskclaw-settings.json` 或 `NODESTUDIO_TOKEN`
