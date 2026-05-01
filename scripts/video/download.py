#!/usr/bin/env python3
"""Download a video from URL to a local directory."""
import json, os, re, sys, time, urllib.request, urllib.error

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


def get_workspace():
    cfg_path = os.path.expanduser("~/.deskclaw/nanobot/config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        ws = cfg.get("agents", {}).get("defaults", {}).get("workspace", "~/.deskclaw/nanobot/workspace")
        return os.path.expanduser(ws)
    except Exception:
        return os.path.expanduser("~/.deskclaw/nanobot/workspace")


def resolve_output_dir(output_dir):
    ws = get_workspace()
    base_outputs = os.path.normpath(os.path.join(ws, "outputs"))
    if output_dir:
        candidate = os.path.normpath(os.path.expanduser(output_dir))
        base_norm = base_outputs.replace("\\", "/").lower() if os.name == "nt" else base_outputs
        cand_norm = candidate.replace("\\", "/").lower() if os.name == "nt" else candidate
        if not cand_norm.startswith(base_norm):
            raise ValueError(f"output_dir must be under workspace outputs: {base_outputs}")
        return candidate
    session_key = os.environ.get("NANOBOT_SESSION_KEY") or os.environ.get("OPENCLAW_SESSION_KEY", "")
    if session_key:
        safe = re.sub(r'[<>:"/\\|?*]', "_", session_key.replace(":", "_")).strip()
        return os.path.join(base_outputs, safe)
    return base_outputs


def is_valid_video(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 10000:
        return False
    with open(path, "rb") as f:
        head = f.read(4).hex()
    bad_heads = ("3c3f786d", "3c457272", "3c68746d", "3c214f43", "7b22436f")
    return head not in bad_heads


def try_download(url, output, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            with open(output, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        if is_valid_video(output):
            return True
    except Exception:
        pass
    if os.path.isfile(output):
        os.remove(output)
    return False


def refetch_video_urls(task_id, token):
    req = urllib.request.Request(
        f"{API}/generation/tasks/{task_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read())
        d = r.get("data", r) if isinstance(r, dict) else {}
        urls = []
        for key in ("video_url", "download_url", "signed_url", "video_download_url", "cdn_url", "result_url"):
            v = d.get(key, "")
            if v and isinstance(v, str) and v.startswith("http"):
                urls.append(v)
        return urls
    except Exception:
        return []


def try_api_proxy(task_id, token, output):
    for suffix in ("download", "video", "result"):
        url = f"{API}/generation/tasks/{task_id}/{suffix}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct or "html" in ct:
                    continue
                with open(output, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
            if is_valid_video(output):
                return True
        except Exception:
            pass
        if os.path.isfile(output):
            os.remove(output)
    return False


def download_with_retries(video_url, output, token, task_id):
    if token and try_download(video_url, output, {"Authorization": f"Bearer {token}"}):
        return True
    if try_download(video_url, output):
        return True
    if try_download(video_url, output, {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{BASE_URL}/",
    }):
        return True
    if not task_id or not token:
        return False
    fresh_urls = refetch_video_urls(task_id, token)
    for url in fresh_urls:
        if url == video_url:
            continue
        if try_download(url, output, {"Authorization": f"Bearer {token}"}):
            return True
        if try_download(url, output):
            return True
    return try_api_proxy(task_id, token, output)


def main():
    if len(sys.argv) < 2 or not sys.argv[1]:
        print(json.dumps({"error": "Usage: download.py '<video_url>' [filename] [output_dir] [task_id]"}))
        sys.exit(1)
    video_url = sys.argv[1].replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u003f", "?")
    filename_hint = sys.argv[2] if len(sys.argv) > 2 else ""
    output_dir = sys.argv[3] if len(sys.argv) > 3 else ""
    task_id = sys.argv[4] if len(sys.argv) > 4 else ""
    try:
        output_dir = resolve_output_dir(output_dir)
    except Exception as e:
        print(json.dumps({"error": f"invalid_output_dir: {e}"}))
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if filename_hint:
        safe_name = re.sub(r'[\s/\\:*?"<>|]', "_", filename_hint)
        filename = f"{safe_name}_{timestamp}.mp4"
    else:
        filename = f"video_{timestamp}.mp4"
    output = os.path.join(output_dir, filename)
    token = get_token()
    if download_with_retries(video_url, output, token, task_id):
        size_mb = f"{os.path.getsize(output) / 1048576:.1f}"
        print(json.dumps({"status": "ok", "path": output, "url": video_url, "size_mb": f"{size_mb}MB"}))
    else:
        for f in (output, f"{output}.tmp"):
            if os.path.isfile(f):
                os.remove(f)
        print(json.dumps({"status": "download_failed", "url": video_url, "task_id": task_id, "message": "All download methods failed."}))
        sys.exit(1)


if __name__ == "__main__":
    main()

