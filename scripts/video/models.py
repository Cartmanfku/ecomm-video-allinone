#!/usr/bin/env python3
"""Query available video generation models from NodeStudio."""
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
        return c.get("auth.token", "") or c.get("authToken", "")
    return ""


def main():
    token = get_token()
    if not token:
        print(json.dumps({"error": "No token. Check ~/.deskclaw/deskclaw-settings.json (authToken). Ensure user is logged in."}))
        sys.exit(1)
    req = urllib.request.Request(
        f"{API}/generation/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(json.dumps({"error": f"HTTP {e.code}", "detail": body[:500]}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()

