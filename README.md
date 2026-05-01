# DeskClaw 电商视频全能独立版

`ecomm-video-allinone` 是一个可独立发布的电商视频生产技能。  
安装这一个目录，即可完成从脚本拆解、宫格生图、视频提示词到最终图片/视频下载的完整流程。

**平台说明：** 本技能**目前仅支持在 DeskClaw 中安装与使用**（含其提供的技能安装入口、账号与工作区、NodeStudio 网关等配套能力）。其他客户端或独立运行环境不在当前支持范围内。

## 关于 DeskClaw

[DeskClaw](https://deskclaw.me/) 是面向桌面的 AI 全能助手产品，定位为 **「Worker，not Tools」**：不是偶尔问一句就走的「网友式工具」，而是长期驻留、可协作完成工作的 **「同事」**；官网也强调其 **桌面宠物形态** 与一体化助手体验。本技能（`ecomm-video-allinone`）在 **DeskClaw** 内作为 **电商视频生产** 的独立能力包使用，与账号、工作区、NodeStudio 等 DeskClaw 侧配置自然衔接。

## 适用场景

- 电商短视频（5s/10s/15s）快速出片
- 长视频（>15s）拆段与一致性生成
- 脚本直出资产包（`image_gen_input` + `video_gen_input`）
- 真人出镜场景的人脸过检处理

## 核心能力（8 合 1）

- 脚本拆解：`script-analysis`
- 宫格提示：`grid-prompt`
- 视频提示：`video-prompt`
- 人脸过检：`face-bypass`
- 长视频编排：`long-video`
- 图片执行：`scripts/image/*`
- 视频执行：`scripts/video/*`

## 目录结构

- 主编排入口：`SKILL.md`
- 子能力索引：`docs/SUB_SKILLS_INDEX.md`
- 子能力文档：
  - `docs/sub_skills/script-analysis.md`
  - `docs/sub_skills/grid-prompt.md`
  - `docs/sub_skills/video-prompt.md`
  - `docs/sub_skills/face-bypass.md`
  - `docs/sub_skills/long-video.md`
  - `docs/sub_skills/image-generation.md`
  - `docs/sub_skills/video-generation.md`
- 执行脚本：
  - `scripts/image/{submit,poll,poll_until_done,download,models}.{py,sh}`
  - `scripts/video/{submit,poll,poll_until_done,download,models}.{py,sh}`

## 标准工作流

1. 输入脚本（或产品信息）
2. 生成结构化分镜（units/segments/sub_shots）
3. 输出宫格生图输入 `image_gen_input`
4. 输出视频生成输入 `video_gen_input`
5. 执行图片脚本拿到宫格图本地路径
6. 把宫格图路径填入 `video_gen_input.image_url`
7. 执行视频脚本拿到最终视频本地路径

## 快速使用

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

- Token 自动读取：`~/.deskclaw/deskclaw-settings.json` 或 `NODESTUDIO_TOKEN`
- API 地址默认：`https://nostudio-api.deskclaw.me`，可用 `NODESTUDIO_URL` 覆盖
- 下载目录默认：workspace 下 `outputs/`
- 安全限制：`download.py` 的 `output_dir` 仅允许写入 `workspace/outputs` 子目录

## 发布说明（源码仓库）

- 技能入口：`SKILL.md`
- 许可证：`LICENSE`（Apache License 2.0）
- 源码可托管于 GitHub 等仓库；**安装与运行仍以 DeskClaw 为准**（见上文「平台说明」）。
- 仓库辅助文件：`.gitignore`（忽略缓存、虚拟环境、本地产物等）、`.gitattributes`（换行与文本类型）、`.editorconfig`（编辑器基础约定）。
- 建议发布前自检：
  - 文档路径是否仍指向 `scripts/image/*` 与 `scripts/video/*`
  - 示例命令可直接运行

