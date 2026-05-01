#!/usr/bin/env python3
"""Submit an image generation task to NodeStudio (create + submit in one step).

Usage: python submit.py '<json_body>'
Local images in reference_images[] are auto-converted to base64 data URIs.
"""
import base64, json, mimetypes, os, sys, uuid, urllib.request, urllib.error

BASE_URL = os.environ.get("NODESTUDIO_URL", "https://nostudio-api.deskclaw.me")
API = f"{BASE_URL}/api/v1"
MAX_FILE_BYTES = 10 * 1024 * 1024


def get_token():
    token = os.environ.get("NODESTUDIO_TOKEN", "")
    if token:
        return token
    path = os.path.expanduser("~/.deskclaw/deskclaw-settings.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        a = c.get("auth")
        t = a.get("token", "") if isinstance(a, dict) else ""
        return t or c.get("auth.token", "") or c.get("authToken", "")
    return ""


def _get_workspace():
    cfg_path = os.path.expanduser("~/.deskclaw/nanobot/config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        ws = cfg.get("agents", {}).get("defaults", {}).get("workspace", "~/.deskclaw/nanobot/workspace")
    except Exception:
        ws = "~/.deskclaw/nanobot/workspace"
    return os.path.normpath(os.path.expanduser(ws))


def resolve_media_urls(data):
    ws = _get_workspace()

    def to_data_uri(v):
        if not v or not isinstance(v, str):
            return v
        s = v.strip()
        if s.startswith(("http://", "https://", "data:")):
            return s
        raw_path = s[7:] if s.startswith("file://") else s
        if os.path.isabs(raw_path):
            path = os.path.normpath(os.path.expanduser(raw_path))
        else:
            path = os.path.normpath(os.path.join(ws, raw_path.lstrip("/")))
        if not os.path.isfile(path):
            raise ValueError(f"not a file or missing: {path}")
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            raise ValueError(
                f"图片文件过大（{size // 1024 // 1024}MB > 10MB），请缩小后重试"
            )
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:{mime};base64,{b64}"

    if "reference_images" in data and isinstance(data["reference_images"], list):
        data["reference_images"] = [to_data_uri(x) if x else x for x in data["reference_images"]]
    return data


def api_post(url, body, token, idem_key, timeout=30):
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Idempotency-Key": idem_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body_text)
        except Exception:
            return {"error": f"HTTP {e.code}", "detail": body_text[:500]}


def parse_input():
    if len(sys.argv) >= 2 and sys.argv[1] and sys.argv[1] != "-":
        raw = sys.argv[1]
        if raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1]
        return json.loads(raw)
    return json.load(sys.stdin)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: submit.py '<json_body>'"}))
        sys.exit(1)

    token = get_token()
    if not token:
        print(json.dumps({"error": "No token. Check ~/.deskclaw/deskclaw-settings.json. Ensure user is logged in."}))
        sys.exit(1)

    data = parse_input()

    try:
        data = resolve_media_urls(data)
    except Exception as e:
        print(json.dumps({"error": f"resolve_media_urls: {e}"}))
        sys.exit(1)

    idem_key = str(uuid.uuid4())

    create_body = {
        "task_type": "image_generate",
        "action": "generate",
        "title": data.get("title", data.get("prompt", "image")[:30]),
        "description": data.get("prompt", ""),
        "model_name": data.get("model", "nano2"),
        "input_materials": {},
        "parameters": {
            "prompt": data.get("prompt", ""),
            "reference_images": data.get("reference_images", []),
            "size": data.get("size", "1024x1024"),
            "image_count": data.get("image_count", 1),
        },
    }

    submit_body = {
        "model_id": data.get("model", "nano2"),
        "prompt": data.get("prompt", ""),
        "reference_images": data.get("reference_images", []),
        "size": data.get("size", "1024x1024"),
        "aspect_ratio": data.get("aspect_ratio", "1:1"),
        "resolution": data.get("resolution", "0.5K"),
        "image_count": data.get("image_count", 1),
        "save_to_assets": data.get("save_to_assets", True),
    }

    create_resp = api_post(f"{API}/tasks/generate", create_body, token, idem_key)
    task_id = (create_resp.get("data") or create_resp).get("task_id", "")
    if not task_id:
        print(json.dumps(create_resp, ensure_ascii=False))
        sys.exit(1)

    submit_resp = api_post(
        f"{API}/image-generation/tasks/{task_id}/submit",
        submit_body, token, f"{idem_key}-submit", timeout=180,
    )
    d = (submit_resp.get("data") or submit_resp) if isinstance(submit_resp, dict) else submit_resp
    if isinstance(d, dict):
        d.setdefault("task_id", task_id)
        if "error" in d and "image_urls" not in d:
            d = {"task_id": task_id, "status": "submitted", "hint": "submit timeout, poll to get result"}
    else:
        d = {"task_id": task_id, "status": "submitted"}
    print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()

