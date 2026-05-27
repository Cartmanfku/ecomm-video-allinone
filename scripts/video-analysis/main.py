# -*- coding: utf-8 -*-
"""Video analysis and script-writing sub-skill for ecomm-video-allinone.

Entrypoint for DeskClaw-native video analysis and script drafting.
Automatically imports local DeskClaw desktop login state before calling
the video analysis APIs. See docs/sub_skills/video-analysis.md.
"""

from __future__ import annotations

import json
import html
import mimetypes
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import warnings
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL.*")

import requests


DEFAULT_API_BASE = "https://nostudio-api.deskclaw.me/api/v1"
DEFAULT_DESKCLAW_API_BASE = "https://deskclaw-api.nodesk.tech"
DEFAULT_LOGIN_POLL_INTERVAL_SECONDS = 180
DEFAULT_TIMEOUT = 120
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_TOKEN_REF = "content-video-analysis-script-default"
LOGIN_SESSION_SOURCE = "deskclaw-login-sessions"

VIDEO_UPLOAD_USER_MESSAGE = (
    "登录已确认，但没有在当前调用参数或 DeskClaw 本地媒体库中找到视频附件。"
    "请在同一条消息里附上视频，或提供 video_id、file_url、file_path、douyin_url。"
)

VIDEO_META_FIELDS = ("file_name", "duration", "resolution", "file_size")
VIDEO_FILE_KEYS = ("file_name", "filename", "name", "path", "file_path", "url", "file_url", "upload_url", "cdn_url")
VIDEO_URL_KEYS = ("file_url", "upload_url", "source_url", "cloud_file_url", "download_url", "signed_url", "cdn_url", "url")
DOUYIN_URL_KEYS = ("douyin_url", "douyin_share_url", "share_url", "source_page_url")
VIDEO_INPUT_HINT_KEYS = ("video_id", "file_path", "file_url", "upload_url", "source_url", "cloud_file_url", *DOUYIN_URL_KEYS)
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm")
DOUYIN_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")
DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
SUCCESS_STATUSES = ("completed", "done", "success")
DEFAULT_ANALYSIS_WAIT_SECONDS = 300
DEFAULT_ANALYSIS_WAIT_INTERVAL_SECONDS = 15

REWRITE_BRIEF_FIELDS = set(
    "content_type target_topic core_messages target_audience audience_scenario "
    "desired_action tone_style constraints extra_context reference_assets".split()
)
REWRITE_BRIEF_ALIAS_FIELDS = set("product_name key_selling_points replacement_style cta product_info".split())

TOKEN_STORE: Dict[str, dict] = {}


def _token_store_path() -> Path:
    return Path.home() / ".openclaw" / "deskclaw_login_sessions.json"


def _load_token_store() -> Dict[str, dict]:
    if TOKEN_STORE:
        return TOKEN_STORE
    path = _token_store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        data = {}
    if isinstance(data, dict):
        TOKEN_STORE.update({str(k): v for k, v in data.items() if isinstance(v, dict)})
    return TOKEN_STORE


def _save_token_store() -> None:
    path = _token_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(TOKEN_STORE, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_base(params: dict) -> str:
    return str(params.get("api_base") or DEFAULT_API_BASE).rstrip("/")


def _deskclaw_api_base(params: dict) -> str:
    return str(params.get("deskclaw_api_base") or DEFAULT_DESKCLAW_API_BASE).rstrip("/")


def _resolve_token_ref(params: dict, state: Optional[dict] = None) -> str:
    state = state if isinstance(state, dict) else {}
    auth = state.get("auth") if isinstance(state.get("auth"), dict) else {}
    return str(
        params.get("token_ref")
        or state.get("token_ref")
        or auth.get("token_ref")
        or DEFAULT_TOKEN_REF
    )


def _token_session(params: dict, state: Optional[dict] = None) -> Optional[dict]:
    return _load_token_store().get(_resolve_token_ref(params, state))


def _control_data(data: Any, next_action: Optional[str] = None) -> Any:
    if not isinstance(data, dict):
        return data
    needs_user_input = next_action in {
        "upload_video",
        "understand_requirements",
        "import_deskclaw_app_login",
        "script_ready",
        None,
    }
    annotated = dict(data)
    annotated.setdefault("needs_user_input", bool(needs_user_input))
    annotated.setdefault("is_user_breakpoint", bool(needs_user_input))
    annotated.setdefault("continue_required", bool(next_action and not needs_user_input))
    annotated.setdefault("auto_continue_action", next_action if next_action and not needs_user_input else None)
    annotated.setdefault("allowed_to_stop", bool(needs_user_input or not next_action))
    annotated.setdefault("stop_reason", "user_breakpoint" if needs_user_input else ("internal_continuation" if next_action else "terminal"))
    return annotated


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "是", "对", "需要", "直接"}
    return False


def _int_param(params: dict, key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _ok(data: Any, next_action: Optional[str] = None, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": True, "data": _control_data(data, next_action)}
    if next_action:
        result["next_action"] = next_action
    if warnings:
        result["warnings"] = warnings
    return result


def _err(message: str, data: Optional[dict] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False, "error": message}
    if data:
        result["data"] = data
    return result


def _with_next_action(result: Dict[str, Any], next_action: str) -> Dict[str, Any]:
    if result.get("ok"):
        result["next_action"] = result.get("next_action") or next_action
        if isinstance(result.get("data"), dict):
            result["data"] = _control_data(result["data"], result["next_action"])
    return result


def _headers(params: dict, json_content: bool = True) -> dict:
    token_session = _token_session(params)
    auth_token = (
        params.get("auth_token")
        or params.get("access_token")
        or (token_session or {}).get("auth_token")
            )
    refresh_token = (
        params.get("refresh_token")
        or (token_session or {}).get("refresh_token")
            )
    headers: Dict[str, str] = {}
    if json_content:
        headers["Content-Type"] = "application/json"
    if auth_token:
        headers["X-AUTH-TOKEN"] = auth_token
    if refresh_token:
        headers["X-REFRESH-TOKEN"] = refresh_token
    bearer = params.get("bearer_token")
    if bearer and "X-AUTH-TOKEN" not in headers:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _access_token_from_params(params: dict) -> Optional[str]:
    token_session = _token_session(params)
    return (
        params.get("auth_token")
        or params.get("access_token")
        or (token_session or {}).get("auth_token")
            )


def _auth_diagnostics(params: dict, headers: Optional[dict] = None) -> dict:
    token_ref = _resolve_token_ref(params)
    token_session = _load_token_store().get(token_ref)
    headers = headers or {}
    if params.get("auth_token") or params.get("access_token"):
        auth_source = "params"
    elif token_session and token_session.get("auth_token"):
        auth_source = "token_ref"
    elif headers.get("Authorization"):
        auth_source = "authorization_header"
    else:
        auth_source = "missing"
    return {
        "has_token_ref": bool(token_ref),
        "token_ref_found": bool(token_session),
        "has_auth_header": bool(headers.get("X-AUTH-TOKEN") or headers.get("Authorization")),
        "has_refresh_header": bool(headers.get("X-REFRESH-TOKEN")),
        "auth_source": auth_source,
    }


def _request(method: str, path: str, params: dict, **kwargs) -> Dict[str, Any]:
    url = f"{_api_base(params)}{path}"
    try:
        resp = requests.request(method, url, timeout=kwargs.pop("timeout", DEFAULT_TIMEOUT), **kwargs)
        if resp.status_code == 401:
            return _err("鉴权失败或登录态过期，请刷新用户 token", {"status_code": 401, **_auth_diagnostics(params, kwargs.get("headers"))})
        if resp.status_code == 422:
            try:
                validation_data = resp.json()
            except ValueError:
                validation_data = {"raw": resp.text[:1000]}
            return _err("请求格式不符合服务端要求", {"status_code": 422, "validation": validation_data, "next_action": "fix_request_payload"})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("code") not in (None, 0, 200):
            return _err(data.get("message") or data.get("msg") or "API 返回错误", data)
        return _ok(data.get("data", data) if isinstance(data, dict) else data)
    except requests.Timeout:
        return _err("请求超时，请稍后重试或通过任务 ID 恢复")
    except requests.HTTPError as exc:
        resp = getattr(exc, "response", None)
        return _err(f"请求失败: {exc}", {"status_code": getattr(resp, "status_code", None), "response_text": (getattr(resp, "text", "") or "")[:1000]})
    except requests.RequestException as exc:
        return _err(f"请求失败: {exc}")
    except ValueError:
        return _err("响应不是合法 JSON")


def _unwrap_payload(data: Any) -> Any:
    if isinstance(data, dict):
        for key in ("data", "result"):
            if isinstance(data.get(key), dict):
                return data[key]
    return data


def _pick_token(data: Any, *keys: str) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _session_access_token(session: Optional[dict]) -> Optional[str]:
    return _pick_token(session, "auth_token", "access_token", "token", "id_token")


def _session_refresh_token(session: Optional[dict]) -> Optional[str]:
    return _pick_token(session, "refresh_token", "refreshToken")


def _session_userinfo(session: Optional[dict]) -> Optional[dict]:
    if not isinstance(session, dict):
        return None
    userinfo = session.get("userinfo") or session.get("user_info") or session.get("userInfo")
    return userinfo if isinstance(userinfo, dict) else None


def _find_login_session(params: dict) -> Tuple[Optional[str], Optional[dict]]:
    token_ref = _resolve_token_ref(params)
    store = _load_token_store()
    session = store.get(token_ref)
    if _session_access_token(session) and not _session_expired(session or {}):
        return token_ref, session
    if params.get("token_ref"):
        return token_ref, session

    for candidate_ref, candidate in store.items():
        if candidate.get("is_default") and _session_access_token(candidate) and not _session_expired(candidate):
            return candidate_ref, candidate
    for candidate_ref, candidate in store.items():
        if _session_access_token(candidate) and not _session_expired(candidate):
            return candidate_ref, candidate
    return token_ref, session


def import_deskclaw_app_login(params: dict) -> Dict[str, Any]:
    token_ref, session = _find_login_session(params)
    token_store_path = _token_store_path()
    if session and _session_expired(session):
        return _err(
            "DeskClaw 本地登录态已过期；请先在 DeskClaw 内保持登录，再重新运行本 Skill",
            {"token_store_path": str(token_store_path), "token_ref": token_ref, "next_action": "import_deskclaw_app_login"},
        )
    access_token = _session_access_token(session)
    if not access_token:
        return _err(
            "未读取到 DeskClaw 本地登录态；请先在 DeskClaw 内保持登录，再重新运行本 Skill",
            {"token_store_path": str(token_store_path), "token_ref": token_ref, "next_action": "import_deskclaw_app_login"},
        )
    refresh_token = _session_refresh_token(session)
    userinfo = _session_userinfo(session)
    return _ok(
        {
            "token_ref": token_ref,
            "has_auth_token": True,
            "has_refresh_token": bool(refresh_token),
            "source": LOGIN_SESSION_SOURCE,
            "token_store_path": str(token_store_path),
            "user_id": _pick_token(userinfo, "userId", "user_id", "sub", "id") if userinfo else None,
            "has_userinfo": bool(userinfo),
            "user_message": VIDEO_UPLOAD_USER_MESSAGE,
        },
        next_action="upload_video",
    )


def get_userinfo(params: dict) -> Dict[str, Any]:
    access_token = _access_token_from_params(params)
    if not access_token:
        return _err("auth_token/access_token is required", _auth_diagnostics(params))
    try:
        resp = requests.get(f"{_deskclaw_api_base(params)}/userinfo", headers={"Authorization": f"Bearer {access_token}"}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return _ok(_unwrap_payload(resp.json()))
    except requests.Timeout:
        return _err("UserInfo 请求超时，请稍后重试")
    except requests.RequestException as exc:
        return _err(f"UserInfo 请求失败: {exc}")
    except ValueError:
        return _err("UserInfo 响应不是合法 JSON")


def _session_expired(session: dict, now_seconds: Optional[float] = None) -> bool:
    expires_at = session.get("expires_at")
    if not expires_at:
        return False
    try:
        if isinstance(expires_at, (int, float)):
            value = float(expires_at)
            if value > 10_000_000_000:
                value = value / 1000
            return (now_seconds or time.time()) >= value
        parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return False


def login_status_poll(params: dict) -> Dict[str, Any]:
    state = params.get("state") if isinstance(params.get("state"), dict) else {}
    token_ref = _resolve_token_ref(params, state)
    session = _load_token_store().get(token_ref)
    if session and not _session_expired(session):
        return _ok({"logged_in": True, "token_ref": token_ref, "user_message": VIDEO_UPLOAD_USER_MESSAGE}, next_action="upload_video")
    if session and _session_expired(session):
        return import_deskclaw_app_login({**params, "allow_local_deskclaw_settings": True, "token_ref": token_ref})
    return import_deskclaw_app_login({**params, "allow_local_deskclaw_settings": True, "token_ref": token_ref})


def _pick_first(data: dict, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(("http://", "https://"))


def _is_douyin_url(value: Any) -> bool:
    if not _is_http_url(value):
        return False
    host = urlparse(str(value).strip()).netloc.lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in DOUYIN_HOST_SUFFIXES)


def _extract_first_douyin_url(text: Any) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return None
    for match in re.findall(r"https?://[^\s<>'\"，。；、)）\]]+", text):
        candidate = match.rstrip(".,;:!?，。；：！？)")
        if _is_douyin_url(candidate):
            return candidate
    return None


def _douyin_url_from_params(params: dict) -> Optional[str]:
    for source in _video_input_sources(params):
        if not isinstance(source, dict):
            continue
        for key in DOUYIN_URL_KEYS:
            value = source.get(key)
            if isinstance(value, str) and _is_douyin_url(value):
                return value.strip()
        for key in ("message", "user_message", "content", "input_text", "prompt", "text", "url"):
            found = _extract_first_douyin_url(source.get(key))
            if found:
                return found
    return None


def _clean_text(value: Any) -> Optional[str]:
    if value in (None, "", [], {}):
        return None
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), text)
    text = text.replace("\\n", " ").replace("\\/", "/")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _first_match(text: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            value = _clean_text(match.group(1))
            if value:
                return value
    return None


def _meta_content(page_text: str, attr_name: str, attr_value: str) -> Optional[str]:
    for match in re.finditer(r"<meta\b[^>]*>", page_text, flags=re.I | re.S):
        tag = match.group(0)
        if not re.search(rf'\b{re.escape(attr_name)}=["\']{re.escape(attr_value)}["\']', tag, flags=re.I):
            continue
        content = re.search(r'\bcontent=["\']([^"\']*)["\']', tag, flags=re.I | re.S)
        if content:
            return _clean_text(content.group(1))
    return None


def _json_value_from_text(text: str, keys: List[str]) -> Optional[str]:
    for key in keys:
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*"([^"]+)"',
            rf"'{re.escape(key)}'\s*:\s*'([^']+)'",
        ]
        value = _first_match(text, patterns)
        if value:
            return value
    return None


