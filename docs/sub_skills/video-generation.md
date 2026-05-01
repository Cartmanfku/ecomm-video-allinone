# SUB_SKILL: Video Generation

## Default path (minimize tool calls)

Do **not** `read_file` / `ls` this skill on every request. Do **not** run `models.py` unless handling **fallback after `failed`**.

1. `python scripts/video/submit.py "<compact_json>"` → get `task_id`
2. `python scripts/video/poll_until_done.py <task_id>` — **one** exec, `timeout=600`
3. `python scripts/video/download.py "<video_url>" "<short_name>" "" "<task_id>"` — **must pass `task_id`** as 4th arg
4. **Single** `message(media)` with **local file path** — see **Silent policy**

**Exactly 4 tool calls.** Do NOT add `read_file`, `list_dir`, `write_file`, or any other calls. Do NOT write your own scripts or call APIs directly — always use the provided `.py` scripts.

**Image upload is automatic.** When user sends an image for image-to-video, `submit.py` handles all URL resolution internally — no env vars or manual URL construction needed.

**Nanobot limits:** `exec` is capped at **600s** per call. `poll_until_done.py` defaults to **540s** internal wait. If it times out while still processing, run **`python scripts/video/poll_until_done.py <same_task_id> 480`** again (vary the second arg so the command is not identical — do **not** re-submit). Consider raising `agents.defaults.maxToolIterations` in `~/.deskclaw/nanobot/config.json` from **20** to **35–40** so long flows do not hit max iterations.

## Silent policy

**No user-visible status text** until the final delivery: no "please wait", "polling", or intermediate narration. Only the **final** `message()` with `media` (and minimal `content` if required).

## Token & URLs

- Token: auto from `~/.deskclaw/deskclaw-settings.json` → `authToken`, or `NODESTUDIO_TOKEN`.
- NodeStudio base: `NODESTUDIO_URL` (default `https://nostudio-api.deskclaw.me`).
- **Naming:** Models are **Seedance 2.0** (`pro`), **Seedance 2.0 Fast** (`fast`), and **Seedance 1.5 Pro** (`1.5-pro`).

## Models (no pre-flight `models.py`)

| model_id | Name | Resolution | Duration | Ref imgs / vids / auds | Notes |
|----------|------|-----------|----------|------------------------|-------|
| `fast` | **Seedance 2.0 Fast** | 480p / 720p | 4–15s | 9 / 3 / 3 | Default when user has no preference |
| `pro` | **Seedance 2.0** | 480p / 720p | 4–15s | 9 / 3 / 3 | Higher quality, slower |
| `1.5-pro` | **Seedance 1.5 Pro** | 480p / 720p / 1080p | 4–12s | 2 / 0 / 0 | Supports 1080p |

**Selection rules (in order):**
1. User explicitly names a model → use it.
2. User asks for "best quality" / "highest" / "最好" / "最高画质" → use `pro`.
3. User asks for "1080p" or "高清" → use `1.5-pro` (only model supporting 1080p).
4. User has no preference → use `fast`.
5. If the chosen model **fails**, fall back: `fast` → `pro` → `1.5-pro`; only call `models.py` if all fail.

**Do not** run `models.py` before the first `submit.py`.

## Build JSON (compact, no spaces after `:` or `,`)

Required: `prompt`.

### Image-to-video

When the user sends an image, the message contains `![image](media/<session>/<file>)`. Pass the **relative path** as `image_url`:

```json
{"prompt":"...","image_url":"media/agent_main_desk-xxx/abc123.jpg"}
```

`submit.py` automatically resolves local paths: public API → presign-upload to CDN; local API → gateway `/files/...`. **Do not** set `DESKCLAW_GATEWAY_HOST`, construct URLs, or retry with different env vars — the script handles everything.

### Parameters

| Intent | Fields |
|--------|--------|
| Portrait | `"aspect_ratio":"9:16"` |
| Landscape | `"16:9"` (default) |
| Square / ultrawide | `"1:1"` / `"21:9"` |
| Duration | default `5` |
| No audio | `"generate_audio":false` |
| Resolution | `"720p"` or `"480p"` |

## Submit

```
python scripts/video/submit.py "<json_body>"
```

**Windows note:** Use `"` (double quotes) for the JSON argument, with internal `\"` escaping. Single quotes do not work on Windows cmd.

## Poll

```
python scripts/video/poll_until_done.py <task_id> [max_seconds]
```

- Default `max_seconds` **540** (stays under **600s** nanobot `exec` kill).
- Pass `exec(..., timeout=600)`.
- **Do not** run `poll.py` in parallel with `poll_until_done.py`.
- `progress` **50** while `processing` is normal (placeholder), not a stall.

**Resume:** If output contains `poll_until_done_timeout` and task not `failed`, re-run with **same** `task_id` and a **different** second arg (e.g. `400`). Never duplicate the exact same command string (gateway may block).

## Fallback (only on `failed`)

1. `python scripts/video/models.py` → pick next alias from list (`fast` → `pro`).
2. `submit.py` again → `poll_until_done.py` new `task_id`.

## Download

```
NANOBOT_SESSION_KEY='agent:main:desk-xxx' python scripts/video/download.py "<video_url>" "<short_name>" "" "<task_id>"
```

- **4th arg `task_id` is required** — enables re-poll for signed URL and API proxy fallback when CDN returns Access Denied.
- 3rd arg is output_dir (empty string `""` = auto from session key).
- Script saves to workspace `outputs/` and prints `{"status":"ok","path":"..."}`.
- If download fails, returns `{"status":"download_failed",...}`.

## Present (single message)

**Silent until here.** `message({ "content": "…", "media": ["<local_path>"] })`.

**Critical rules:**
- `media` must contain the **local file path** returned by `download.py` (`path` field). Never put a remote URL in `media`.
- **Never** put CDN URLs in `content` — they are not publicly accessible and will show Access Denied to the user.
- If download failed, say "视频生成成功但下载失败，请稍后重试" in `content`, leave `media` empty. Do NOT paste the raw URL.
- **Model name:** Use **Seedance 2.0**, **Seedance 2.0 Fast**, or **Seedance 1.5 Pro**.

## Error Handling

| Case | Action |
|------|--------|
| 401/403 | Re-auth |
| 429 | `视频生成的积分已经用完了，请充值；如果充值后还无法使用，请联系管理员。` |
| `failed` | Fallback above |
| Poll timeout | Resume `poll_until_done.py` same `task_id`, different max_seconds |

## Rules

- **Python scripts only**: `submit.py`, `poll_until_done.py`, `poll.py`, `download.py`, `models.py` (fallback only).
- **Do NOT** write custom scripts, Python files, or call APIs with `curl` / `urllib` yourself.
- **Do NOT** `read_file` the scripts — just `exec()` them.
- **Do NOT** set or change `DESKCLAW_GATEWAY_HOST` — the scripts auto-detect the correct upload method.
- **Do NOT** call `mcp_deskclaw_restart_gateway` — gateway restarts break the current session.
- If `submit.py` returns an error about image upload, report it to the user and stop. Do not retry with different env vars.
- JSON compact in arguments.