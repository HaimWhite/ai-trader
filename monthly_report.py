"""월간 리포트: 그 달의 마지막 평일 저녁에 한 달 성과를 정리해서 디스코드로 보냅니다.
  python monthly_report.py            오늘이 이번 달 마지막 평일일 때만 보냄 (이미 보냈으면 건너뜀)
  python monthly_report.py --now      날짜와 상관없이 이번 달 리포트를 지금 보냄 (시험용)
  python monthly_report.py --print    보내지 않고 내용만 보기"""
import json
import sys
from datetime import date, datetime, timedelta

import config
import messages
import notify
import status


def _read(name, default):
    p = config.DATA_DIR / name
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def is_last_weekday(d):
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return d.weekday() < 5 and n.month != d.month


def build(today=None):
    today = today or datetime.now().date()
    ym = today.strftime("%Y-%m")
    first = today.replace(day=1).isoformat()
    hist, trades = _read("history.json", []), _read("trades.json", [])
    base = [h for h in hist if h["date"] < first]
    base = base[-1]["equity"] if base else config.INITIAL_CASH
    cur = [h for h in hist if h["date"][:7] == ym]
    equity = cur[-1]["equity"] if cur else base
    peak, worst = base, 0.0
    for h in cur:
        peak = max(peak, h["equity"])
        worst = min(worst, h["equity"] / peak - 1)
    mt = [t for t in trades if t["time"][:7] == ym]
    sells = [t for t in mt if t["side"] == "SELL"]
    idx = {}
    for v in _read("indices.json", {}).values():
        past = [c for d, c in zip(v["dates"], v["close"]) if d < first]
        if past and v["close"]:
            idx[v["name"]] = (v["close"][-1] / past[-1] - 1) * 100
    by = {}
    for t in sells:
        by[t["name"]] = by.get(t["name"], 0) + t["pnl"]
    ranked = sorted(by.items(), key=lambda x: x[1])
    return {
        "month": today.month, "equity": equity, "change": equity - base,
        "change_pct": (equity / base - 1) * 100 if base else 0,
        "total_pct": (equity / config.INITIAL_CASH - 1) * 100, "worst_dd": worst * 100, "index": idx,
        "buys": sum(1 for t in mt if t["side"] == "BUY"), "sells": len(sells),
        "wins": sum(1 for t in sells if t["pnl"] > 0), "pnl": sum(t["pnl"] for t in sells),
        "best": ranked[-1] if ranked and ranked[-1][1] > 0 else None,
        "worst": ranked[0] if ranked and ranked[0][1] < 0 else None,
        "reasons": {r: sum(1 for t in sells if t["reason"] == r) for r in ("손절", "추적손절") if any(t["reason"] == r for t in sells)},
        "days": len(cur),
    }


def main():
    today = datetime.now().date()
    d = build(today)
    text = messages.monthly_message(d)
    if "--print" in sys.argv:
        print(text)
        return
    ym = today.strftime("%Y-%m")
    log = _read("monthly.json", [])
    if "--now" not in sys.argv:
        if not is_last_weekday(today):
            print("오늘은 이번 달 마지막 평일이 아니라서 건너뜁니다.")
            return
        if any(e["month"] == ym for e in log):
            print("이번 달 리포트는 이미 보냈어요.")
            return
    print(text)
    notify.send(text)
    if "--now" not in sys.argv:
        log.append({"month": ym, "sent": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        config.DATA_DIR.mkdir(exist_ok=True)
        json.dump(log, open(config.DATA_DIR / "monthly.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    status.beat("monthly", True, "월간 리포트")


if __name__ == "__main__":
    main()
