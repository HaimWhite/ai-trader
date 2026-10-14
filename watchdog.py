"""PC 꺼짐 감시: GitHub 가 평일 17:30(한국 시간)에 실행해서, 오늘 16:00 정기 점검 기록이 올라왔는지 확인하고
없으면 디스코드 DM 으로 알려줍니다. (PC 와 별개로 돌기 때문에 PC 가 꺼져 있어도 알림이 가요.)
- 공휴일에도 16:00 점검은 돌기 때문에, 기록이 없으면 확인이 필요한 상황이에요.
- 디스코드 정보는 GitHub 의 Secrets(DISCORD_BOT_TOKEN, DISCORD_USER_ID)에서 읽어요.
- 테스트: python watchdog.py --test   (무조건 테스트 메시지 1건을 보냅니다)"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
BOSS = "하임님"
API = "https://discord.com/api/v10"


def post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body else {}


def send(text):
    token, user, hook = os.environ.get("DISCORD_BOT_TOKEN"), os.environ.get("DISCORD_USER_ID"), os.environ.get("DISCORD_WEBHOOK_URL")
    if token and user:
        h = {"Authorization": "Bot " + token, "Content-Type": "application/json", "User-Agent": "DiscordBot (ai-trader-watchdog, 1.0)"}
        ch = post(API + "/users/@me/channels", {"recipient_id": user}, h)["id"]
        post(f"{API}/channels/{ch}/messages", {"content": text[:1900]}, h)
        return True
    if hook:
        post(hook, {"content": text[:1900]}, {"Content-Type": "application/json", "User-Agent": "ai-trader-watchdog"})
        return True
    print("디스코드 설정(Secrets)이 없어서 알림을 보내지 못했어요:\n" + text)
    return False


def prev_weekday(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def target_day(now):
    """어느 날의 기록을 확인할지. GitHub 의 예약 실행은 몇 시간씩 늦게 시작될 때가 있어서,
    17:00 이전(새벽 등)에 시작했으면 '오늘'이 아니라 직전 평일의 기록을 확인해요."""
    if now.weekday() < 5 and now.strftime("%H:%M") >= "17:00":
        return now.date()
    d = now.date()
    return prev_weekday(d) if now.weekday() >= 5 or now.strftime("%H:%M") < "17:00" else d


def main(path="data/latest.json", now=None):
    now = now or (datetime.fromisoformat(os.environ["WATCHDOG_NOW"]).replace(tzinfo=KST) if os.environ.get("WATCHDOG_NOW") else datetime.now(KST))
    if "--test" in sys.argv:
        ok = send(f"{BOSS}, 감시 장치 테스트입니다. 이 메시지가 보이면 PC 꺼짐 알림이 정상으로 연결된 거예요.")
        print("테스트 메시지 전송:", ok)
        return 0 if ok else 1
    if now.weekday() >= 5:
        print("주말이라 확인하지 않아요.")
        return 0
    try:
        updated = json.load(open(path, encoding="utf-8"))["updated_at"]
    except Exception as e:
        updated = ""
        print("latest.json 을 읽지 못했어요:", e)
    target = target_day(now).strftime("%Y-%m-%d")
    late = target != now.strftime("%Y-%m-%d")
    if updated and (updated[:10] > target or (updated[:10] == target and updated[11:16] >= "15:35")):
        print(f"{target} 정기 점검 기록이 있어요:", updated, "(늦게 시작된 실행)" if late else "")
        return 0
    when = f"{target[5:7]}월 {target[8:10]}일" if late else "오늘"
    text = (f"{BOSS}, {when} 16:00 정기 점검 기록이 GitHub에 올라오지 않았습니다.\n"
            f"마지막 기록은 {updated or '확인 불가'}입니다.\n"
            "PC가 꺼져 있거나 절전 상태이거나, 인터넷·로그인 문제로 업로드가 막혔을 수 있습니다. (공휴일에도 점검은 돌기 때문에 확인이 필요합니다.)\n"
            "PC를 켜신 뒤 run_auto.bat 를 한 번 실행하시면 기록이 올라갑니다.")
    print(text)
    send(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
