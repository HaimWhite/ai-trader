"""과거 데이터로 전략을 검증합니다. 실행: python backtest.py"""
import json
from datetime import datetime

import market
import numpy as np
import pandas as pd

import config


def load_data():
    frames = {}
    for code, name in config.SYMBOLS.items():
        df = market.load_prices(code, config.BACKTEST_START)
        frames[code] = df
        print(f"[{name}] {len(df)}일치 데이터")
    return frames


def prepare(frames, ma_list):
    """날짜 목록과 종목별 numpy 배열(시가, 종가, 이동평균들)을 만듭니다."""
    idx = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in frames.values()])))
    data = {}
    for code, df in frames.items():
        d = df.reindex(idx)
        close = d["Close"].ffill()
        op = d["Open"].where(d["Open"] > 0).fillna(close)
        data[code] = {
            "open": op.to_numpy(dtype=float),
            "close": close.to_numpy(dtype=float),
            "ma": {n: close.rolling(n).mean().to_numpy(dtype=float) for n in ma_list},
        }
    return idx, data


def simulate(n_days, data, short, long_, stop, filter_n=None, confirm=1, gap=0.0, trail=None, wide_stop=None, pullback=None, fast_exit=None):
    """stop: 손절 비율(예 -0.07), 없으면 None / filter_n: 종가가 이 기간 이동평균 위일 때만 매수
    confirm: 상승 신호가 N일 연속 유지돼야 매수 / gap: 단기선이 장기선보다 이 비율 이상 높아야 매수
    trail: 최고가 대비 이 비율만큼 내려오면 매도(추적 손절) / wide_stop: 변동성 큰 종목(config.WIDE_STOP_CODES)의 손절선
    pullback: 단기선보다 이 비율 이상 눌렸을 때만 매수"""
    n = len(data)
    cash = float(config.INITIAL_CASH)
    pos = {}         # code -> {qty, avg, cost}
    pending = {}     # code -> ("BUY"/"SELL", 사유)
    blocked = set()  # 손절 후 재진입 대기
    streak = {}      # 종목별 상승 신호 연속 일수
    below = {}       # 종가가 단기선 아래인 연속 일수
    curve, trades = [], []

    for i in range(n_days):
        # 1) 전날 신호를 오늘 시가에 체결 (미래 정보를 쓰지 않기 위해)
        if pending:
            for code, (side, why) in list(pending.items()):
                if side != "SELL" or code not in pos:
                    continue
                op = data[code]["open"][i]
                if np.isnan(op):
                    continue
                price = op * (1 - config.SLIPPAGE_RATE)
                amount = price * pos[code]["qty"]
                proceeds = amount - amount * config.fee_rate(code) - amount * config.sell_tax_rate(code)
                pnl = proceeds - pos[code]["cost"]
                trades.append({"code": code, "pnl": pnl, "pnl_pct": pnl / pos[code]["cost"] * 100, "why": why, "i": i})
                cash += proceeds
                del pos[code]
                del pending[code]

            buys = [c for c, (s, _) in pending.items() if s == "BUY" and c not in pos]
            if buys:
                eq_open = cash + sum(p["qty"] * data[c]["open"][i] for c, p in pos.items())
                budget = eq_open / min(n, config.MAX_POSITIONS)
                for code in buys:
                    if len(pos) >= config.MAX_POSITIONS:
                        del pending[code]
                        continue
                    op = data[code]["open"][i]
                    if np.isnan(op):
                        continue
                    price = op * (1 + config.SLIPPAGE_RATE)
                    qty = int(min(budget, cash) // (price * (1 + config.fee_rate(code))))
                    if qty > 0:
                        amount = price * qty
                        cost = amount + amount * config.fee_rate(code)
                        cash -= cost
                        pos[code] = {"qty": qty, "avg": price, "cost": cost}
                    del pending[code]

        # 2) 종가 기준 평가
        curve.append(cash + sum(p["qty"] * data[c]["close"][i] for c, p in pos.items()))

        # 3) 종가 기준으로 내일 주문할 신호 판단
        for code, dd in data.items():
            c = dd["close"][i]
            ms = dd["ma"][short][i]
            ml = dd["ma"][long_][i]
            if np.isnan(ml) or np.isnan(c):
                continue
            bullish = ms > ml
            streak[code] = streak.get(code, 0) + 1 if bullish else 0
            below[code] = below.get(code, 0) + 1 if c < ms else 0
            entry_ok = True
            if confirm > 1 and streak[code] < confirm:
                entry_ok = False
            if gap and not ms > ml * (1 + gap):
                entry_ok = False
            if pullback and not c <= ms * (1 - pullback):
                entry_ok = False
            if fast_exit and not c > ms:   # 빠른 청산을 쓰면, 가격이 단기선 위로 돌아온 뒤에만 재진입
                entry_ok = False
            if filter_n:
                mf = dd["ma"][filter_n][i]
                entry_ok = entry_ok and (not np.isnan(mf)) and c > mf
            if not bullish:
                blocked.discard(code)
            if code in pos:
                pos[code]["peak"] = max(pos[code].get("peak", pos[code]["avg"]), c)
                code_stop = wide_stop if (wide_stop is not None and code in config.WIDE_STOP_CODES) else stop
                if code_stop is not None and c / pos[code]["avg"] - 1 <= code_stop:
                    pending[code] = ("SELL", "손절")
                    blocked.add(code)
                elif trail is not None and c <= pos[code]["peak"] * (1 - trail):
                    pending[code] = ("SELL", "추적손절")
                    blocked.add(code)
                elif fast_exit and below[code] >= fast_exit:
                    pending[code] = ("SELL", "단기 이탈")
                elif not bullish:
                    pending[code] = ("SELL", "하락 추세")
                else:
                    pending.pop(code, None)
            else:
                if bullish and entry_ok and code not in blocked:
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


def benchmark_curve(data, start):
    """3종목을 같은 비중으로 사서 계속 들고 있을 때의 자산 곡선"""
    n_days = len(next(iter(data.values()))["close"])
    return [
        config.INITIAL_CASH * sum(dd["close"][i] / dd["close"][start] for dd in data.values()) / len(data)
        for i in range(start, n_days)
    ]


def main():
    frames = load_data()
    idx, data = prepare(frames, [config.SHORT_MA, config.LONG_MA])
    start = config.LONG_MA          # 이동평균이 계산되기 시작하는 시점부터 비교
    curve, trades = simulate(len(idx), data, config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT)

    dates = idx[start:]
    strat = curve[start:]
    bench = benchmark_curve(data, start)

    wins = [t for t in trades if t["pnl"] > 0]
    by_symbol = {}
    for code, name in config.SYMBOLS.items():
        ts = [t for t in trades if t["code"] == code]
        by_symbol[name] = {
            "trades": len(ts),
            "win_rate": round(len([t for t in ts if t["pnl"] > 0]) / len(ts) * 100, 1) if ts else 0,
            "pnl": round(sum(t["pnl"] for t in ts)),
        }

    keep = list(range(0, len(dates), 5))
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
