"""주간 리포트: 최근 7일의 성과를 정리해서 디스코드로 보냅니다. 실행: python weekly_report.py"""
import json
from datetime import datetime, timedelta

import config
import messages
import notify
import status


def _read(name, default):
    p = config.DATA_DIR / name
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def build():
    hist, trades = _read("history.json", []), _read("trades.json", [])
    latest, account, idxs = _read("latest.json", {}), _read("account.json", {"positions": {}}), _read("indices.json", {})
    tune = _read("tuning_log.json", [])
    today = datetime.now().date()
    start = (today - timedelta(days=7)).isoformat()
    base = [h for h in hist if h["date"] <= start]
    base = base[-1] if base else (hist[0] if hist else {"equity": config.INITIAL_CASH})
    equity = hist[-1]["equity"] if hist else config.INITIAL_CASH
    change = equity - base["equity"]

    index = {}
    for key, v in idxs.items():
        past = [c for d, c in zip(v["dates"], v["close"]) if d <= start]
        if past and v["close"]:
            index[v["name"]] = (v["close"][-1] / past[-1] - 1) * 100

    wt = [t for t in trades if t["time"][:10] > start]
    sells = [t for t in wt if t["side"] == "SELL"]
    holdings = []
    for code, p in account["positions"].items():
        price = latest.get("symbols", {}).get(code, {}).get("price", p["avg_price"])
        holdings.append({"name": p["name"], "qty": p["qty"], "ret": (price / p["avg_price"] - 1) * 100})
    tuning = []
    for e in tune:
        if e["time"][:10] > start and e["status"] in ("applied", "pending", "rejected"):
            tuning.append({"applied": "적용됨", "pending": "승인 대기 중인 제안이 있습니다", "rejected": "거절한 제안이 있습니다"}[e["status"]])
    return {
        "start": start[5:], "end": today.isoformat()[5:], "equity": equity, "change": change,
        "change_pct": change / base["equity"] * 100 if base["equity"] else 0, "index": index,
        "buys": sum(1 for t in wt if t["side"] == "BUY"), "sells": len(sells), "wins": sum(1 for t in sells if t["pnl"] > 0),
        "pnl": sum(t["pnl"] for t in sells), "holdings": holdings, "tuning": tuning,
    }


if __name__ == "__main__":
    text = messages.weekly_message(build())
    print(text)
    notify.send(text)   # 무음 DM
    status.beat("weekly", True, "주간 리포트")
