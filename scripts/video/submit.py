#!/usr/bin/env python3
"""Submit a video generation task to NodeStudio (create + submit in one step)."""
import json, mimetypes, os, sys, uuid, urllib.request, urllib.error

BASE_URL = os.environ.get("NODESTUDIO_URL", "https://nostudio-api.deskclaw.me")
API = f"{BASE_URL}/api/v1"


def get_token():
    token = os.environ.get("NODESTUDIO_TOKEN", "")
    if token:
        return token
    path = os.path.expanduser("~/.deskclaw/deskclaw-settings.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        return c.get("auth.token", "") or c.get("authToken", "")
    return ""


def _is_public_api():
    host = BASE_URL.lower()
    for local in ("localhost", "127.0.0.1", "0.0.0.0", "192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.3"):
        if local in host:
            return False
    return True


def _presign_upload(file_path, token):
    fname = os.path.basename(file_path)
    ct = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    media_type = "image" if ct.startswith("image") else ("video" if ct.startswith("video") else "audio")
    file_size = os.path.getsize(file_path)
    body = json.dumps({
        "file_name": fname,
        "media_type": media_type,
        "content_type": ct,
        "file_size": file_size,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/assets/presign-upload",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        presign = json.loads(resp.read())
    d = presign.get("data") or presign
    upload_url = d["upload_url"]
    signed_headers = d.get("signed_headers", {})
    cdn_url = d["cdn_url"]
    asset_id = d["asset_id"]
    with open(file_path, "rb") as f:
        file_data = f.read()
    put_req = urllib.request.Request(upload_url, data=file_data, method="PUT")
    put_req.add_header("Content-Type", signed_headers.get("Content-Type", ct))
    for k, v in signed_headers.items():
        if k.lower() != "content-type":
            put_req.add_header(k, v)
    with urllib.request.urlopen(put_req, timeout=120):
        pass
    confirm_req = urllib.request.Request(
        f"{API}/assets/confirm-upload/{asset_id}",
        data=b"{}",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(confirm_req, timeout=15):
        pass
    return cdn_url


def resolve_media_urls(data, token):
    cfg_path = os.path.expanduser("~/.deskclaw/nanobot/config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return data
    ws = cfg.get("agents", {}).get("defaults", {}).get("workspace", "~/.deskclaw/nanobot/workspace")
    ws = os.path.normpath(os.path.expanduser(ws))
    use_upload = _is_public_api()
    port = cfg.get("gateway", {}).get("port", 18790)
    host = os.environ.get("DESKCLAW_GATEWAY_HOST") or os.environ.get("DESKCLAW_FILES_HOST") or "127.0.0.1"
    files_base = os.environ.get("DESKCLAW_FILES_BASE_URL") or f"http://{host}:{port}"
    files_base = files_base.rstrip("/")

    def one_url(v):
        if not v or not isinstance(v, str):
            return v
        s = v.strip()
        if s.startswith(("http://", "https://")):
            return s
        path = s[7:] if s.startswith("file://") else (s if os.path.isabs(s) else os.path.join(ws, s.lstrip("/")))
        path = os.path.normpath(os.path.expanduser(path))
        ws_norm = ws.replace("\\", "/").lower() if os.name == "nt" else ws
        p_norm = path.replace("\\", "/").lower() if os.name == "nt" else path
        if not p_norm.startswith(ws_norm):
            raise ValueError(f"image path outside workspace: {path}")
        if not os.path.isfile(path):
            raise ValueError(f"not a file or missing: {path}")
        if use_upload:
            return _presign_upload(path, token)
        return files_base + "/files" + path.replace("\\", "/")

    for key in ("image_url", "end_image_url"):
        if key in data and data[key]:
            data[key] = one_url(data[key])
    if "reference_images" in data and isinstance(data["reference_images"], list):
        data["reference_images"] = [one_url(x) if x else x for x in data["reference_images"]]
    return data


def api_post(url, body, token, idem_key):
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Idempotency-Key": idem_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body_text)
        except Exception:
            return {"error": f"HTTP {e.code}", "detail": body_text[:500]}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: submit.py '<json_body>'"}))
        sys.exit(1)
    token = get_token()
    if not token:
        print(json.dumps({"error": "No token. Check ~/.deskclaw/deskclaw-settings.json (authToken). Ensure user is logged in."}))
        sys.exit(1)
    data = json.loads(sys.argv[1])
    try:
        data = resolve_media_urls(data, token)
    except Exception as e:
        print(json.dumps({"error": f"resolve_media_urls: {e}"}))
        sys.exit(1)
    idem_key = str(uuid.uuid4())
    create_body = {
        "task_type": "video_generate",
        "action": "generate",
        "title": data.get("title", data.get("prompt", "video")[:30]),
        "description": data.get("prompt", ""),
        "model_name": data.get("model", "fast"),
        "aspect_ratio": data.get("aspect_ratio", "16:9"),
        "duration": data.get("duration", 5),
        "input_materials": {},
        "parameters": {"prompt": data.get("prompt", ""), "resolution": data.get("resolution", "720p"), "generate_audio": data.get("generate_audio", True)},
    }
    submit_body = {
        "model_id": data.get("model", "fast"),
        "prompt": data.get("prompt", ""),
        "resolution": data.get("resolution", "720p"),
        "duration": data.get("duration", 5),
        "aspect_ratio": data.get("aspect_ratio", "16:9"),
        "generate_audio": data.get("generate_audio", True),
        "watermark": data.get("watermark", False),
    }
    for key in ("image_url", "end_image_url", "reference_images", "reference_videos", "reference_audios", "seed"):
        if key in data:
            submit_body[key] = data[key]
            if key in ("image_url", "end_image_url", "seed"):
                create_body["parameters"][key] = data[key]
    create_resp = api_post(f"{API}/tasks/generate", create_body, token, idem_key)
    task_id = (create_resp.get("data") or create_resp).get("task_id", "")
    if not task_id:
        print(json.dumps(create_resp, ensure_ascii=False))
        sys.exit(1)
    submit_resp = api_post(f"{API}/generation/tasks/{task_id}/submit", submit_body, token, f"{idem_key}-submit")
    d = (submit_resp.get("data") or submit_resp) if isinstance(submit_resp, dict) else submit_resp
    if isinstance(d, dict):
        d.setdefault("task_id", task_id)
    else:
        d = {"task_id": task_id, "status": "submitted"}
    print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()