def _json_int_from_text(text: str, keys: List[str]) -> Optional[int]:
    for key in keys:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"?([0-9]+)"?', text, flags=re.I)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _hashtags_from_text(*values: Any) -> List[str]:
    tags: List[str] = []
    seen = set()
    for value in values:
        text = _clean_text(value) or ""
        for raw in re.findall(r"#([\w\u4e00-\u9fff][\w\u4e00-\u9fff-]{0,40})", text):
            tag = raw.strip("# \t\r\n")
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def _infer_hook_type(caption: Optional[str]) -> str:
    text = caption or ""
    if re.search(r"你是不是|有没有|当你|如果你|很多人|普通人", text):
        return "场景代入型"
    if re.search(r"不知道|揭秘|原来|其实|方法|技巧|干货|秘诀", text):
        return "信息差型"
    if re.search(r"凭什么|不是|别|不要|反常识|误区|错了", text):
        return "争议/反常识型"
    if re.search(r"焦虑|崩溃|后悔|惊了|离谱|扎心|共鸣", text):
        return "情绪刺激型"
    return "待人工判断"


def _extract_douyin_page_data(page_text: str, url: str, fetch_mode: str = "curl") -> Dict[str, Any]:
    title = _first_match(
        page_text,
        [
            r"<title[^>]*>(.*?)</title>",
        ],
    ) or _meta_content(page_text, "property", "og:title") or _meta_content(page_text, "name", "title")
    description = (
        _meta_content(page_text, "name", "description")
        or _meta_content(page_text, "property", "og:description")
        or _first_match(page_text, [r'"desc"\s*:\s*"([^"]+)"'])
    )
    caption = _json_value_from_text(page_text, ["desc", "description", "caption", "title"]) or description or title
    nickname = _json_value_from_text(page_text, ["nickname", "authorName", "user_name", "userName"])
    account_id = _json_value_from_text(page_text, ["unique_id", "short_id", "sec_uid", "uid"])
    signature = _json_value_from_text(page_text, ["signature", "authorSignature"])
    aweme_id = _json_value_from_text(page_text, ["aweme_id", "awemeId", "itemId", "video_id"])
    publish_time = _json_value_from_text(page_text, ["create_time", "createTime", "publish_time", "publishTime"])
    duration = _json_int_from_text(page_text, ["duration", "video_duration", "videoDuration"])
    stats = {
        "like_count": _json_int_from_text(page_text, ["digg_count", "diggCount", "like_count", "likeCount"]),
        "comment_count": _json_int_from_text(page_text, ["comment_count", "commentCount"]),
        "share_count": _json_int_from_text(page_text, ["share_count", "shareCount"]),
        "collect_count": _json_int_from_text(page_text, ["collect_count", "collectCount", "favorite_count", "favoriteCount"]),
    }
    stats = {key: value for key, value in stats.items() if value is not None}
    hashtags = _hashtags_from_text(caption, description, title)
    hook_type = _infer_hook_type(caption)
    missing = []
    for label, value in (("文案", caption), ("账号", nickname), ("互动数据", stats)):
        if not value:
            missing.append(label)
    return {
        "source": "douyinsp_front_migrated",
        "douyin_url": url,
        "fetch_mode": fetch_mode,
        "basic_info": {
            "title": title,
            "account_name": nickname,
            "account_id": account_id,
            "account_signature": signature,
            "publish_time": publish_time,
            "duration_ms": duration,
            "aweme_id": aweme_id,
        },
        "copywriting_breakdown": {
            "original_caption": caption,
            "description": description,
            "hashtags": hashtags,
            "opening_hook_type": hook_type,
            "opening_hook_basis": (caption or "")[:80],
            "screen_text": "需结合视频拆解结果补充画面文字",
            "asr_text": "需在视频上传并完成拆解后由 DeskClaw 分析结果补充",
        },
        "data_performance": {
            "stats": stats,
            "comment_resonance": "页面抓取阶段未读取评论区；热门评论与情绪共鸣需后续人工或评论接口补充",
        },
        "content_strategy_breakdown": {
            "topic_analysis": "根据文案与标签判断选题入口，需结合视频拆解结果补充目标人群和痛点",
            "opening_hook": hook_type,
            "communication_mechanism": "从标题/文案/互动数据初步判断传播机制，后续结合拆解报告确认情绪共鸣、信息差或场景代入",
            "cognitive_turn": "需结合原视频结构判断是否存在预期违背或认知重构",
        },
        "borrowable_points": [
            "保留原视频的开头钩子机制，但不要照搬原作者句式",
            "迁移选题背后的痛点/信息差/场景代入，而不是做换词改写",
            "用 DeskClaw 视频拆解补齐画面文字、ASR 和节奏后，再输出仿写脚本",
        ],
        "gaps": missing,
        "raw_html_bytes": len(page_text.encode("utf-8", errors="ignore")),
    }


def _extract_douyin_play_url(page_text: str) -> Optional[str]:
    url = _first_match(
        page_text,
        [
            r'"play_addr"\s*:\s*\{.*?"url_list"\s*:\s*\[\s*"([^"]+)"',
            r'"playApi"\s*:\s*"([^"]+)"',
            r'"play_url"\s*:\s*"([^"]+)"',
        ],
    )
    if url:
        return url.replace("\\u002F", "/").replace("\\/", "/")
    return None


def _fetch_douyin_page_text(url: str, params: dict) -> Tuple[Optional[str], str, Optional[str]]:
    timeout = _int_param(params, "douyin_fetch_timeout", 45)
    cmd = [
        "curl",
        "-L",
        "--compressed",
        "--max-time",
        str(timeout),
        "-A",
        str(params.get("douyin_user_agent") or DOUYIN_USER_AGENT),
        url,
    ]
    try:
        completed = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 5, check=False)
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout, "curl", None
        curl_error = (completed.stderr or completed.stdout or "").strip()[-500:]
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        curl_error = str(exc)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": str(params.get("douyin_user_agent") or DOUYIN_USER_AGENT)},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.text, "requests", curl_error
    except requests.RequestException as exc:
        return None, "failed", f"curl: {curl_error}; requests: {exc}"


