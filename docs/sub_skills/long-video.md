# SUB_SKILL: Long Video

管理 15s 以上视频的多段拆分和一致性保障。当前视频生成模型单次最多生成 15s 视频，长视频需要拆段生成再组合。

## 下游对接

本 Skill 输出的每段 `image_gen_input` / `video_gen_input` JSON 可直接传给本技能内置脚本：

```bash
python scripts/image/submit.py '<image_gen_input>'
python scripts/video/submit.py '<video_gen_input>'
```

## 适用场景

- 视频总时长 > 15s
- 需要多段视频保持一致性（人物、产品、场景）
- 需要在"一致性"和"出片速度"之间做决策

## 两种一致性模式

### 模式 A：链式续接（一致性最强，推荐）

把前一段视频喂给视频生成模型，让它从完整运动轨迹（不是只看最后一帧）自然接着生。

```
1. 用"前段宫格图 + 前段 video_prompt"生成第 1 段（0-15s）
2. 把第 1 段视频 + "后段 video_prompt"喂回模型（视频延伸模式）
3. 模型分析第 1 段的运动/光线/构图轨迹，续接出第 2 段
4. 如有第 3 段，把前两段拼接后再喂回去续接
```

优势：
- 人物外观、光线、空间关系自动从前段继承
- 无需额外做一致性锚定
- 过渡最自然，看不出拼接痕迹

限制：
- 必须串行生成，总耗时 = 段数 x 单段耗时
- 前段质量不好，后段也会跟着不好

generation JSON 序列：
```json
// 第 1 段：宫格图生视频（image-to-video）
{"prompt":"<video_prompt_part1>","model":"fast","aspect_ratio":"16:9","duration":15,"image_url":"<grid_image_path>"}

// 第 2 段：视频续接（用前段下载的视频路径作为参考）
{"prompt":"<video_prompt_part2>，承接前段画面","model":"fast","aspect_ratio":"16:9","duration":15,"image_url":"<part1_last_frame_or_grid_image>"}
```

每段依次传给 `scripts/video/submit.py` → `scripts/video/poll_until_done.py` → `scripts/video/download.py`。

### 模式 B：共享参考图锚定（速度快，可并行）

所有段共享同一组参考图（人物/产品/场景），锚定到同一视觉基准。

```
1. 准备一致性参考图集：人物正面照、产品标准图、场景全景图（3-5 张）
2. 每段生成时都用 reference_images 参数传入这组参考图
3. 每段 video_prompt 开头写"角色与参考图保持一致，场景与参考图保持一致"
4. 各段独立生成，最后剪辑拼接
```

优势：
- 各段可并行生成，总耗时 ≈ 单段耗时
- 某段不满意可以只重生那一段

限制：
- 一致性依赖参考图质量
- 段间过渡需手动在剪辑时处理
- 光线/角度可能有细微差异

generation JSON（各段并行）：
```json
// 第 1 段
{"prompt":"<video_prompt_part1>，角色与参考图保持一致","model":"fast","aspect_ratio":"16:9","duration":15,"image_url":"<grid_image_part1>"}

// 第 2 段（可并行提交）
{"prompt":"<video_prompt_part2>，角色与参考图保持一致","model":"fast","aspect_ratio":"16:9","duration":15,"image_url":"<grid_image_part2>"}
```

各段 JSON 并行传给 `scripts/video/*` 执行。共享参考图通过 `scripts/image/*` 预先生成并下载到本地。

## 选哪种？

| 场景 | 推荐 | 原因 |
|---|---|---|
| 同一人从头到尾出镜 | A（链式） | 人脸一致性要求极高 |
| 产品展示，场景多次切换 | B（锚定） | 各段独立，不需帧级连续 |
| 前后有明确转场（淡入淡出） | B | 转场本身打断连续性 |
| 科普动画，前后衔接机制链路 | A | 动画需要视觉连续 |
| 赶时间，快速出片 | B | 可并行，速度翻倍 |

## 段间 video_prompt 衔接写法

**核心规则：后段开头必须对齐前段结尾的画面状态。**

```
// 前段结尾
...13-15s: 创始人手持产品微笑，镜头缓推到产品特写，停留收束

// 后段开头（从前段结尾状态接续）
这是第2段（15-30s），承接前段。角色和场景与前段保持完全一致。

0-2s: 从产品特写缓慢拉远，创始人手持产品回到中景，表情自然过渡
2-4s: ...
```

禁止做的事：
- 后段开头不能突然换场景或换人
- 后段不能重复前段已展示的内容
- 后段的 `@Tag` 引用必须和前段一致

## 执行流程

### 链式续接

1. 将前段 `image_gen_input` 传给 `scripts/image/*` → 下载宫格图
2. 将前段 `video_gen_input`（含宫格图 `image_url`）传给 `scripts/video/*` → 下载前 15s 视频
3. 将后段 `video_gen_input`（`image_url` 指向前段视频的最后一帧或新宫格图）传给 `scripts/video/*` → 下载后 15s
4. 重复直到全部段落生成完毕

### 共享锚定并行

1. 各段 `image_gen_input` 并行传给 `scripts/image/*` → 下载各段宫格图
2. 各段 `video_gen_input` 并行传给 `scripts/video/*` → 下载各段视频
3. 最后在剪辑软件中拼接

## 与人脸方案的组合

| 视频类型 | 人脸方案 | 续接方式 | 操作说明 |
|---|---|---|---|
| 30s 品牌广告，创始人出镜 | 形象克隆 | 链式续接 | APP 录分身 → 分身生视频 → 视频延伸 |
| 30s 远程代言人 | 风格转绘 | 链式续接 | 转绘 → 参考图 → 链式继承 |
| 30s 电商模特 | 渔网袜 prompt | 链式续接 | grid_prompt 自动处理 → 链式继承 |
| 45s 连续短剧 | 形象克隆或 ID 引用 | 链式续接 | 优先形象克隆 |
| 30s 产品展示无人脸 | 虚拟演员或无需 | 共享锚定 | 并行生成，速度快 |
| 30s 虚拟代言人 | AI 虚拟演员 | 链式续接 | 生成定妆照 → 链式续接 |

## 输出格式

当处理长视频时，输出包含多段信息：

```json
{
  "total_duration": 30,
  "segments": [
    {
      "segment_id": "seg_01",
      "time_range": "0-15s",
      "grid_size": "3x3",
      "image_gen_input": {"prompt":"前段宫格指令...","model":"nano2","aspect_ratio":"16:9","resolution":"1K"},
      "video_gen_input": {"prompt":"前段视频描述...","model":"fast","aspect_ratio":"16:9","duration":15}
    },
    {
      "segment_id": "seg_02",
      "time_range": "15-30s",
      "grid_size": "2x3",
      "image_gen_input": {"prompt":"后段宫格指令...","model":"nano2","aspect_ratio":"16:9","resolution":"1K"},
      "video_gen_input": {"prompt":"后段视频描述（承接前段）...","model":"fast","aspect_ratio":"16:9","duration":15},
      "continuation_from": "seg_01"
    }
  ],
  "consistency_refs": {
    "character_ref": "角色参考图描述",
    "product_ref": "产品参考图描述",
    "scene_ref": "场景参考图描述"
  },
  "recommended_method": "chain_extend"
}
```

每段的 `image_gen_input` 和 `video_gen_input` 都是 compact JSON，可直接传给 `scripts/image/submit.py` 与 `scripts/video/submit.py`。链式续接时，后段的 `video_gen_input.image_url` 需要在前段视频下载完成后填入。

