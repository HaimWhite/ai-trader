"""과거 데이터로 전략을 검증합니다. 실행: python backtest.py"""
import json
from datetime import datetime

import FinanceDataReader as fdr
import pandas as pd

import config


def load_data():
    frames = {}
    for code, name in config.SYMBOLS.items():
        df = fdr.DataReader(code, config.BACKTEST_START).dropna(subset=["Close"])
        frames[code] = df
        print(f"[{name}] {len(df)}일치 데이터")
    return frames


def prepare(frames):
    idx = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in frames.values()])))
    data = {}
    for code, df in frames.items():
        d = df.reindex(idx)
        d["Close"] = d["Close"].ffill()
        d["Open"] = d["Open"].where(d["Open"] > 0).fillna(d["Close"])
        d["ma_s"] = d["Close"].rolling(config.SHORT_MA).mean()
        d["ma_l"] = d["Close"].rolling(config.LONG_MA).mean()
        data[code] = d
    return idx, data


def simulate(idx, data):
    n = len(data)
    cash = float(config.INITIAL_CASH)
    pos = {}        # code -> {qty, avg, cost}
    pending = {}    # code -> ("BUY"/"SELL", 사유)
    blocked = set() # 손절 후 재진입 대기
    curve, trades = [], []

    for i, d in enumerate(idx):
        # 1) 전날 신호를 오늘 시가에 체결 (미래 정보를 쓰지 않기 위해)
        if pending:
            for code, (side, why) in list(pending.items()):
                if side != "SELL" or code not in pos:
                    continue
                op = data[code].at[d, "Open"]
                if pd.isna(op):
                    continue
                price = op * (1 - config.SLIPPAGE_RATE)
                amount = price * pos[code]["qty"]
                proceeds = amount - amount * config.FEE_RATE - amount * config.SELL_TAX_RATE
                pnl = proceeds - pos[code]["cost"]
                trades.append({"code": code, "pnl": pnl, "pnl_pct": pnl / pos[code]["cost"] * 100, "why": why})
                cash += proceeds
                del pos[code]
                del pending[code]

            buys = [c for c, (s, _) in pending.items() if s == "BUY" and c not in pos]
            if buys:
                eq_open = cash + sum(p["qty"] * data[c].at[d, "Open"] for c, p in pos.items())
                budget = eq_open / n
                for code in buys:
                    op = data[code].at[d, "Open"]
                    if pd.isna(op):
                        continue
                    price = op * (1 + config.SLIPPAGE_RATE)
                    qty = int(min(budget, cash) // (price * (1 + config.FEE_RATE)))
                    if qty > 0:
                        amount = price * qty
                        cost = amount + amount * config.FEE_RATE
                        cash -= cost
                        pos[code] = {"qty": qty, "avg": price, "cost": cost}
                    del pending[code]

        # 2) 종가 기준 평가
        equity = cash + sum(p["qty"] * data[c].at[d, "Close"] for c, p in pos.items())
        curve.append(equity)

        # 3) 종가 기준으로 내일 주문할 신호 판단
        for code in data:
            row = data[code].iloc[i]
            if pd.isna(row["ma_l"]) or pd.isna(row["Close"]):
                continue
            bullish = row["ma_s"] > row["ma_l"]
            if not bullish:
                blocked.discard(code)
            if code in pos:
                if row["Close"] / pos[code]["avg"] - 1 <= config.STOP_LOSS_PCT:
                    pending[code] = ("SELL", "손절")
                    blocked.add(code)
                elif not bullish:
                    pending[code] = ("SELL", "하락 추세")
                else:
                    pending.pop(code, None)
            else:
                if bullish and code not in blocked:
                    pending[code] = ("BUY", "상승 추세")
                else:
                    pending.pop(code, None)
    return curve, trades


def metrics(values, dates):
    s = pd.Series(values, index=dates)
    years = (dates[-1] - dates[0]).days / 365.25
    total = s.iloc[-1] / s.iloc[0] - 1
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    mdd = (s / s.cummax() - 1).min()
    return {
        "final": round(float(s.iloc[-1])),
        "total_return": round(total * 100, 2),
        "cagr": round(cagr * 100, 2),
        "mdd": round(float(mdd) * 100, 2),
    }


def main():
    frames = load_data()
    idx, data = prepare(frames)
    start = config.LONG_MA          # 이동평균이 계산되기 시작하는 시점부터 비교
    curve, trades = simulate(idx, data)

    dates = idx[start:]
    strat = curve[start:]
    first_close = {c: data[c]["Close"].iloc[start] for c in data}
    bench = [
        config.INITIAL_CASH * sum(data[c]["Close"].iloc[i] / first_close[c] for c in data) / len(data)
        for i in range(start, len(idx))
    ]

    wins = [t for t in trades if t["pnl"] > 0]
    by_symbol = {}
    for code, name in config.SYMBOLS.items():
        ts = [t for t in trades if t["code"] == code]
        by_symbol[name] = {
            "trades": len(ts),
            "win_rate": round(len([t for t in ts if t["pnl"] > 0]) / len(ts) * 100, 1) if ts else 0,
            "pnl": round(sum(t["pnl"] for t in ts)),
        }

    step = 5
    keep = list(range(0, len(dates), step))
    if keep[-1] != len(dates) - 1:
        keep.append(len(dates) - 1)

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "period": [dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")],
        "strategy": metrics(strat, dates),
        "benchmark": metrics(bench, dates),
        "trade_count": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "avg_trade_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 2) if trades else 0,
        "by_symbol": by_symbol,
        "curve": [
            {"date": dates[i].strftime("%Y-%m-%d"), "strategy": round(strat[i]), "benchmark": round(bench[i])}
            for i in keep
        ],
    }
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(config.DATA_DIR / "backtest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print()
    print(f"기간: {out['period'][0]} ~ {out['period'][1]}")
    print(f"전략      : 총 {out['strategy']['total_return']}% | 연 {out['strategy']['cagr']}% | 최대낙폭 {out['strategy']['mdd']}%")
    print(f"단순 보유 : 총 {out['benchmark']['total_return']}% | 연 {out['benchmark']['cagr']}% | 최대낙폭 {out['benchmark']['mdd']}%")
    print(f"거래 {out['trade_count']}회 | 승률 {out['win_rate']}% | 평균 손익 {out['avg_trade_pct']}%")


if __name__ == "__main__":
    main()
