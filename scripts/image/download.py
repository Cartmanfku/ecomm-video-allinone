#!/usr/bin/env python3
"""Download image(s) from URL(s) to a local directory.

Usage: python download.py '<image_url_or_json_array>' [filename] [output_dir]
  - image_url: single URL or JSON array '["url1","url2"]'
  - filename: short name for the file (optional)
  - output_dir: absolute dir, or empty to auto-resolve from session key
"""
import json, os, re, sys, time, urllib.request, urllib.error

BASE_URL = os.environ.get("NODESTUDIO_URL", "https://nostudio-api.deskclaw.me")


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


def parse_urls(raw):
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            return [str(u) for u in arr if u]
        return [str(arr)]
    except Exception:
        return [raw]


def is_valid_image(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 500:
        return False
    with open(path, "rb") as f:
        head = f.read(4).hex()
    bad_heads = ("3c3f786d", "3c457272", "3c68746d", "3c214f43")
    return head not in bad_heads


def try_download(url, output, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(output, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        if is_valid_image(output):
            return True
    except Exception:
        pass
    if os.path.isfile(output):
        os.remove(output)
    return False


def main():
    if len(sys.argv) < 2 or not sys.argv[1]:
        print(json.dumps({"error": "Usage: download.py '<image_url_or_json_array>' [filename] [output_dir]"}))
        sys.exit(1)

    raw_input = sys.argv[1]
    if raw_input.startswith("'") and raw_input.endswith("'"):
        raw_input = raw_input[1:-1]
    image_input = raw_input.replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u003f", "?")
    filename_hint = sys.argv[2] if len(sys.argv) > 2 else ""
    output_dir = sys.argv[3] if len(sys.argv) > 3 else ""

    try:
        output_dir = resolve_output_dir(output_dir)
    except Exception as e:
        print(json.dumps({"error": f"invalid_output_dir: {e}"}))
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)

    urls = parse_urls(image_input)
    token = get_token()
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    downloaded = []
    failed = 0

    for idx, url in enumerate(urls):
        if not url:
            continue
        ext = "png"
        lower = url.lower()
        if ".jpg" in lower or ".jpeg" in lower:
            ext = "jpg"
        elif ".webp" in lower:
            ext = "webp"
        elif ".gif" in lower:
            ext = "gif"

        if filename_hint:
            safe_name = re.sub(r'[\s/\\:*?"<>|]', "_", filename_hint)
            fname = f"{safe_name}_{timestamp}.{ext}" if idx == 0 else f"{safe_name}_{timestamp}_{idx}.{ext}"
        else:
            fname = f"image_{timestamp}.{ext}" if idx == 0 else f"image_{timestamp}_{idx}.{ext}"
        outfile = os.path.join(output_dir, fname)

        ok = False
        if token:
            ok = try_download(url, outfile, {"Authorization": f"Bearer {token}"})
        if not ok:
            ok = try_download(url, outfile)
        if not ok:
            ok = try_download(url, outfile, {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{BASE_URL}/",
            })

        if ok and os.path.isfile(outfile):
            downloaded.append(outfile)
        else:
            for f in (outfile, f"{outfile}.tmp"):
                if os.path.isfile(f):
                    os.remove(f)
            failed += 1

    if downloaded:
        print(json.dumps({"status": "ok", "paths": downloaded, "downloaded": len(downloaded), "failed": failed}))
    else:
        print(json.dumps({"status": "download_failed", "message": "All download methods failed.", "failed": failed}))
        sys.exit(1)


if __name__ == "__main__":
    main()

