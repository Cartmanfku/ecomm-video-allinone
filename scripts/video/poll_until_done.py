#!/usr/bin/env python3
"""Poll until task reaches completed or failed (single exec call)."""
import json, os, sys, time, urllib.request, urllib.error

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


def poll_once(task_id, token):
    req = urllib.request.Request(
        f"{API}/generation/tasks/{task_id}/status",
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
        print(json.dumps({"error": "Usage: poll_until_done.py <task_id> [max_seconds]"}))
        sys.exit(1)
    task_id = sys.argv[1]
    max_sec = int(sys.argv[2]) if len(sys.argv) > 2 else 540
    interval = 15
    token = get_token()
    if not token:
        print(json.dumps({"error": "No token. Check ~/.deskclaw/deskclaw-settings.json (authToken). Ensure user is logged in."}))
        sys.exit(1)
    elapsed = 0
    last_result = {}
    while elapsed < max_sec:
        last_result = poll_once(task_id, token)
        status = last_result.get("status", "")
        if status == "completed":
            print(json.dumps(last_result, ensure_ascii=False))
            sys.exit(0)
        if status == "failed":
            print(json.dumps(last_result, ensure_ascii=False))
            sys.exit(1)
        time.sleep(interval)
        elapsed += interval
    last_result = poll_once(task_id, token)
    if last_result.get("status") == "completed":
        print(json.dumps(last_result, ensure_ascii=False))
        sys.exit(0)
    print(json.dumps(last_result, ensure_ascii=False))
    print(json.dumps({"error": "poll_until_done_timeout", "max_seconds": max_sec, "last_status": last_result.get("status", "unknown")}))
    sys.exit(1)


if __name__ == "__main__":
    main()

