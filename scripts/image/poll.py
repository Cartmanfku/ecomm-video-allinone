#!/usr/bin/env python3
"""Poll image generation task status from NodeStudio.

Usage: python poll.py <task_id>
Env: NODESTUDIO_URL (default https://nostudio-api.deskclaw.me), NODESTUDIO_TOKEN
"""
import json, os, sys, urllib.request, urllib.error

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
        a = c.get("auth")
        t = a.get("token", "") if isinstance(a, dict) else ""
        return t or c.get("auth.token", "") or c.get("authToken", "")
    return ""


def poll(task_id, token):
    req = urllib.request.Request(
        f"{API}/image-generation/tasks/{task_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"task_id": task_id, "status": "error", "error_message": f"HTTP {e.code}: {body[:300]}"}
    except Exception as e:
        return {"task_id": task_id, "status": "error", "error_message": str(e)}

    d = r.get("data", r) if isinstance(r, dict) else {"raw": str(r)}
    if isinstance(d, dict):
        d.setdefault("task_id", task_id)
        d.setdefault("status", "unknown")
    return d


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: poll.py <task_id>"}))
        sys.exit(1)

    token = get_token()
    if not token:
        print(json.dumps({"error": "No token. Check ~/.deskclaw/deskclaw-settings.json. Ensure user is logged in."}))
        sys.exit(1)

    result = poll(sys.argv[1], token)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

