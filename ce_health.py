"""코드이터 이상 알림 (가볍게 확인만 해요). advisor.py --poll 이 10분마다 부르고, 문제가 있으면 하루에 한 종류당 한 번만 디스코드로 알려요.
  ① 평일 09:40~16:30 인데 탐색 기록이 40분 넘게 갱신되지 않을 때
  ② 금요일 17:00 이후인데 오늘 16:30 적용 기록이 없을 때
  ③ 최근 2시간 안에 탐색 오류가 5번 이상 쌓였을 때"""
import json
from datetime import datetime

import config
import notify

ALERTS = config.DATA_DIR / "ce_alerts.json"


def _load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _age_min(ts, now=None):
    try:
        return ((now or datetime.now()) - datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
    except Exception:
        return None


def check(now=None):
    now = now or datetime.now()
    if now.weekday() >= 5:
        return []
    today = now.strftime("%Y-%m-%d")
    hm = (now.hour, now.minute)
    stat = _load(config.DATA_DIR / "status.json", {})
    st = _load(config.DATA_DIR / "codeeater.json", {})
    done = _load(ALERTS, {})
    if done.get("date") != today:
        done = {"date": today, "sent": []}
    found = []
    if (9, 40) <= hm <= (16, 30):
        age = _age_min((stat.get("codeeater_scout") or {}).get("time", ""), now)
        if age is None or age > 40:
            found.append(("scout", "코드이터 탐색이 멈춘 것 같아요 (40분 넘게 기록이 없어요). PC 가 절전 중이거나 프로그램이 꺼졌을 수 있어요. python check_codeeater.py 로 확인해 보세요."))
    if now.weekday() == 4 and hm >= (17, 0):
        ap = (stat.get("codeeater") or {}).get("time", "")
        if not ap.startswith(today):
            found.append(("apply", "오늘 금요일 16:30 코드이터 적용 기록이 없어요. python codeeater.py --apply 로 직접 실행하거나 python check_codeeater.py 로 확인해 보세요."))
    errs = [e for e in ((st.get("pool") or {}).get("errors") or [])]
    recent = 0
    for e in errs:
        try:
            t = datetime.strptime(f"{now.year}-{e[:11]}", "%Y-%m-%d %H:%M")
            if (now - t).total_seconds() < 7200:
                recent += 1
        except Exception:
            pass
    if recent >= 5:
        found.append(("errors", f"코드이터 탐색 오류가 최근 2시간에 {recent}번 났어요. GitHub 호출 한도(토큰이 없으면 작아요)나 Ollama 문제일 수 있어요. python check_codeeater.py 로 확인해 보세요."))
    sent = []
    for kind, text in found:
        if kind in done["sent"]:
            continue
        notify.send(f"하임님, {text}", mention=True)
        done["sent"].append(kind)
        sent.append(kind)
    if sent:
        config.DATA_DIR.mkdir(exist_ok=True)
        with open(ALERTS, "w", encoding="utf-8") as f:
            json.dump(done, f)
    return sent


if __name__ == "__main__":
    print(check() or "이상 없음")
