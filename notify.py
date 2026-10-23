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


LAST_MESSAGE_ID = None   # 방금 보낸 DM 의 번호 (답장을 찾을 때 기준으로 씀)


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_replies(after_id):
    """after_id 이후에 하임님이 DM 으로 보낸 글 목록(오래된 순). 실패하면 None."""
    token, user = _env("DISCORD_BOT_TOKEN"), _env("DISCORD_USER_ID")
    if not token or not user or not after_id:
        return None
    base = _env("DISCORD_API_BASE") or "https://discord.com/api/v10"
    headers = {"Authorization": "Bot " + token, "Content-Type": "application/json", "User-Agent": "DiscordBot (ai-trader, 1.0)"}
    try:
        channel = _post(base + "/users/@me/channels", {"recipient_id": user}, headers)["id"]
        msgs = _get(f"{base}/channels/{channel}/messages?after={after_id}&limit=50", headers)
    except Exception as e:
        print("디스코드 답장 확인 실패:", e)
        return None
    mine = [m for m in msgs if str(m.get("author", {}).get("id")) == str(user)]   # 본인이 보낸 글만 인정
    return sorted(mine, key=lambda m: int(m["id"]))


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
        global LAST_MESSAGE_ID
        LAST_MESSAGE_ID = _post(f"{base}/channels/{channel}/messages", payload, headers).get("id")
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
