"""거래 복기: 지금까지의 실제(가상 계좌) 운영 결과를 정리해서 data/review.json 에 저장합니다. 실행: python review.py
- 청산 이유별(손절 / 추적 손절 / 추세 이탈 / 수동) 성과, 월별 수익률(코스피·나스닥 비교), 실운영 vs 같은 기간 백테스트
- main.py 가 16:00 점검 때 자동으로 갱신해요."""
import json
from datetime import datetime

import config


def _load(name, default):
    p = config.DATA_DIR / f"{name}.json"
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return default


def reason_kind(r):
    r = str(r or "")
    if r == "손절":
        return "손절"
    if r == "추적손절":
        return "추적 손절"
    if "하락 추세" in r:
        return "추세 이탈"
    if "수동" in r:
        return "수동"
    return "기타"


def _day(t):
    return datetime.strptime(t[:10], "%Y-%m-%d")


def closed_trades(trades):
    """매도 거래마다 직전 매수와 짝지어 수익률(%)과 보유 일수를 계산"""
    last_buy, out = {}, []
    for t in sorted(trades, key=lambda x: x["time"]):
        if t["side"] == "BUY":
            last_buy[t["code"]] = t
        elif t["side"] == "SELL":
            b = last_buy.get(t["code"])
            cost = b["price"] * t["qty"] if b else None
            out.append({"code": t["code"], "name": t["name"], "date": t["time"][:10], "pnl": t["pnl"],
                        "pct": round(t["pnl"] / cost * 100, 2) if cost else None,
                        "days": (_day(t["time"]) - _day(b["time"])).days if b else None,
                        "kind": reason_kind(t.get("reason")), "group": config.group_of(t["code"])})
    return out


def _agg(rows):
    pcts = [r["pct"] for r in rows if r["pct"] is not None]
    days = [r["days"] for r in rows if r["days"] is not None]
    wins = [r for r in rows if r["pnl"] > 0]
    return {"n": len(rows), "wins": len(wins), "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0,
            "avg_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "avg_days": round(sum(days) / len(days), 1) if days else None,
            "pnl": round(sum(r["pnl"] for r in rows))}


def monthly(history, indices):
    """월말 자산 기준 월별 수익률(%)과 같은 달 지수 등락(%)"""
    if not history:
        return []
    ends = {}
    for h in history:
        ends[h["date"][:7]] = h["equity"]
    months = sorted(ends)
    out, prev = [], float(config.INITIAL_CASH)
    first_date = history[0]["date"]

    def idx_ret(key, month, first):
        x = (indices or {}).get(key)
        if not x:
            return None
        d, c = x["dates"], x["close"]
        m_end = [i for i, dd in enumerate(d) if dd[:7] == month]
        if not m_end:
            return None
        end = c[m_end[-1]]
        before = [i for i, dd in enumerate(d) if dd[:7] < month]
        if before:
            start = c[before[-1]]
        else:   # 첫 달: 실운영 시작일 이후 첫 값부터
            after = [i for i, dd in enumerate(d) if dd >= first]
            start = c[after[0]] if after else None
        return round((end / start - 1) * 100, 2) if start else None

    for m in months:
        e = ends[m]
        out.append({"month": m, "ret": round((e / prev - 1) * 100, 2), "equity": round(e),
                    "kospi": idx_ret("KS11", m, first_date), "nasdaq": idx_ret("IXIC", m, first_date)})
        prev = e
    return out


def live_vs_backtest(history, bt):
    """실운영 기간과 같은 기간의 백테스트 수익률 비교"""
    if len(history) < 2 or not bt or not bt.get("curve"):
        return None
    d0, d1 = history[0]["date"], history[-1]["date"]
    curve = bt["curve"]
    a = next((r for r in curve if r["date"] >= d0), None)
    b = [r for r in curve if r["date"] <= d1]
    if not a or not b or b[-1]["date"] <= a["date"]:
        return None
    live = (history[-1]["equity"] / history[0]["equity"] - 1) * 100
    back = (b[-1]["strategy"] / a["strategy"] - 1) * 100
    return {"start": d0, "end": d1, "days": (_day(d1) - _day(d0)).days, "live": round(live, 2), "backtest": round(back, 2),
            "diff": round(live - back, 2)}


