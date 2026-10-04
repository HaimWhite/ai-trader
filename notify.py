"""디스코드 알림.
1순위: 봇이 본인에게 개인 DM (DISCORD_BOT_TOKEN, DISCORD_USER_ID)
2순위: 웹훅 채널 (DISCORD_WEBHOOK_URL) - 봇 DM이 안 될 때의 대체 수단
설정값은 .env 파일에서 읽습니다."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def _env(key):
    val = os.environ.get(key)
    if val:
        return val
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body else {}


def _send_dm(message, loud):
    token, user = _env("DISCORD_BOT_TOKEN"), _env("DISCORD_USER_ID")
    if not token or not user:
        return False
    base = _env("DISCORD_API_BASE") or "https://discord.com/api/v10"
    headers = {"Authorization": "Bot " + token, "Content-Type": "application/json", "User-Agent": "DiscordBot (ai-trader, 1.0)"}
    try:
        channel = _post(base + "/users/@me/channels", {"recipient_id": user}, headers)["id"]
        payload = {"content": message[:1900]}
        if not loud:
            payload["flags"] = 4096   # 무음 (푸시 알림 없이 도착)
        _post(f"{base}/channels/{channel}/messages", payload, headers)
        return True
    except urllib.error.HTTPError as e:
        print("디스코드 DM 실패:", e.code, e.read().decode("utf-8", "ignore")[:200])
    except Exception as e:
        print("디스코드 DM 실패:", e)
    return False


def _send_webhook(message, mention):
    url = _env("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    payload = {"content": message[:1900]}
    if mention:
        user, role = _env("DISCORD_USER_ID"), _env("DISCORD_ROLE_ID")
        tags = (f"<@{user}> " if user else "") + (f"<@&{role}> " if role else "")
        if tags:
            payload["content"] = tags + payload["content"]
            payload["allowed_mentions"] = {"parse": [], "users": [user] if user else [], "roles": [role] if role else []}
    try:
        _post(url, payload, {"Content-Type": "application/json", "User-Agent": "ai-trader"})
        return True
    except Exception as e:
        print("디스코드 웹훅 실패:", e)
        return False


def send(message, mention=False):
    """mention=True: 중요한 알림 (푸시 알림이 울림) / False: 무음 DM으로 조용히 전달"""
    if _send_dm(message, loud=mention):
        return True
    return _send_webhook(message, mention)
