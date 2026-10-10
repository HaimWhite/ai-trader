"""고점 대비 낙폭을 계산하고, 단계(-10/-15/-20/-25/-30%)를 새로 넘을 때마다 한 번씩만 알립니다.
상태는 data/alerts.json 에 저장돼요 (같은 단계는 다시 알리지 않고, -5% 안으로 회복하면 해제)."""
import json

import config

LEVELS = (10, 15, 20, 25, 30)
RESET_PCT = 5   # 이 안으로 회복하면 경보를 해제


def current(history, initial=None):
    """history(마지막이 오늘) 기준 현재 낙폭 정보. 고점은 시작 자금과 기록된 자산 중 가장 큰 값"""
    initial = initial or config.INITIAL_CASH
    peak, peak_date = float(initial), "시작"
    max_dd = 0.0
    run_peak = float(initial)
    for h in history:
        e = float(h["equity"])
        if e > peak:
            peak, peak_date = e, h["date"]
        run_peak = max(run_peak, e)
        max_dd = min(max_dd, (e / run_peak - 1) * 100)
    eq = float(history[-1]["equity"]) if history else float(initial)
    return {"dd": (eq / peak - 1) * 100, "peak": peak, "peak_date": peak_date, "equity": eq, "max_dd": max_dd}


def level_of(dd):
    hit = [l for l in LEVELS if dd <= -l]
    return max(hit) if hit else 0


def decide(dd):
    """알릴 일이 있으면 'deeper' / 'recover', 없으면 None 을 돌려주고 상태를 갱신합니다."""
    path = config.DATA_DIR / "alerts.json"
    state = {"level": 0}
    if path.exists():
        try:
            state = json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    lvl, old, kind = level_of(dd), int(state.get("level", 0)), None
    if lvl > old:
        kind = "deeper"
        state["level"] = lvl
    elif old > 0 and dd > -RESET_PCT:
        kind = "recover"
        state["level"] = 0
    elif lvl < old and lvl > 0:
        state["level"] = lvl   # 조금 회복했다가 다시 깊어지면 다시 알리도록 단계만 낮춤
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return kind, lvl


def backtest_mdd():
    p = config.DATA_DIR / "backtest.json"
    try:
        return float(json.load(open(p, encoding="utf-8"))["strategy"]["mdd"])
    except Exception:
        return None