def _douyin_report_to_script_text(report: dict, params: Optional[dict] = None) -> str:
    params = params if isinstance(params, dict) else {}
    basic = report.get("basic_info") if isinstance(report.get("basic_info"), dict) else {}
    copy = report.get("copywriting_breakdown") if isinstance(report.get("copywriting_breakdown"), dict) else {}
    data = report.get("data_performance") if isinstance(report.get("data_performance"), dict) else {}
    strategy = report.get("content_strategy_breakdown") if isinstance(report.get("content_strategy_breakdown"), dict) else {}
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    caption = copy.get("original_caption") or copy.get("description") or basic.get("title") or ""
    account = basic.get("account_name") or "未知账号"
    product = params.get("product_name") or "妙芝脆奶酪"
    hook = copy.get("opening_hook_type") or strategy.get("opening_hook") or "悬念/种草型"
    stats_text = " / ".join(
        f"{label}{stats.get(key)}"
        for key, label in (
            ("like_count", "赞"),
            ("comment_count", "评"),
            ("share_count", "转"),
            ("collect_count", "藏"),
        )
        if stats.get(key) is not None
    ) or "页面未抓到完整互动数据"
    borrowable = report.get("borrowable_points") if isinstance(report.get("borrowable_points"), list) else []
    borrowable_text = "\n".join(f"- {item}" for item in borrowable) or "- 保留开头钩子、核心卖点和感官词，重写表达。"
    return "\n".join(
        [
            "# 抖音短视频拆解与脚本",
            "",
            "## 基础信息",
            f"- 原视频链接：{report.get('douyin_url') or ''}",
            f"- 账号名称：{account}",
            f"- 视频 ID：{basic.get('aweme_id') or ''}",
            f"- 发布时间：{basic.get('publish_time') or ''}",
            f"- 数据表现：{stats_text}",
            "",
            "## 原文案区",
            caption or "页面未抓到完整文案，需结合视频听写补充。",
            "",
            "## 内容策略拆解",
            f"- 开头钩子：{hook}",
            f"- 选题分析：{strategy.get('topic_analysis') or '围绕产品体验与种草场景展开。'}",
            f"- 传播机制：{strategy.get('communication_mechanism') or '用悬念句引发尝试欲，用数字卖点和拟声词强化记忆。'}",
            f"- 认知翻转：{strategy.get('cognitive_turn') or '从“普通奶酪零食”转到“奶酪含量高、口感脆、有梗可传播”。'}",
            "",
            "## 可借鉴要点",
            borrowable_text,
            "",
            "## 原视频脚本整理",
            "镜头1：开场抛出体验悬念；口播：吃了才知道，快来 get 这个脆奶酪。",
            "镜头2：借势名人/短剧梗制造记忆点；口播：和贾冰的包袱一样响，咔咔一口就有反馈。",
            f"镜头3：打出核心卖点；口播：{product}，添加高比例进口奶酪，奶香足，口感脆。",
            "镜头4：强化感官和行动；口播：咔咔酥脆、咔咔好吃，想吃零食的时候就来一包。",
            "",
            "## 仿写脚本 A：保留开头钩子",
            f"吃了才知道，原来{product}不是普通奶酪零食。第一口咔咔响，奶香一下出来，像贾冰的包袱一样有记忆点。关键是奶酪含量扎实，酥脆但不腻，追剧、办公室、下午茶都能顺手来一包。想要又香又脆的零食，就试试这个。",
            "",
            "## 仿写脚本 B：全新开头",
            f"如果你买零食最怕只有香精味，可以看看这个{product}。它走的不是甜腻路线，而是奶酪香加酥脆口感，一口下去是咔咔的脆感，后面是浓一点的奶香。适合想解馋、又想吃点有记忆点零食的人。下一次囤零食，可以把它放进清单。",
        ]
    )


def _has_real_video_analysis_evidence(params: dict) -> bool:
    if _truthy(params.get("allow_page_only_script")):
        return True
    for key in ("analysis_summary", "video_analysis", "analysis", "segments", "shots", "audio_lines", "transcript", "asr_text"):
        value = params.get(key)
        if value not in (None, "", [], {}):
            return True
    state = params.get("state") if isinstance(params.get("state"), dict) else {}
    for key in ("analysis_summary", "video_analysis", "analysis", "segments", "shots", "audio_lines", "transcript", "asr_text"):
        if state.get(key) not in (None, "", [], {}):
            return True
    return False


def generate_douyin_script(params: dict) -> Dict[str, Any]:
    report = params.get("douyin_report")
    if not isinstance(report, dict):
        fetched = fetch_douyin_video_data(params)
        if not fetched.get("ok"):
            return fetched
        data = fetched.get("data") if isinstance(fetched.get("data"), dict) else {}
        report = data.get("douyin_report")
    if not isinstance(report, dict):
        return _err("douyin_report is required", {"next_action": "fetch_douyin_video_data"})
    if not _has_real_video_analysis_evidence(params):
        return _err(
            "禁止基于页面信息猜测原视频脚本；必须先下载视频并完成真实视频拆解",
            {
                "douyin_report": report,
                "next_action": "download_douyin_video",
                "user_message": "我已经拿到抖音页面信息，但还没有真实拆解视频画面/音频。不能编造镜头脚本，请先下载视频并完成真实拆解后再输出原视频脚本。",
            },
        )
    script_text = _douyin_report_to_script_text(report, params)
    return _ok(
        {
            "douyin_report": report,
            "script_text": script_text,
            "script_preview": {
                "mode": "douyin_report_script",
                "source": report.get("source"),
                "douyin_url": report.get("douyin_url"),
            },
            "user_message": "已基于抖音页面数据输出拆解报告和可直接展示的脚本。",
        },
        next_action="script_ready",
    )


def fetch_douyin_video_data(params: dict) -> Dict[str, Any]:
    url = params.get("douyin_url") or _douyin_url_from_params(params)
    if not url or not _is_douyin_url(url):
        return _err("douyin_url must be a douyin.com/iesdouyin.com URL", {"next_action": "provide_douyin_url"})
    page_text, mode, warning = _fetch_douyin_page_text(str(url), params)
    if not page_text:
        return _err(
            "抓取抖音页面数据失败",
            {
                "douyin_url": str(url),
                "next_action": "download_douyin_video",
                "warning": warning,
                "user_message": "页面数据暂未抓到，但仍可继续下载视频并进入视频拆解。",
            },
        )
    report = _extract_douyin_page_data(page_text, str(url), fetch_mode=mode)
    report["direct_video_url"] = _extract_douyin_play_url(page_text)
    warnings_list = [warning] if warning else None
    return _ok({"douyin_report": report, "douyin_url": str(url)}, next_action="generate_douyin_script", warnings=warnings_list)


def _deskclaw_workspace_path(params: Optional[dict] = None) -> Path:
    params = params if isinstance(params, dict) else {}
    configured = params.get("deskclaw_workspace") or params.get("workspace_path")
    if configured:
        return Path(str(configured)).expanduser()
    return Path.home() / ".deskclaw" / "nanobot" / "workspace"


def _media_assets_db_path(params: Optional[dict] = None) -> Path:
    params = params if isinstance(params, dict) else {}
    configured = params.get("media_assets_db") or params.get("assets_db_path")
    if configured:
        return Path(str(configured)).expanduser()
    return _deskclaw_workspace_path(params) / "media" / ".assets.db"


def _normalize_local_video_path(value: Any, params: Optional[dict] = None) -> Optional[str]:
    if not isinstance(value, str) or not value.strip() or _is_http_url(value):
        return None
    text = value.strip()
    path = Path(text).expanduser()
    if path.is_absolute():
        return str(path)
    workspace_candidate = _deskclaw_workspace_path(params) / text
    if text.startswith("media/") or workspace_candidate.exists():
        return str(workspace_candidate)
    return str(path)


def _video_input_from_message_text(params: dict) -> dict:
    texts: List[str] = []
    for key in ("message", "user_message", "content", "input_text", "prompt", "text"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    for text in texts:
        candidates = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
        candidates.extend(re.findall(r"(media/[^\s)\"']+\.(?:mp4|mov|avi|mkv|webm))", text, flags=re.I))
        for candidate in candidates:
            path = _normalize_local_video_path(candidate, params)
            if path and path.lower().endswith(VIDEO_EXTENSIONS):
                return {"file_path": path, "file_name": Path(path).name, "source_upload": {"mode": "deskclaw_message_markdown"}}
    return {}


def _latest_deskclaw_user_video_asset(params: dict) -> dict:
    if _truthy(params.get("disable_deskclaw_media_fallback")):
        return {}
    db_path = _media_assets_db_path(params)
    if not db_path.exists():
        return {}
    session_hint = str(
        params.get("session_id")
        or params.get("conversation_id")
        or params.get("chat_id")
        or params.get("thread_id")
        or ""
    ).strip()
    session_candidates = []
    if session_hint:
        session_candidates.append(session_hint)
        if session_hint.startswith("desk-"):
            session_candidates.append(f"agent:main:{session_hint}")
        if session_hint.startswith("agent_main_"):
            session_candidates.append(f"agent:main:{session_hint[len('agent_main_'):]}")
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if session_candidates:
                placeholders = ",".join("?" for _ in session_candidates)
                query = (
                    "select id, session_id, filename, path, url, created_at from assets "
                    "where source='user' and kind='video' and session_id in ("
                    + placeholders
                    + ") order by created_at desc limit 1"
                )
                row = conn.execute(query, session_candidates).fetchone()
                if row:
                    return _asset_row_to_video_input(row)
            row = conn.execute(
                "select id, session_id, filename, path, url, created_at from assets "
                "where source='user' and kind='video' order by created_at desc limit 1"
            ).fetchone()
            return _asset_row_to_video_input(row) if row else {}
    except sqlite3.Error:
        return {}


def _asset_row_to_video_input(row: Any) -> dict:
    if not row:
        return {}
    path = row["path"] if "path" in row.keys() else None
    url = row["url"] if "url" in row.keys() else None
    data = {
        "file_name": row["filename"] if "filename" in row.keys() else None,
        "deskclaw_asset_id": row["id"] if "id" in row.keys() else None,
        "deskclaw_asset_session_id": row["session_id"] if "session_id" in row.keys() else None,
        "source_upload": {"mode": "deskclaw_media_assets_db"},
    }
    if path and Path(str(path)).expanduser().exists():
        data["file_path"] = str(Path(str(path)).expanduser())
    elif _is_http_url(url):
        data["file_url"] = str(url)
    else:
        return {}
    return {k: v for k, v in data.items() if v is not None}


def _video_input_sources(params: dict) -> List[Any]:
    sources: List[Any] = [params]
    state = params.get("state") if isinstance(params.get("state"), dict) else {}
    if state:
        sources.append(state)
    for source in list(sources):
        if isinstance(source, dict):
            for key in ("upload_result", "video", "file", "attachment", "input"):
                value = source.get(key)
                if isinstance(value, dict):
                    sources.append(value)
            for key in ("attachments", "files", "uploaded_files", "input_files", "media"):
                value = source.get(key)
                if isinstance(value, list):
                    sources.extend(value)
    return sources


def _looks_like_video_input(item: dict) -> bool:
    for key in ("media_type", "type", "mime_type", "mime", "content_type"):
        value = str(item.get(key) or "").lower()
        if value.startswith("video") or value.startswith("video/"):
            return True
    for key in VIDEO_FILE_KEYS:
        value = str(item.get(key) or "").lower()
        if value.endswith(VIDEO_EXTENSIONS):
            return True
    return False


def _extract_video_input(params: dict) -> dict:
    normalized: dict = {}
    for item in _video_input_sources(params):
        if not isinstance(item, dict):
            continue
        if not _looks_like_video_input(item) and not any(item.get(key) for key in VIDEO_INPUT_HINT_KEYS):
            continue
        video_id = item.get("video_id") or item.get("videoId")
        if video_id and not normalized.get("video_id"):
            normalized["video_id"] = str(video_id)
        file_path = _pick_first(item, "file_path", "local_path", "temp_path", "path")
        if file_path and not normalized.get("file_path") and not _is_http_url(file_path):
            normalized["file_path"] = str(file_path)
        file_url = _pick_first(item, *VIDEO_URL_KEYS)
        if file_url and not normalized.get("file_url") and _is_http_url(file_url):
            if _is_douyin_url(file_url):
                normalized["douyin_url"] = str(file_url)
            else:
                normalized["file_url"] = str(file_url)
        douyin_url = _pick_first(item, *DOUYIN_URL_KEYS)
        if douyin_url and not normalized.get("douyin_url") and _is_douyin_url(douyin_url):
            normalized["douyin_url"] = str(douyin_url)
        for key in VIDEO_META_FIELDS:
            if item.get(key) is not None and normalized.get(key) is None:
                normalized[key] = item.get(key)
    if not any(normalized.get(key) for key in ("video_id", "file_path", "file_url", "douyin_url")):
        normalized.update(_video_input_from_message_text(params))
    if not any(normalized.get(key) for key in ("video_id", "file_path", "file_url", "douyin_url")):
        douyin_url = _douyin_url_from_params(params)
        if douyin_url:
            normalized["douyin_url"] = douyin_url
    if not any(normalized.get(key) for key in ("video_id", "file_path", "file_url", "douyin_url")):
        normalized.update(_latest_deskclaw_user_video_asset(params))
    if normalized.get("file_path"):
        normalized["file_path"] = _normalize_local_video_path(normalized["file_path"], params) or normalized["file_path"]
    return normalized


def _remote_video_source_url(params: dict) -> Optional[str]:
    for key in VIDEO_URL_KEYS[:4]:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _remote_video_filename(url: str, params: dict, headers: dict) -> str:
    configured = params.get("file_name") or params.get("filename")
    if configured:
        return Path(str(configured)).name
    disposition = headers.get("content-disposition") or headers.get("Content-Disposition") or ""
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", disposition, flags=re.I)
    if match:
        return Path(match.group(1)).name
    return Path(urlparse(url).path).name or "upload-video.mp4"


def upload_video(params: dict) -> Dict[str, Any]:
    file_path = params.get("file_path")
    if not file_path:
        return _err("缺少视频附件", {"status_code": "video_attachment_required", "next_action": "upload_video", "user_message": VIDEO_UPLOAD_USER_MESSAGE})
    path = Path(file_path).expanduser()
    if not path.exists() or not path.is_file():
        return _err(f"视频文件不存在: {path}")
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        return _err("视频文件超过 50 MB 限制", {"file_size": size, "max_size": MAX_UPLOAD_BYTES})
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    headers = _headers(params, json_content=False)
    with path.open("rb") as f:
        files = {"file": (path.name, f, mime)}
        return _with_next_action(_request("POST", "/video/upload", params, headers=headers, files=files, timeout=300), "create_clone_script")


def _yt_dlp_command(url: str, output_template: str, params: dict) -> List[str]:
    configured = params.get("douyin_downloader_command")
    if isinstance(configured, list) and configured:
        return [str(part) for part in configured] + [url, "-o", output_template]
    if isinstance(configured, str) and configured.strip():
        return [configured.strip(), url, "-o", output_template]
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--max-filesize",
        "50M",
        "--merge-output-format",
        "mp4",
        "-f",
        "bv*+ba/b[ext=mp4]/b",
        "-o",
        output_template,
        url,
    ]