def shape(rows):
    """수익이 어떤 모양으로 나는지: 소수의 큰 이익에 얼마나 기대는지 (자르고 달리기 전략의 특징)"""
    wins = sorted((r["pnl"] for r in rows if r["pnl"] > 0), reverse=True)
    loss = [r["pnl"] for r in rows if r["pnl"] <= 0]
    if not rows:
        return None
    gw, gl = sum(wins), sum(loss)
    pcts = [r["pct"] for r in rows if r["pct"] is not None and r["pnl"] > 0]
    wd = [r["days"] for r in rows if r["pnl"] > 0 and r["days"] is not None]
    ld = [r["days"] for r in rows if r["pnl"] <= 0 and r["days"] is not None]
    return {
        "gross_win": round(gw), "gross_loss": round(gl), "net": round(gw + gl),
        "n_win": len(wins), "n_loss": len(loss),
        "top1_share": round(wins[0] / gw * 100, 1) if gw else None,
        "top3_share": round(sum(wins[:3]) / gw * 100, 1) if gw else None,
        "net_wo_top1": round(gw + gl - wins[0]) if wins else None,
        "big_wins": sum(1 for p in pcts if p >= 20),
        "win_days": round(sum(wd) / len(wd), 1) if wd else None,
        "loss_days": round(sum(ld) / len(ld), 1) if ld else None,
    }


def build():
    trades, history = _load("trades", []), _load("history", [])
    rows = closed_trades(trades)
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    by_group = {}
    for r in rows:
        by_group.setdefault(r["group"], []).append(r)
    wins = [r["pct"] for r in rows if r["pct"] is not None and r["pnl"] > 0]
    losses = [r["pct"] for r in rows if r["pct"] is not None and r["pnl"] <= 0]
    summary = _agg(rows)
    summary["avg_win"] = round(sum(wins) / len(wins), 2) if wins else None
    summary["avg_loss"] = round(sum(losses) / len(losses), 2) if losses else None
    summary["payoff"] = round(abs(summary["avg_win"] / summary["avg_loss"]), 2) if wins and losses and summary["avg_loss"] else None
    best = max((r for r in rows if r["pct"] is not None), key=lambda r: r["pct"], default=None)
    worst = min((r for r in rows if r["pct"] is not None), key=lambda r: r["pct"], default=None)
    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "shape": shape(rows),
        "best": {"name": best["name"], "pct": best["pct"], "date": best["date"]} if best else None,
        "worst": {"name": worst["name"], "pct": worst["pct"], "date": worst["date"]} if worst else None,
        "by_kind": {k: _agg(v) for k, v in by_kind.items()},
        "by_group": {k: _agg(v) for k, v in by_group.items()},
        "monthly": monthly(history, _load("indices", {})),
        "live_vs_bt": live_vs_backtest(history, _load("backtest", None)),
    }


COMMENT_SYSTEM = (
    "당신은 개인 주식 자동매매 기록을 쉬운 말로 설명해 주는 비서입니다. 아래 JSON 은 지금까지의 거래 복기 숫자입니다. 이 숫자만 근거로, 초보자가 이해하기 쉬운 한국어 존댓말로 3~4문장 설명하세요.\n"
    "규칙: 1) JSON 에 없는 숫자를 만들지 마세요. 2) 앞으로의 가격 예측이나 사고팔라는 조언은 하지 마세요. 3) 이 전략은 '작게 잃고 가끔 크게 버는' 방식이라는 점을 고려하세요. "
    "4) 좋았던 점 하나와 아쉬운 점 하나를 균형 있게 말하세요. 5) 제목, 목록, 따옴표 없이 문단 하나로만 쓰세요."
)


def add_comment(out):
    """Ollama 가 복기 숫자를 읽고 쉬운 설명을 씀 (숫자를 지어내면 버림)"""
    if not config.OLLAMA_REVIEW or not out["summary"].get("n"):
        return
    import llm
    src = {k: out[k] for k in ("summary", "shape", "best", "worst", "by_kind", "live_vs_bt") if out.get(k)}
    src["monthly_last3"] = (out.get("monthly") or [])[-3:]
    text = json.dumps(src, ensure_ascii=False)
    comment = llm.chat(COMMENT_SYSTEM, text, timeout=config.OLLAMA_POLISH_TIMEOUT * 2)
    if comment and llm.numbers_subset(text, comment) and 40 <= len(comment) <= 800:
        out["comment"] = {"text": comment, "model": config.OLLAMA_MODEL, "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def update():
    config.DATA_DIR.mkdir(exist_ok=True)
    out = build()
    old = _load("review", {}).get("comment")
    try:
        add_comment(out)
    except Exception as e:
        print("복기 해설 실패(무시):", str(e)[:60])
    if "comment" not in out and old:   # 이번에 못 썼으면 지난 해설을 유지
        out["comment"] = old
    with open(config.DATA_DIR / "review.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    o = update()
    s = o["summary"]
    print(f"청산 {s['n']}건 | 승률 {s['win_rate']}% | 평균 {s['avg_pct']}% | 평균 보유 {s['avg_days']}일 | 합계 {s['pnl']:,}원")
    for k, v in o["by_kind"].items():
        print(f"  {k}: {v['n']}건, 승률 {v['win_rate']}%, 평균 {v['avg_pct']}%")
    if o["live_vs_bt"]:
        l = o["live_vs_bt"]
        print(f"실운영 {l['live']}% vs 같은 기간 백테스트 {l['backtest']}% (차이 {l['diff']}%p)")
    print("data/review.json 에 저장했어요.")
