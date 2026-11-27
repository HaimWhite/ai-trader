"""코드이터 이상 알림 (가볍게 확인만 해요). advisor.py --poll 이 10분마다 부르고, 문제가 있으면 하루에 한 종류당 한 번만 디스코드로 알려요.
  ① PC 를 켠 지 25분이 지났는데 탐색 기록이 40분 넘게 갱신되지 않을 때 (탐색은 PC 가 켜진 동안 계속 돌아요)
  ② 금요일 16:45 이후인데 오늘 16:15 적용 기록이 없을 때
  ③ 최근 2시간 안에 탐색 오류가 5번 이상 쌓였을 때
  ④ 학습 데이터가 1000개가 되면 '파인튜닝 할까요?' 를 바로 한 번 물어봐요 (보류하면 500개 더 쌓였을 때 다시)"""
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


def _uptime_min():
    """윈도우가 켜진 지 몇 분인지 (모르면 None). 막 켠 직후에는 탐색이 아직 시작 전이라 알림을 미뤄요."""
    try:
        import ctypes
        return ctypes.windll.kernel32.GetTickCount64() / 60000.0
    except Exception:
        return None


def check(now=None):
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    hm = (now.hour, now.minute)
    stat = _load(config.DATA_DIR / "status.json", {})
    st = _load(config.DATA_DIR / "codeeater.json", {})
    done = _load(ALERTS, {})
    if done.get("date") != today:
        done = {"date": today, "sent": []}
    found = []
    up = _uptime_min()
    if up is None or up >= 25:
        age = _age_min((stat.get("codeeater_scout") or {}).get("time", ""), now)
        if age is None or age > 40:
            found.append(("scout", "코드이터 탐색이 멈춘 것 같아요 (40분 넘게 기록이 없어요). PC 가 절전 중이거나 프로그램이 꺼졌을 수 있어요. python check_codeeater.py 로 확인해 보세요."))
    if now.weekday() == 4 and hm >= (16, 45):
        ap = (stat.get("codeeater") or {}).get("time", "")
        if not ap.startswith(today):
            found.append(("apply", "오늘 금요일 16:15 코드이터 적용 기록이 없어요. python codeeater.py --apply 로 직접 실행하거나 python check_codeeater.py 로 확인해 보세요."))
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
    try:   # 학습 데이터가 기준(1000개)을 넘으면 금요일을 기다리지 않고 바로 '파인튜닝 할까요?' 를 한 번 물어봐요
        import codeknow
        kk = codeknow.read()
        if codeknow.ask_finetune(kk):
            codeknow.write(kk)
            sent.append("finetune_ask")
    except Exception:
        pass
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