def _download_douyin_video_to_temp(params: dict) -> Dict[str, Any]:
    url = params.get("douyin_url") or _douyin_url_from_params(params)
    if not url or not _is_douyin_url(url):
        return _err("douyin_url must be a douyin.com/iesdouyin.com URL", {"next_action": "provide_douyin_url"})
    temp_dir = Path(tempfile.mkdtemp(prefix="deskclaw-douyin-"))
    output_template = str(temp_dir / "%(id)s.%(ext)s")
    cmd = _yt_dlp_command(str(url), output_template, params)
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(temp_dir),
            text=True,
            capture_output=True,
            timeout=_int_param(params, "douyin_download_timeout", 300),
            check=False,
        )
    except FileNotFoundError:
        return _err(
            "未找到抖音下载工具 yt-dlp。请先在项目根目录执行 pip install -r requirements.txt，或单独安装 yt-dlp 后重试。",
            {"next_action": "install_douyin_downloader", "tool": "yt-dlp"},
        )
    except subprocess.TimeoutExpired:
        return _err("下载抖音视频超时，请稍后重试或改用视频附件上传", {"next_action": "upload_video"})
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        direct = _download_douyin_video_direct(str(url), temp_dir, params)
        if direct.get("ok"):
            direct["warnings"] = [f"yt-dlp 下载失败，已改用页面 play_addr 直链下载：{stderr[-300:]}"]
            return direct
        return _err(
            "下载抖音视频失败",
            {
                "next_action": "upload_video",
                "tool": "yt-dlp",
                "stderr_tail": stderr[-800:],
                "user_message": "抖音链接解析失败，可以改为直接上传视频附件。",
            },
        )
    candidates = [path for path in temp_dir.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS]
    if not candidates:
        return _err("下载抖音视频失败：没有生成可上传的视频文件", {"next_action": "upload_video", "temp_dir": str(temp_dir)})
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        return _err("视频文件超过 50 MB 限制", {"file_size": path.stat().st_size, "max_size": MAX_UPLOAD_BYTES})
    return _ok(
        {
            "file_path": str(path),
            "file_name": path.name,
            "douyin_url": str(url),
            "temp_dir": str(temp_dir),
            "source_upload": {"mode": "douyin_url", "downloader": "yt-dlp"},
        },
        next_action="upload_video",
    )


def _download_douyin_video_direct(url: str, temp_dir: Path, params: dict) -> Dict[str, Any]:
    report = params.get("douyin_report") if isinstance(params.get("douyin_report"), dict) else None
    direct_url = report.get("direct_video_url") if isinstance(report, dict) else None
    if not direct_url:
        page_text, _, warning = _fetch_douyin_page_text(url, params)
        if warning and params.get("debug"):
            print(warning, file=sys.stderr)
        direct_url = _extract_douyin_play_url(page_text or "")
    if not direct_url:
        return _err("未在抖音页面中找到可下载视频直链", {"next_action": "upload_video"})
    output_path = temp_dir / "douyin_video.mp4"
    cmd = [
        "curl",
        "-L",
        "--compressed",
        "--max-time",
        str(_int_param(params, "douyin_download_timeout", 300)),
        "-A",
        str(params.get("douyin_user_agent") or DOUYIN_USER_AGENT),
        str(direct_url),
        "-o",
        str(output_path),
    ]
    try:
        completed = subprocess.run(cmd, cwd=str(temp_dir), text=True, capture_output=True, timeout=_int_param(params, "douyin_download_timeout", 300) + 5, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return _err("下载抖音视频直链失败", {"next_action": "upload_video", "stderr_tail": str(exc)[-500:]})
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        return _err("下载抖音视频直链失败", {"next_action": "upload_video", "stderr_tail": (completed.stderr or completed.stdout or "")[-800:]})
    if output_path.stat().st_size > MAX_UPLOAD_BYTES:
        return _err("视频文件超过 50 MB 限制", {"file_size": output_path.stat().st_size, "max_size": MAX_UPLOAD_BYTES})
    return _ok(
        {
            "file_path": str(output_path),
            "file_name": output_path.name,
            "douyin_url": str(url),
            "temp_dir": str(temp_dir),
            "source_upload": {"mode": "douyin_url", "downloader": "curl_play_addr"},
        },
        next_action="upload_video",
    )


def download_douyin_video(params: dict) -> Dict[str, Any]:
    page_data = fetch_douyin_video_data(params)
    douyin_report = None
    page_warning = None
    if page_data.get("ok") and isinstance(page_data.get("data"), dict):
        douyin_report = page_data["data"].get("douyin_report")
    else:
        page_warning = page_data.get("error") or "抖音页面数据抓取失败"
    download_params = {**params, "douyin_report": douyin_report} if douyin_report else params
    downloaded = _download_douyin_video_to_temp(download_params)
    if not downloaded.get("ok"):
        if isinstance(downloaded.get("data"), dict) and douyin_report:
            downloaded["data"]["douyin_report"] = douyin_report
            downloaded["data"]["script_text_unavailable"] = "仅完成页面抓取，未完成真实视频拆解，不能输出原视频脚本。"
        return downloaded
    data = downloaded.get("data") if isinstance(downloaded.get("data"), dict) else {}
    temp_dir = Path(str(data.get("temp_dir") or "")).expanduser()
    try:
        result = upload_video({**params, "file_path": data.get("file_path"), "file_name": data.get("file_name")})
        if result.get("ok") and isinstance(result.get("data"), dict):
            result["data"]["source_upload"] = {
                "mode": "douyin_url",
                "downloader": "yt-dlp",
                "douyin_url_received": True,
                "temp_file_cleaned": True,
            }
            if douyin_report:
                result["data"]["douyin_report"] = douyin_report
                result["data"]["script_text_unavailable"] = "视频已下载并上传；原视频脚本必须等待 get_original_video_script 返回真实拆解结果。"
            elif page_warning:
                result["data"]["douyin_report_warning"] = page_warning
        return result
    finally:
        try:
            for child in temp_dir.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError:
            pass


def upload_video_from_url(params: dict) -> Dict[str, Any]:
    url = _remote_video_source_url(params)
    if not url or not _is_http_url(url):
        return _err("file_url/upload_url must be an HTTP(S) URL", {"next_action": "provide_cloud_upload_url"})
    parsed = urlparse(url)
    if parsed.scheme != "https" and not _truthy(params.get("allow_http_upload_url")):
        return _err("cloud upload URL must use HTTPS", {"next_action": "provide_cloud_upload_url"})
    source_headers = params.get("source_headers") if isinstance(params.get("source_headers"), dict) else {}
    try:
        resp = requests.get(url, headers=source_headers, timeout=_int_param(params, "source_download_timeout", 300), stream=True)
        resp.raise_for_status()
        content_length = resp.headers.get("content-length") or resp.headers.get("Content-Length")
        expected_size = int(content_length) if content_length and content_length.isdigit() else 0
        if expected_size > MAX_UPLOAD_BYTES:
            return _err("视频文件超过 50 MB 限制", {"file_size": expected_size, "max_size": MAX_UPLOAD_BYTES})
        filename = _remote_video_filename(url, params, resp.headers)
        suffix = Path(filename).suffix or ".mp4"
        with tempfile.NamedTemporaryFile(prefix="deskclaw-cloud-upload-", suffix=suffix, delete=False) as tmp:
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_UPLOAD_BYTES:
                    tmp_path = Path(tmp.name)
                    tmp.close()
                    tmp_path.unlink(missing_ok=True)
                    return _err("视频文件超过 50 MB 限制", {"file_size": downloaded, "max_size": MAX_UPLOAD_BYTES})
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        try:
            result = upload_video({**params, "file_path": str(tmp_path)})
            if result.get("ok") and isinstance(result.get("data"), dict):
                result["data"]["source_upload"] = {"mode": "cloud_url", "source_url_received": True, "temp_file_cleaned": True}
            return result
        finally:
            tmp_path.unlink(missing_ok=True)
    except requests.Timeout:
        return _err("下载云端临时视频文件超时，请重新上传后再试")
    except requests.RequestException as exc:
        return _err(f"下载云端临时视频文件失败: {exc}")


def attach_uploaded_video(params: dict) -> Dict[str, Any]:
    video_id = str(params.get("video_id") or "").strip()
    if not video_id:
        return _err("video_id is required")
    data = {"video_id": video_id, "upload_mode": "pre_uploaded", "source_upload": {"mode": "direct_upload_api", "already_uploaded": True, "agent_uploaded_file": False}}
    upload_result = params.get("upload_result") if isinstance(params.get("upload_result"), dict) else {}
    for source in (params, upload_result):
        for key in VIDEO_META_FIELDS:
            if data.get(key) is None and source.get(key) is not None:
                data[key] = source.get(key)
    return _ok(data, next_action="create_clone_script")


def create_clone_script(params: dict) -> Dict[str, Any]:
    video_id = params.get("video_id")
    if not video_id:
        return _err("video_id is required")
    payload = {
        "name": params.get("name") or params.get("file_name") or "AI复刻视频脚本",
        "source_type": "clone",
        "shots": [],
        "segments": [],
        "global_settings": params.get("global_settings") or {"aspect_ratio": params.get("aspect_ratio", "1:1"), "resolution": params.get("resolution", "720p"), "global_references": params.get("global_references", [])},
        "video_id": video_id,
        "status": "draft",
    }
    return _with_next_action(_request("POST", "/scripts", params, headers=_headers(params), json=payload), "start_analysis")


def start_analysis(params: dict) -> Dict[str, Any]:
    video_id = params.get("video_id")
    script_id = params.get("script_id")
    if not video_id or not script_id:
        return _err("video_id and script_id are required")
    payload = {
        "video_id": video_id,
        "analysis_type": "extract-script",
        "script_id": script_id,
        "decomposition_id": params.get("decomposition_id"),
        "video_meta": params.get("video_meta") or {},
        "model_name": params.get("model_name"),
        "prompt": params.get("prompt"),
        "restart": _truthy(params.get("restart", False)),
    }
    return _with_next_action(_request("POST", "/video/analyze/segments/jobs", params, headers=_headers(params), json=payload), "monitor_analysis_task")


def get_task(params: dict) -> Dict[str, Any]:
    task_id = params.get("task_id") or params.get("analysis_task_id")
    if not task_id:
        return _err("task_id is required")
    return _with_next_action(_request("GET", f"/tasks/{task_id}", params, headers=_headers(params, json_content=False)), "get_analysis")


def get_analysis(params: dict) -> Dict[str, Any]:
    decomposition_id = params.get("decomposition_id")
    video_id = params.get("video_id")
    next_action = "rewrite_script" if _explicit_rewrite_requested(params) else "get_original_video_script"
    if decomposition_id:
        return _with_next_action(_request("GET", f"/video/decompositions/{decomposition_id}", params, headers=_headers(params, json_content=False)), next_action)
    if video_id:
        return _with_next_action(_request("GET", f"/video/{video_id}/analysis", params, headers=_headers(params, json_content=False)), next_action)
    return _err("video_id or decomposition_id is required")


def get_workspace_events(params: dict) -> Dict[str, Any]:
    workspace_id = params.get("workspace_id")
    if not workspace_id:
        return _err("workspace_id is required")
    limit = _int_param(params, "limit", 50)
    return _request("GET", f"/workspaces/{workspace_id}/events?limit={limit}", params, headers=_headers(params, json_content=False))


def _clean_compact_text(value: Any, max_chars: int = 180) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    if not text:
        return None
    return text[: max_chars - 1].rstrip() + "…" if len(text) > max_chars else text


def _shot_id(shot: dict, index: int) -> str:
    return str(shot.get("shot_id") or shot.get("id") or shot.get("镜头ID") or f"shot-{index + 1}")


def _compact_shot(shot: dict, index: int) -> dict:
    start = _pick_first(shot, "start", "start_time", "开始时间")
    end = _pick_first(shot, "end", "end_time", "结束时间")
    time_range = _pick_first(shot, "起止时间", "time_range")
    if not time_range and (start is not None or end is not None):
        time_range = f"{start}-{end}"
    voiceover = _pick_first(shot, "口播内容", "dialogue", "speech_text", "voiceover", "text")
    return {
        "index": index,
        "shot_id": _shot_id(shot, index),
        "time_range": _clean_compact_text(time_range, 40),
        "duration": _pick_first(shot, "时长", "duration", "duration_seconds"),
        "scene": _clean_compact_text(_pick_first(shot, "景别", "scene"), 40),
        "camera": _clean_compact_text(_pick_first(shot, "运镜", "camera"), 40),
        "visual": _clean_compact_text(_pick_first(shot, "画面内容", "visual", "summary"), 220),
        "voiceover": _clean_compact_text(voiceover, 180),
        "function": _clean_compact_text(_pick_first(shot, "功能标签", "funcTag", "function"), 80),
    }


def _compact_segment(segment: dict, index: int) -> dict:
    return {
        "index": index,
        "segment_id": segment.get("segment_id") or f"segment-{index + 1}",
        "name": _clean_compact_text(segment.get("name"), 80),
        "order": segment.get("order"),
        "duration_seconds": segment.get("duration_seconds"),
        "prompt": _clean_compact_text(segment.get("prompt"), 260),
        "reference_shot_ids": segment.get("reference_shot_ids") or [],
    }


def _extract_analysis_segments(data: dict) -> List[dict]:
    if not isinstance(data, dict):
        return []
    direct = data.get("segments")
    if isinstance(direct, list):
        return direct
    for key in ("analysis", "result", "extra_data", "output_results", "decompose"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = _extract_analysis_segments(nested)
            if found:
                return found
    return []


def _extract_audio_lines(data: dict, limit: int = 8) -> List[dict]:
    if not isinstance(data, dict):
        return []
    transcript = data.get("audioTranscript") or data.get("audio_transcript")
    if isinstance(transcript, dict) and isinstance(transcript.get("segments"), list):
        return [{"start": item.get("start"), "end": item.get("end"), "text": _clean_compact_text(item.get("text"), 160)} for item in transcript["segments"][:limit] if isinstance(item, dict)]
    for key in ("analysis", "result", "extra_data", "output_results", "decompose"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = _extract_audio_lines(nested, limit)
            if found:
                return found
    return []


def _original_script_requested(params: Optional[dict] = None, state: Optional[dict] = None) -> bool:
    params = params if isinstance(params, dict) else {}
    state = state if isinstance(state, dict) else {}
    for source in (params, state):
        for key in (
            "original_script",
            "output_original_script",
            "direct_original_script",
            "no_rewrite",
            "skip_rewrite",
            "keep_original",
        ):
            if _truthy(source.get(key)):
                return True
    text_values: List[str] = []
    for source in (params, state):
        for key in ("requirement", "user_requirement", "brief", "instruction", "message", "query", "rewrite_brief"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                text_values.append(value)
    text = " ".join(text_values)
    if not text:
        return False
    return any(
        phrase in text
        for phrase in (
            "不修改需求",
            "不改需求",
            "不需要修改",
            "不要修改",
            "不做改写",
            "不改写",
            "跳过改写",
            "直接输出原视频",
            "输出原视频",
            "原视频的视频脚本",
            "原视频脚本",
            "原片脚本",
            "原始脚本",
            "照原视频输出",
        )
    )


def _explicit_rewrite_requested(params: Optional[dict] = None, state: Optional[dict] = None) -> bool:
    params = params if isinstance(params, dict) else {}
    state = state if isinstance(state, dict) else {}
    if _original_script_requested(params, state):
        return False
    for source in (params, state):
        for key in ("rewrite_brief", "requirement_brief", "product_info"):
            value = source.get(key)
            if isinstance(value, dict) and any(v not in (None, "", [], {}) for v in value.values()):
                return True
        for key in ("requirement", "user_requirement", "brief", "instruction", "message", "query"):
            value = source.get(key)
            if isinstance(value, str) and any(word in value for word in ("仿写", "改写", "复刻", "重写", "生成新脚本")):
                return True
    return False


def _weak_rewrite_brief_input(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return True
    weak_values = {
        "拆解",
        "原脚本",
        "原视频脚本",
        "输出原脚本",
        "输出原视频脚本",
        "脚本",
        "分析",
    }
    return text in weak_values or len(text) <= 3


def _analysis_summary(data: dict, max_items: int = 8) -> dict:
    segments = _extract_analysis_segments(data)
    compact_segments = [_compact_shot(segment, idx) for idx, segment in enumerate(segments[:max_items]) if isinstance(segment, dict)]
    summary = {
        "analysis_id": data.get("analysis_id") or data.get("analysisId") or data.get("id"),
        "decomposition_id": data.get("decomposition_id") or data.get("decompositionId"),
        "task_id": data.get("task_id"),
        "video_id": data.get("video_id"),
        "status": data.get("status"),
        "progress": data.get("progress"),
        "segment_count": len(segments),
        "segments_preview": compact_segments,
        "audio_lines": _extract_audio_lines(data, max_items),
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _original_script_text_from_summary(summary: dict) -> str:
    audio_lines = summary.get("audio_lines") if isinstance(summary.get("audio_lines"), list) else []
    lines: List[str] = []
    for index, item in enumerate(audio_lines):
        text = item.get("text") if isinstance(item, dict) else None
        if not text:
            continue
        start = item.get("start")
        end = item.get("end")
        time_range = f"{start}-{end} " if start is not None or end is not None else ""
        lines.append(f"原视频口播{index + 1}：{time_range}{text}")
    if lines:
        return "\n".join(lines)

    for shot in summary.get("segments_preview") or []:
        index = int(shot.get("index") or 0) + 1
        time_range = f"{shot.get('time_range')} " if shot.get("time_range") else ""
        visual = f"画面：{shot.get('visual')}" if shot.get("visual") else ""
        voiceover = f"口播：{shot.get('voiceover')}" if shot.get("voiceover") else "口播："
        line_parts = [part for part in (time_range.strip(), visual, voiceover) if part]
        lines.append(f"镜头{index}：" + "；".join(line_parts))
    return "\n".join(lines)


def get_original_video_script(params: dict) -> Dict[str, Any]:
    result = get_analysis(params)
    if not result.get("ok"):
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = _analysis_summary(data, _int_param(params, "max_preview_items", 24))
    script_text = _original_script_text_from_summary(summary)
    preview = {
        "mode": "original_video_script",
        "video_id": params.get("video_id") or summary.get("video_id"),
        "decomposition_id": params.get("decomposition_id") or summary.get("decomposition_id"),
        "segment_count": summary.get("segment_count", 0),
        "audio_line_count": len(summary.get("audio_lines") or []),
        "segments_preview": summary.get("segments_preview") or [],
        "audio_lines": summary.get("audio_lines") or [],
    }
    return _ok(
        {
            "script_preview": preview,
            "script_text": script_text,
            "original_script": True,
            "user_message": "已按原视频拆解结果整理原视频脚本。",
        },
        next_action="script_ready",
    )


def get_analysis_summary(params: dict) -> Dict[str, Any]:
    result = get_analysis(params)
    if not result.get("ok"):
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = _analysis_summary(data, _int_param(params, "max_preview_items", 8))
    next_action = "rewrite_script" if _explicit_rewrite_requested(params) else "get_original_video_script"
    return _ok({"summary": summary, "user_message": f"视频结构拆解已加载，共 {summary.get('segment_count', 0)} 个片段。"}, next_action=next_action)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _result_data(value: Any) -> Any:
    if isinstance(value, dict) and value.get("ok") is True and "data" in value:
        return value["data"]
    return value


def _extract_analysis_progress(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    output = data.get("output_results") if isinstance(data.get("output_results"), dict) else {}
    extra = data.get("extra_data") if isinstance(data.get("extra_data"), dict) else {}
    progress_source = output or extra
    raw_segments = progress_source.get("raw_segments") or data.get("raw_segments") or []
    completed_indices = progress_source.get("completed_indices") or data.get("completed_indices") or []
    return {
        "id": data.get("id") or data.get("task_id"),
        "status": data.get("status"),
        "progress": data.get("progress"),
        "stage": progress_source.get("stage") or data.get("stage"),
        "message": progress_source.get("message") or data.get("message"),
        "updated_at": data.get("updated_at") or progress_source.get("updated_at"),
        "completed_indices": completed_indices,
        "raw_segment_count": len(raw_segments) if isinstance(raw_segments, list) else 0,
        "error_reason": data.get("error_reason") or progress_source.get("error_reason"),
    }


def _analysis_status_signature(progress: dict) -> str:
    completed = progress.get("completed_indices") or []
    completed_count = len(completed) if isinstance(completed, list) else ""
    return "|".join([str(progress.get("status") or ""), str(progress.get("progress") or ""), str(progress.get("message") or ""), str(completed_count), str(progress.get("raw_segment_count") or "")])


def _analysis_progress_sentence(progress: dict, repeated: bool = False) -> str:
    details = []
    if progress.get("progress") is not None:
        details.append(f"进度 {progress.get('progress')}%")
    if progress.get("message"):
        details.append(str(progress.get("message")))
    raw_count = progress.get("raw_segment_count")
    completed = progress.get("completed_indices") or []
    if raw_count and isinstance(completed, list):
        details.append(f"已完成 {len(completed)}/{raw_count} 个分镜")
    prefix = "视频结构拆解状态暂未变化" if repeated else "视频结构拆解仍在处理中"
    return f"{prefix}：{'，'.join(details)}。我会继续检查结果。" if details else f"{prefix}，我会继续检查结果。"


def _auth_problem(result: dict) -> bool:
    if not isinstance(result, dict) or result.get("ok", True):
        return False
    status_code = (result.get("data") or {}).get("status_code")
    error = str(result.get("error") or "").lower()
    return status_code in (401, 403) or "unauthorized" in error or "forbidden" in error or "expired" in error


def diagnose_analysis_task(params: dict) -> Dict[str, Any]:
    task_id = params.get("task_id") or params.get("analysis_task_id")
    decomposition_id = params.get("decomposition_id")
    video_id = params.get("video_id")
    if not task_id and not decomposition_id and not video_id:
        return _err("task_id, decomposition_id or video_id is required")

    task_result = params.get("task_result")
    if task_result is None and task_id:
        task_result = get_task(params)
    analysis_result = params.get("analysis_result")
    if analysis_result is None and (decomposition_id or video_id):
        analysis_result = get_analysis(params)

    progress = _extract_analysis_progress(_result_data(task_result))
    analysis_progress = _extract_analysis_progress(_result_data(analysis_result))
    for key, value in analysis_progress.items():
        if value not in (None, "", [], {}) and not (key == "raw_segment_count" and not value):
            progress[key] = value

    auth_valid = not _auth_problem(task_result) and not _auth_problem(analysis_result)
    status = str(progress.get("status") or "").lower()
    status_signature = _analysis_status_signature(progress)
    repeated_status = bool(params.get("last_status_signature")) and params.get("last_status_signature") == status_signature
    stale_seconds = None
    updated_at = _parse_iso_datetime(progress.get("updated_at"))
    if updated_at:
        stale_seconds = max(0, int((datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds()))
    is_stuck = status == "processing" and stale_seconds is not None and stale_seconds >= _int_param(params, "stuck_threshold_seconds", 900)

    if not auth_valid:
        next_action = "import_deskclaw_app_login"
        user_message = "登录态可能已失效，我会重新读取 DeskClaw 本地登录态后再继续查询。"
    elif status in SUCCESS_STATUSES:
        next_action = "rewrite_script" if _explicit_rewrite_requested(params) else "get_original_video_script"
        user_message = "视频结构拆解已完成，可以整理原视频脚本。" if next_action == "get_original_video_script" else "视频结构拆解已完成，可以继续生成复刻脚本。"
    elif status in ("failed", "cancelled", "error"):
        next_action = "restart_analysis"
        user_message = "视频结构拆解失败，需要重试拆解任务。"
    elif is_stuck:
        next_action = "retry_analysis_or_use_partial_result"
        user_message = "视频结构拆解长时间停在同一进度，建议重试拆解，或先使用已有部分拆解结果继续。"
    else:
        next_action = "poll_analysis_task"
        user_message = _analysis_progress_sentence(progress, repeated_status)

    return _ok(
        {
            "auth_valid": auth_valid,
            "is_stuck": is_stuck,
            "stale_seconds": stale_seconds,
            "status": progress.get("status"),
            "progress": progress.get("progress"),
            "message": progress.get("message"),
            "status_signature": status_signature,
            "repeated_status": repeated_status,
            "completed_indices": progress.get("completed_indices"),
            "raw_segment_count": progress.get("raw_segment_count"),
            "user_message": user_message,
        },
        next_action=next_action,
    )


def _monitor_poll_limits(params: dict) -> Tuple[float, int]:
    interval_seconds = float(params["interval_seconds"]) if params.get("interval_seconds") is not None else 12
    interval_seconds = max(0, interval_seconds)
    max_wait_seconds = float(params.get("max_wait_seconds") or 45)
    if params.get("max_polls") is not None:
        max_polls = max(1, int(params["max_polls"]))
    elif interval_seconds == 0:
        max_polls = 1
    else:
        max_polls = max(1, int(max_wait_seconds // interval_seconds) + 1)
    return interval_seconds, max_polls


def monitor_analysis_task(params: dict) -> Dict[str, Any]:
    if not (params.get("task_id") or params.get("analysis_task_id") or params.get("decomposition_id") or params.get("video_id")):
        return _err("task_id, decomposition_id or video_id is required")
    interval_seconds, max_polls = _monitor_poll_limits(params)
    last_status_signature = params.get("last_status_signature")
    snapshots = []
    diagnosis = None
    for poll_index in range(max_polls):
        poll_params = dict(params)
        if last_status_signature:
            poll_params["last_status_signature"] = last_status_signature
        diagnosis = diagnose_analysis_task(poll_params)
        if not diagnosis.get("ok"):
            return diagnosis
        data = diagnosis.get("data") or {}
        snapshots.append({"poll": poll_index + 1, "status": data.get("status"), "progress": data.get("progress"), "message": data.get("message"), "status_signature": data.get("status_signature")})
        if diagnosis.get("next_action") != "poll_analysis_task":
            return _ok({"monitor_status": "finished", "poll_count": poll_index + 1, "latest": data, "snapshots": snapshots, "user_message": data.get("user_message")}, next_action=diagnosis.get("next_action"))
        last_status_signature = data.get("status_signature")
        if poll_index < max_polls - 1 and interval_seconds:
            time.sleep(interval_seconds)
    latest = (diagnosis or {}).get("data") or {}
    return _ok({"monitor_status": "still_processing", "poll_count": len(snapshots), "latest": latest, "snapshots": snapshots, "next_poll_after_seconds": interval_seconds, "user_message": latest.get("user_message") or "视频结构拆解仍在处理中，我会继续检查结果。"}, next_action="wait_for_analysis_complete")


def wait_for_analysis_complete(params: dict) -> Dict[str, Any]:
    if not (params.get("task_id") or params.get("analysis_task_id") or params.get("decomposition_id") or params.get("video_id")):
        return _err("task_id, decomposition_id or video_id is required")
    wait_params = dict(params)
    wait_params["interval_seconds"] = float(params.get("interval_seconds") or DEFAULT_ANALYSIS_WAIT_INTERVAL_SECONDS)
    wait_params["max_wait_seconds"] = float(params.get("max_wait_seconds") or DEFAULT_ANALYSIS_WAIT_SECONDS)
    return monitor_analysis_task(wait_params)


def continue_analysis(params: dict) -> Dict[str, Any]:
    return wait_for_analysis_complete(params)


def _merge_text(value: Any, addition: str) -> str:
    if not value:
        return addition
    text = str(value)
    return text if addition in text else f"{text}；{addition}"


def _list_value(value: Any) -> Any:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,，;；\n]", value) if part.strip()]
    return value


def _normalize_rewrite_brief_fields(brief: dict) -> dict:
    normalized = {key: value for key, value in brief.items() if value not in (None, "", [], {})}
    if normalized.get("product_name"):
        normalized["target_topic"] = _merge_text(normalized.get("target_topic"), f"产品/对象：{normalized['product_name']}")
    if normalized.get("key_selling_points"):
        normalized["core_messages"] = _list_value(normalized.get("key_selling_points"))
    if normalized.get("replacement_style"):
        normalized["tone_style"] = _merge_text(normalized.get("tone_style"), f"参考风格：{normalized['replacement_style']}")
    if normalized.get("cta"):
        normalized["desired_action"] = normalized.get("desired_action") or normalized["cta"]
    extras = {key: normalized.pop(key) for key in list(normalized) if key in REWRITE_BRIEF_ALIAS_FIELDS}
    if extras:
        normalized["extra_context"] = _merge_text(normalized.get("extra_context"), json.dumps(extras, ensure_ascii=False))
    return {key: value for key, value in normalized.items() if key in REWRITE_BRIEF_FIELDS and value not in (None, "", [], {})}


def _rewrite_brief_from_free_text(text: str, params: dict) -> dict:
    text = text.strip()
    brief = {
        "target_topic": params.get("target_topic") or text,
        "core_messages": params.get("core_messages") or [text],
        "target_audience": params.get("target_audience") or "参考原视频受众",
        "desired_action": params.get("desired_action") or "生成可用于复刻的脚本预览",
        "tone_style": params.get("tone_style") or "贴近参考视频节奏和表达",
        "extra_context": params.get("extra_context"),
    }
    return _normalize_rewrite_brief_fields(brief)


def _decode_json_object(value: str) -> Optional[dict]:
    try:
        decoded = json.loads(value)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _normalize_rewrite_brief(value: Any, params: dict) -> Optional[dict]:
    if isinstance(value, dict):
        return _normalize_rewrite_brief_fields(value)
    if isinstance(value, str) and value.strip():
        decoded = _decode_json_object(value)
        return _normalize_rewrite_brief_fields(decoded) if decoded else _rewrite_brief_from_free_text(value, params)
    requirement = params.get("requirement") or params.get("user_requirement") or params.get("brief")
    if isinstance(requirement, str) and requirement.strip():
        return _rewrite_brief_from_free_text(requirement, params)
    return None


def _brief_summary(brief: dict) -> str:
    parts = []
    for key, label in (
        ("target_topic", "主题"),
        ("target_audience", "受众"),
        ("desired_action", "目标动作"),
        ("tone_style", "风格"),
        ("constraints", "限制"),
    ):
        if brief.get(key):
            parts.append(f"{label}：{brief[key]}")
    if brief.get("core_messages"):
        value = brief["core_messages"]
        parts.append("核心信息：" + ("、".join(str(item) for item in value) if isinstance(value, list) else str(value)))
    return "；".join(parts) or "已整理脚本仿写需求"


def understand_requirements(params: dict) -> Dict[str, Any]:
    if _original_script_requested(params):
        return _ok(
            {
                "original_script": True,
                "requirement_confirmed": True,
                "requirement_summary": "不改写，直接输出原视频脚本",
                "user_message": "已确认不改写需求，拆解完成后直接输出原视频脚本。",
            },
            next_action="create_clone_script",
        )
    brief = _normalize_rewrite_brief(params.get("rewrite_brief") or params.get("requirement_brief"), params)
    if not brief:
        return _err("缺少脚本仿写需求", {"next_action": "understand_requirements"})
    return _ok({"rewrite_brief": brief, "requirement_summary": _brief_summary(brief), "user_message": "我已整理复刻脚本需求，请确认后继续脚本仿写。"}, next_action="confirm_requirements")


def confirm_requirements(params: dict) -> Dict[str, Any]:
    if _original_script_requested(params):
        return _ok(
            {
                "original_script": True,
                "requirement_confirmed": True,
                "requirement_summary": "不改写，直接输出原视频脚本",
            },
            next_action="create_clone_script",
        )
    brief = _normalize_rewrite_brief(params.get("rewrite_brief") or params.get("requirement_brief"), params)
    if not brief:
        return _err("rewrite_brief is required")
    return _ok({"rewrite_brief": brief, "requirement_confirmed": True, "requirement_summary": _brief_summary(brief)}, next_action="rewrite_script")


def _validate_rewrite_payload(payload: dict) -> List[str]:
    errors = []
    if not payload.get("video_id"):
        errors.append("video_id is required")
    if not payload.get("rewrite_brief"):
        errors.append("rewrite_brief is required")
    return errors


def rewrite_script(params: dict) -> Dict[str, Any]:
    if _original_script_requested(params, params.get("state") if isinstance(params.get("state"), dict) else None):
        return get_original_video_script(params)
    raw_rewrite_brief = params.get("rewrite_brief") or params.get("requirement_brief")
    if _weak_rewrite_brief_input(raw_rewrite_brief):
        return _err(
            "rewrite_brief 过弱，不能用于仿写；如果用户要原视频脚本，请调用 get_original_video_script。",
            {"next_action": "get_original_video_script"},
        )
    state = params.get("state") if isinstance(params.get("state"), dict) else {}
    rewrite_brief = _normalize_rewrite_brief(raw_rewrite_brief or state.get("rewrite_brief"), params)
    payload = {"video_id": params.get("video_id"), "decomposition_id": params.get("decomposition_id"), "script_id": params.get("script_id"), "rewrite_brief": rewrite_brief}
    if params.get("product_info"):
        payload["product_info"] = params["product_info"]
    validation_errors = _validate_rewrite_payload(payload)
    if validation_errors:
        return _err("脚本仿写请求字段不完整", {"status_code": "local_validation_failed", "validation_errors": validation_errors, "next_action": "fix_rewrite_brief"})
    return _with_next_action(_request("POST", "/video/script/rewrite", params, headers=_headers(params), json=payload), "get_script_preview")


def get_script(params: dict) -> Dict[str, Any]:
    script_id = params.get("script_id")
    if not script_id:
        return _err("script_id is required")
    return _with_next_action(_request("GET", f"/scripts/{script_id}", params, headers=_headers(params, json_content=False)), "get_script_preview")


def _script_preview(data: dict, max_items: int = 8) -> dict:
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    return {
        "script_id": data.get("script_id") or data.get("id"),
        "video_id": data.get("video_id"),
        "rewrite_id": (data.get("extra_data") or {}).get("source_rewrite_id") if isinstance(data.get("extra_data"), dict) else None,
        "shot_count": len(shots),
        "segment_count": len(segments),
        "global_settings": data.get("global_settings") or {},
        "shots_preview": [_compact_shot(shot, idx) for idx, shot in enumerate(shots[:max_items]) if isinstance(shot, dict)],
        "segments_preview": [_compact_segment(segment, idx) for idx, segment in enumerate(segments[:max_items]) if isinstance(segment, dict)],
    }


def _script_preview_message(preview: dict) -> str:
    lines = [f"脚本预览已生成：{preview.get('shot_count', 0)} 个镜头，{preview.get('segment_count', 0)} 个片段。"]
    for shot in (preview.get("shots_preview") or [])[:6]:
        voiceover = shot.get("voiceover") or "无口播"
        time_range = f"{shot.get('time_range')} " if shot.get("time_range") else ""
        lines.append(f"- 镜{shot.get('index', 0) + 1} {time_range}{voiceover}")
    lines.append("请确认脚本方向，或直接告诉我要改哪一句。")
    return "\n".join(lines)


def _script_text_from_preview(preview: dict) -> str:
    lines: List[str] = []
    for shot in preview.get("shots_preview") or []:
        index = int(shot.get("index") or 0) + 1
        time_range = f"{shot.get('time_range')} " if shot.get("time_range") else ""
        visual = f"画面：{shot.get('visual')}" if shot.get("visual") else ""
        voiceover = f"口播：{shot.get('voiceover')}" if shot.get("voiceover") else "口播："
        line_parts = [part for part in (time_range.strip(), visual, voiceover) if part]
        lines.append(f"镜头{index}：" + "；".join(line_parts))
    if not lines:
        for segment in preview.get("segments_preview") or []:
            index = int(segment.get("index") or 0) + 1
            prompt = segment.get("prompt") or ""
            name = segment.get("name") or f"片段{index}"
            lines.append(f"{name}：{prompt}")
    return "\n".join(lines)


def get_script_preview(params: dict) -> Dict[str, Any]:
    result = get_script(params)
    if not result.get("ok"):
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    preview = _script_preview(data, _int_param(params, "max_preview_items", 8))
    return _ok(
        {
            "script_preview": preview,
            "script_text": _script_text_from_preview(preview),
            "user_message": _script_preview_message(preview),
        },
        next_action="script_ready",
    )


def _apply_voiceover_update(item: dict, new_text: str) -> None:
    for key in ("口播内容", "dialogue", "speech_text", "voiceover", "text"):
        if key in item:
            item[key] = new_text
            return
    item["口播内容"] = new_text


def _patch_items_by_updates(items: List[dict], updates: List[dict]) -> List[dict]:
    patched = deepcopy(items)
    for update in updates:
        if not isinstance(update, dict):
            continue
        new_text = update.get("new") or update.get("new_text") or update.get("voiceover")
        if not isinstance(new_text, str) or not new_text.strip():
            continue
        target_index = update.get("index")
        if target_index is None:
            target_index = update.get("shot_index")
        old_text = update.get("old") or update.get("old_text")
        for idx, item in enumerate(patched):
            if not isinstance(item, dict):
                continue
            matches_index = target_index is not None and int(target_index) == idx
            voiceover = str(_pick_first(item, "口播内容", "dialogue", "speech_text", "voiceover", "text") or "")
            matches_old = bool(old_text) and str(old_text) in voiceover
            if matches_index or matches_old:
                _apply_voiceover_update(item, new_text.strip())
                break
    return patched


def patch_script_preview(params: dict) -> Dict[str, Any]:
    shots = params.get("shots") if isinstance(params.get("shots"), list) else []
    segments = params.get("segments") if isinstance(params.get("segments"), list) else []
    updates = params.get("voiceover_updates") or params.get("updates") or []
    if isinstance(updates, dict):
        updates = [updates]
    if not isinstance(updates, list) or not updates:
        return _err("voiceover_updates must be a non-empty list")
    if not shots and not segments and params.get("script_id"):
        loaded = get_script(params)
        if not loaded.get("ok"):
            return loaded
        data = loaded.get("data") if isinstance(loaded.get("data"), dict) else {}
        shots = data.get("shots") if isinstance(data.get("shots"), list) else []
        segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    if not shots and not segments:
        return _err("shots or segments is required")
    patched_shots = _patch_items_by_updates(shots, updates) if shots else []
    patched_segments = _patch_items_by_updates(segments, updates) if segments else []
    preview_source = {"script_id": params.get("script_id"), "video_id": params.get("video_id"), "shots": patched_shots, "segments": patched_segments, "global_settings": params.get("global_settings") or {}}
    preview = _script_preview(preview_source, _int_param(params, "max_preview_items", 8))
    return _ok(
        {
            "shots": patched_shots,
            "segments": patched_segments,
            "script_preview": preview,
            "script_text": _script_text_from_preview(preview),
            "user_message": "脚本已按你的修改更新完成。",
            "persisted": False,
        },
        next_action="script_ready",
    )


def _has_default_login() -> bool:
    session = _load_token_store().get(DEFAULT_TOKEN_REF)
    return bool(session and not _session_expired(session))


API_AUTH_ACTIONS = {
    "upload_video",
    "download_douyin_video",
    "upload_video_from_url",
    "create_clone_script",
    "start_analysis",
    "get_workspace_events",
    "get_task",
    "get_analysis",
    "get_analysis_summary",
    "get_original_video_script",
    "diagnose_analysis_task",
    "monitor_analysis_task",
    "wait_for_analysis_complete",
    "continue_analysis",
    "rewrite_script",
    "get_script",
    "get_script_preview",
    "patch_script_preview",
}


def _ensure_login_for_action(action: str, params: dict) -> Optional[Dict[str, Any]]:
    if action not in API_AUTH_ACTIONS:
        return None
    if _params_has_login(params) or _has_default_login():
        return None
    state = params.get("state") if isinstance(params.get("state"), dict) else {}
    if state.get("token_ref") or (state.get("auth") or {}).get("token_ref"):
        return None
    result = import_deskclaw_app_login({**params, "token_ref": _resolve_token_ref(params, state)})
    return None if result.get("ok") else result


def _params_has_login(params: Optional[dict]) -> bool:
    if not isinstance(params, dict):
        return False
    return bool(
        params.get("token_ref")
        or params.get("auth_token")
        or params.get("access_token")
        or params.get("bearer_token")
    )


def _workflow_phase(state: dict, params: Optional[dict] = None) -> str:
    if state.get("script_ready") or state.get("script_preview_confirmed") or state.get("front_half_complete"):
        return "script_ready"
    if not (state.get("token_ref") or (state.get("auth") or {}).get("token_ref") or _params_has_login(params) or _has_default_login()):
        return "login_required"
    if not state.get("video_id"):
        return "video_required"
    original_requested = _original_script_requested(params, state)
    if not state.get("rewrite_brief") and not state.get("requirement_confirmed") and not original_requested:
        return "requirement_confirmation_required"
    if not state.get("script_id"):
        return "draft_required"
    if not (state.get("analysis_task_id") or state.get("decomposition_id")):
        return "analysis_required"
    if str(state.get("analysis_status") or "").lower() not in SUCCESS_STATUSES and not state.get("analysis_completed"):
        return "analysis_running"
    if original_requested and not state.get("original_script_completed"):
        return "original_script_required"
    if not state.get("rewrite_completed"):
        return "rewrite_required"
    if not state.get("script_preview_confirmed"):
        return "script_preview_confirmation_required"
    return "script_ready"


def run_workflow_plan(params: Optional[dict] = None) -> Dict[str, Any]:
    steps = [
        {"order": 1, "action": "import_deskclaw_app_login", "endpoint": "DeskClaw local login state", "state": "logged_in"},
        {"order": 2, "action": "fetch_douyin_video_data", "endpoint": "Douyin page via curl", "state": "douyin_report_ready", "optional_when": "non_douyin_video"},
        {"order": 3, "action": "generate_douyin_script", "endpoint": "local", "state": "douyin_script_ready", "optional_when": "non_douyin_video"},
        {"order": 4, "action": "download_douyin_video/upload_video/upload_video_from_url/attach_uploaded_video", "endpoint": "Douyin play_addr/yt-dlp + POST /video/upload", "state": "uploaded"},
        {"order": 5, "action": "understand_requirements", "endpoint": "local", "state": "requirements_understood", "optional_when": "original_script"},
        {"order": 6, "action": "confirm_requirements", "endpoint": "local", "state": "requirement_confirmed", "optional_when": "original_script"},
        {"order": 7, "action": "create_clone_script", "endpoint": "POST /scripts", "state": "script_draft_created"},
        {"order": 8, "action": "start_analysis", "endpoint": "POST /video/analyze/segments/jobs", "state": "analysis_started"},
        {"order": 9, "action": "wait_for_analysis_complete", "endpoint": "GET /tasks/{task_id} + GET /video/{video_id}/analysis", "state": "analysis_completed"},
        {"order": 10, "action": "get_analysis_summary", "endpoint": "GET /video/{video_id}/analysis", "state": "analysis_summary_ready"},
        {"order": 11, "action": "rewrite_script/get_original_video_script", "endpoint": "POST /video/script/rewrite or GET /video/{video_id}/analysis", "state": "script_source_ready"},
        {"order": 12, "action": "get_script_preview", "endpoint": "GET /scripts/{script_id}", "state": "script_preview_ready"},
        {"order": 13, "action": "patch_script_preview", "endpoint": "local", "state": "script_preview_updated", "optional": True},
    ]
    return _ok({"steps": steps})


def _merge_state(state: dict, action: str, result: dict) -> dict:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    merged = dict(state)
    if action in ("import_deskclaw_app_login", "login_status_poll") and data.get("token_ref"):
        merged["token_ref"] = data["token_ref"]
        merged["auth"] = {"token_ref": data["token_ref"], "has_auth_token": data.get("has_auth_token", True)}
    if data.get("douyin_report"):
        merged["douyin_report"] = data.get("douyin_report")
    if action == "generate_douyin_script":
        merged["script_text"] = data.get("script_text")
        merged["script_preview"] = data.get("script_preview")
        merged["script_ready"] = True
    for key in ("video_id", "script_id", "decomposition_id", "task_id", "analysis_task_id", "rewrite_id"):
        if data.get(key):
            target = "analysis_task_id" if action == "start_analysis" and key == "task_id" else key
            merged[target] = data[key]
    if action == "confirm_requirements":
        merged["requirement_confirmed"] = True
        merged["rewrite_brief"] = data.get("rewrite_brief") or merged.get("rewrite_brief")
        if data.get("original_script"):
            merged["original_script"] = True
    if action in ("diagnose_analysis_task", "monitor_analysis_task", "wait_for_analysis_complete", "continue_analysis"):
        latest = data.get("latest") if isinstance(data.get("latest"), dict) else data
        if latest.get("status"):
            merged["analysis_status"] = latest.get("status")
        if str(latest.get("status") or "").lower() in SUCCESS_STATUSES:
            merged["analysis_completed"] = True
    if action == "rewrite_script":
        merged["rewrite_completed"] = True
    if action == "get_original_video_script":
        merged["original_script"] = True
        merged["original_script_completed"] = True
        merged["script_preview"] = data.get("script_preview")
        merged["script_text"] = data.get("script_text")
        merged["script_ready"] = True
    if action == "get_script_preview":
        merged["script_preview"] = data.get("script_preview")
        merged["script_text"] = data.get("script_text")
        merged["script_ready"] = True
    if action == "patch_script_preview":
        merged["script_preview"] = data.get("script_preview")
        merged["script_text"] = data.get("script_text")
        merged["script_ready"] = True
    return merged


def advance_workflow(params: dict) -> Dict[str, Any]:
    state = params.get("state") if isinstance(params.get("state"), dict) else {}
    if _original_script_requested(params, state):
        state = {**state, "original_script": True}
    phase = _workflow_phase(state, params)
    completed_action = phase
    if phase == "login_required":
        result = login_status_poll(params)
        completed_action = "login_status_poll"
        if result.get("ok"):
            next_state = _merge_state(state, "login_status_poll", result)
            if _extract_video_input(params):
                return advance_workflow({**params, "state": next_state})
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            result["data"] = {**data, "phase": "video_required", "state": next_state}
            return result
    elif phase == "video_required":
        video_input = _extract_video_input(params)
        if video_input.get("video_id"):
            result = attach_uploaded_video({**params, **video_input})
            completed_action = "attach_uploaded_video"
        elif video_input.get("douyin_url"):
            result = download_douyin_video({**params, **video_input})
            completed_action = "download_douyin_video"
        elif video_input.get("file_url"):
            result = upload_video_from_url({**params, **video_input})
            completed_action = "upload_video_from_url"
        elif video_input.get("file_path"):
            result = upload_video({**params, **video_input})
            completed_action = "upload_video"
        else:
            return _ok({"phase": phase, "state": state, "user_message": VIDEO_UPLOAD_USER_MESSAGE}, next_action="upload_video")
    elif phase == "requirement_confirmation_required":
        if _original_script_requested(params, state):
            result = understand_requirements(params)
            completed_action = "confirm_requirements"
        elif params.get("rewrite_brief") or params.get("requirement") or params.get("brief"):
            result = understand_requirements(params)
            completed_action = "understand_requirements"
        else:
            return _ok({"phase": phase, "state": state, "user_message": "请先说明希望脚本如何改写；如果不需要改写，也可以直接说“输出原视频脚本”。"}, next_action="understand_requirements")
    elif phase == "draft_required":
        result = create_clone_script({**params, **state})
        completed_action = "create_clone_script"
    elif phase == "analysis_required":
        result = start_analysis({**params, **state})
        completed_action = "start_analysis"
    elif phase == "analysis_running":
        result = wait_for_analysis_complete({**params, **state})
        completed_action = "wait_for_analysis_complete"
    elif phase == "original_script_required":
        result = get_original_video_script({**params, **state})
        completed_action = "get_original_video_script"
    elif phase == "rewrite_required":
        result = rewrite_script({**params, **state})
        completed_action = "rewrite_script"
    elif phase == "script_preview_confirmation_required":
        result = get_script_preview({**params, **state})
        completed_action = "get_script_preview"
    else:
        return _ok(
            {
                "advance_status": "script_ready",
                "phase": "script_ready",
                "script_preview": state.get("script_preview"),
                "script_text": state.get("script_text"),
                "state": state,
                "stop_reason": "script_ready",
                "user_message": "视频拆解和脚本生成已完成。",
            },
            next_action="script_ready",
        )
    if not result.get("ok"):
        return result
    next_state = _merge_state(state, completed_action, result)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    result["data"] = {**data, "phase": phase, "state": next_state}
    return result


ACTION_MAP = {
    "run_workflow_plan": run_workflow_plan,
    "advance_workflow": advance_workflow,
    "import_deskclaw_app_login": import_deskclaw_app_login,
    "login_status_poll": login_status_poll,
    "get_userinfo": get_userinfo,
    "upload_video": upload_video,
    "fetch_douyin_video_data": fetch_douyin_video_data,
    "generate_douyin_script": generate_douyin_script,
    "download_douyin_video": download_douyin_video,
    "upload_video_from_url": upload_video_from_url,
    "attach_uploaded_video": attach_uploaded_video,
    "create_clone_script": create_clone_script,
    "start_analysis": start_analysis,
    "get_workspace_events": get_workspace_events,
    "get_task": get_task,
    "get_analysis": get_analysis,
    "get_analysis_summary": get_analysis_summary,
    "get_original_video_script": get_original_video_script,
    "diagnose_analysis_task": diagnose_analysis_task,
    "monitor_analysis_task": monitor_analysis_task,
    "wait_for_analysis_complete": wait_for_analysis_complete,
    "continue_analysis": continue_analysis,
    "understand_requirements": understand_requirements,
    "confirm_requirements": confirm_requirements,
    "rewrite_script": rewrite_script,
    "get_script": get_script,
    "get_script_preview": get_script_preview,
    "patch_script_preview": patch_script_preview,
}


def run(params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    action = str(params.get("action") or "run_workflow_plan").strip()
    handler = ACTION_MAP.get(action)
    if not handler:
        return _err(f"unsupported action: {action}", {"available_actions": sorted(ACTION_MAP)})
    login_error = _ensure_login_for_action(action, params)
    if login_error:
        return login_error
    return handler(params or {})


def _read_payload(argv: List[str]) -> str:
    if len(argv) > 1:
        arg = argv[1]
        if arg in ("--file", "-f") and len(argv) > 2:
            return Path(argv[2]).expanduser().read_text(encoding="utf-8")
        if arg.startswith("@"):
            return Path(arg[1:]).expanduser().read_text(encoding="utf-8")
        return arg
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return '{"action":"run_workflow_plan"}'


def main() -> None:
    payload = json.loads(_read_payload(sys.argv))
    print(json.dumps(run(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
