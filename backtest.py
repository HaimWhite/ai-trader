"""과거 데이터로 전략을 검증합니다. 실행: python backtest.py   (이전 설정과 비교: python backtest.py --vs-old)"""
import json
import sys
from datetime import datetime

import market
import status
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
            "mad": close.pct_change().abs().rolling(20).mean().to_numpy(dtype=float),
            "ma": {n: close.rolling(n).mean().to_numpy(dtype=float) for n in ma_list},
        }
    return idx, data


def simulate(n_days, data, short, long_, stop, filter_n=None, confirm=1, gap=0.0, trail=None, wide_stop=None, pullback=None, fast_exit=None, vol_size=None, breadth_min=None, vol_floor=0.05, class_scale=None, gap_mode=None, gap_thr=0.07, gap_days=2, sector_limit=None):
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
    rank = {}        # 종목별 추세 강도 (단기선/장기선)

    gapcnt = {}   # 최근 120일 중 갭(전날 종가 대비 시가가 gap_thr 이상 벌어진 날) 횟수
    if gap_mode:
        for code, dd in data.items():
            o, c = dd["open"], dd["close"]
            hit = np.zeros(n_days)
            hit[1:] = (np.abs(o[1:] / c[:-1] - 1) >= gap_thr).astype(float)
            cs = np.cumsum(hit)
            cnt = cs.copy()
            cnt[120:] = cs[120:] - cs[:-120]
            gapcnt[code] = cnt

    def _sector_full(code):   # 같은 업종을 이미 sector_limit 종목만큼 들고 있는지
        sec = config.SECTORS.get(code)
        return bool(sector_limit and sec and sum(1 for c in pos if config.SECTORS.get(c) == sec) >= sector_limit)

    def _bud(code, i, budget, eq_open):   # 변동성이 크거나 갭이 잦은 종목은 투자 금액을 줄임
        if vol_size and i > 0:
            m = data[code]["mad"][i - 1]
            if not np.isnan(m):
                budget = min(budget, eq_open * vol_size / min(0.20, max(vol_floor, 3 * m)))
        if class_scale and code in config.WIDE_STOP_CODES:
            budget *= class_scale
        if gap_mode == "half" and i > 0 and gapcnt[code][i - 1] >= gap_days:
            budget *= 0.5
        return budget
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
            buys.sort(key=lambda c: -rank.get(c, 0))
            if buys:
                eq_open = cash + sum(p["qty"] * data[c]["open"][i] for c, p in pos.items())
                budget = eq_open / min(n, config.MAX_POSITIONS)
                for code in buys:
                    if len(pos) >= config.MAX_POSITIONS or _sector_full(code):
                        del pending[code]
                        continue
                    op = data[code]["open"][i]
                    if np.isnan(op):
                        continue
                    price = op * (1 + config.SLIPPAGE_RATE)
                    qty = int(min(_bud(code, i, budget, eq_open), cash) // (price * (1 + config.fee_rate(code))))
                    if qty > 0:
                        amount = price * qty
                        cost = amount + amount * config.fee_rate(code)
                        cash -= cost
                        pos[code] = {"qty": qty, "avg": price, "cost": cost}
                    del pending[code]

        # 2) 종가 기준 평가
        curve.append(cash + sum(p["qty"] * data[c]["close"][i] for c, p in pos.items()))

        # 3) 종가 기준으로 내일 주문할 신호 판단
        breadth = 1.0
        if breadth_min:   # 상승 추세 종목 비율 (시장 전체 분위기)
            valid = bull = 0
            for dd in data.values():
                ml_ = dd["ma"][long_][i]
                if not np.isnan(ml_):
                    valid += 1
                    bull += dd["ma"][short][i] > ml_
            breadth = bull / valid if valid else 1.0
        for code, dd in data.items():
            c = dd["close"][i]
            ms = dd["ma"][short][i]
            ml = dd["ma"][long_][i]
            if np.isnan(ml) or np.isnan(c):
                continue
            bullish = ms > ml
            rank[code] = ms / ml
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
            if breadth_min and breadth < breadth_min:
                entry_ok = False
            if gap_mode == "skip" and gapcnt[code][i] >= gap_days:
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


def live_options():
    """지금 실제 매매에 쓰는 설정을 백테스트에도 그대로 적용"""
    return dict(trail=config.TRAIL_STOP_PCT, vol_size=config.VOL_SIZE_RISK, vol_floor=config.VOL_FLOOR,
                class_scale=config.HIGHVOL_SCALE, gap_mode=config.GAP_MODE, gap_thr=config.GAP_THR,
                gap_days=config.GAP_DAYS, breadth_min=config.BREADTH_MIN, sector_limit=config.MAX_PER_SECTOR)


def settings_text():
    parts = [f"{config.SHORT_MA}일/{config.LONG_MA}일 이동평균", f"손절 {config.STOP_LOSS_PCT * 100:.0f}%"]
    if config.TRAIL_STOP_PCT:
        parts.append(f"추적 손절 {config.TRAIL_STOP_PCT * 100:.0f}%")
    if config.GAP_MODE:
        parts.append(f"갭 잦은 종목 {'건너뜀' if config.GAP_MODE == 'skip' else '절반'}({config.GAP_THR * 100:.0f}%x{config.GAP_DAYS}회)")
    if config.VOL_SIZE_RISK:
        parts.append(f"변동성 크기 조절 {config.VOL_SIZE_RISK * 100:.1f}%")
    if config.HIGHVOL_SCALE:
        parts.append(f"코스닥·나스닥 {config.HIGHVOL_SCALE * 100:.0f}%만 투자")
    if config.BREADTH_MIN:
        parts.append(f"약세장 필터({config.BREADTH_MIN * 100:.0f}%)")
    if config.MAX_PER_SECTOR:
        parts.append(f"같은 업종 최대 {config.MAX_PER_SECTOR}종목")
    parts.append(f"동시 보유 {config.MAX_POSITIONS}종목")
    return " · ".join(parts)


def yearly_returns(dates, series):
    """연도별 수익률(%). 첫 해는 백테스트 시작일부터, 마지막 해는 오늘까지의 수익률입니다."""
    df = pd.DataFrame(series, index=dates)
    last = df.groupby(df.index.year).last()
    prev, out = df.iloc[0], []
    for year, row in last.iterrows():
        out.append({"year": int(year), **{k: round((row[k] / prev[k] - 1) * 100, 1) for k in df.columns}})
        prev = row
    return out


def main():
    frames = load_data()
    idx, data = prepare(frames, [config.SHORT_MA, config.LONG_MA])
    start = config.LONG_MA          # 이동평균이 계산되기 시작하는 시점부터 비교
    curve, trades = simulate(len(idx), data, config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT, **live_options())
    # --vs-old: 추적 손절·갭 필터 없이 손절 -7%만 쓴 경우와 나란히 비교 (시간이 더 걸려서 옵션으로만 제공)
    vs_old = "--vs-old" in sys.argv
    prev_curve = simulate(len(idx), data, config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT)[0] if vs_old else None

    dates = idx[start:]
    strat = curve[start:]
    bench = benchmark_curve(data, start)

    # 코스피·나스닥 지수와 비교 (나스닥은 달러 기준 지수 그대로)
    idx_curves = {}
    for key, sym, yf_sym in (("kospi", "KS11", "^KS11"), ("nasdaq", "IXIC", "^IXIC")):
        try:
            ser = market._fetch(sym, yf_sym, config.BACKTEST_START)["Close"].dropna().reindex(idx, method="ffill").bfill().to_numpy(dtype=float)
            idx_curves[key] = [config.INITIAL_CASH * ser[i] / ser[start] for i in range(start, len(idx))]
        except Exception as e:
            print(f"[지수 비교] {sym} 조회 실패(건너뜀): {str(e)[:60]}")

    wins = [t for t in trades if t["pnl"] > 0]
    by_symbol = {}
    for code, name in config.SYMBOLS.items():
        ts = [t for t in trades if t["code"] == code]
        by_symbol[name] = {
            "trades": len(ts),
            "win_rate": round(len([t for t in ts if t["pnl"] > 0]) / len(ts) * 100, 1) if ts else 0,
            "pnl": round(sum(t["pnl"] for t in ts)),
        }

    series = {"strategy": strat, "benchmark": bench, **idx_curves}
    if vs_old:
        series["previous"] = prev_curve[start:]
    curve_rows = []
    for i in range(len(dates)):
        row = {"date": dates[i].strftime("%Y-%m-%d"), "strategy": round(strat[i]), "benchmark": round(bench[i])}
        if vs_old:
            row["previous"] = round(prev_curve[start + i])
        row.update({k: round(v[i]) for k, v in idx_curves.items()})
        curve_rows.append(row)

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "period": [dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")],
        "strategy": metrics(strat, dates),
        "benchmark": metrics(bench, dates),
        "settings": settings_text(),
        "yearly": yearly_returns(dates, series),
        "trades": [
            {"date": idx[t["i"]].strftime("%Y-%m-%d"), "name": config.SYMBOLS.get(t["code"], t["code"]),
             "pnl": round(t["pnl"]), "pct": round(t["pnl_pct"], 2), "why": t["why"]}
            for t in trades
        ],
        "trade_count": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "avg_trade_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 2) if trades else 0,
        "by_symbol": by_symbol,
        "curve": curve_rows,
    }
    if vs_old:
        out["previous"] = metrics(prev_curve[start:], dates)
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(config.DATA_DIR / "backtest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print()
    print(f"기간: {out['period'][0]} ~ {out['period'][1]}")
    print(f"적용 설정: {out['settings']}")
    rows = [("현재 설정  ", out["strategy"])] + ([("이전 설정  ", out["previous"])] if vs_old else []) + [("단순 보유  ", out["benchmark"])]
    for name, m_ in rows:
        print(f"{name}: 총 {m_['total_return']}% | 연 {m_['cagr']}% | 최대낙폭 {m_['mdd']}%")
    if vs_old:
        print("(이전 설정 = 추적 손절·갭 필터 없이 손절 -7%만 쓴 경우)")
    print(f"현재 설정 거래 {out['trade_count']}회 | 승률 {out['win_rate']}% | 평균 손익 {out['avg_trade_pct']}%")

    if vs_old:   # 기간별 연환산 수익률 차이 (현재 설정 - 이전 설정)
        split_i = int(idx.searchsorted(pd.Timestamp("2025-01-01")))
        print()
        print("[연환산 수익률 차이]  (현재 설정 - 이전 설정, %p)")
        print(f"{'기간':<14}{'현재 연%':>10}{'이전 연%':>10}{'차이':>8}{'현재 낙폭':>10}{'이전 낙폭':>10}")
        for label, (a_, b_) in (("전체", (start, len(idx))), ("2025년 이전", (start, split_i)), ("2025년 이후", (split_i - 1, len(idx)))):
            cur, prv = metrics(curve[a_:b_], idx[a_:b_]), metrics(prev_curve[a_:b_], idx[a_:b_])
            pad = 14 - sum(1 for ch in label if ord(ch) > 127)
            print(f"{label:<{pad}}{cur['cagr']:>10}{prv['cagr']:>10}{cur['cagr'] - prv['cagr']:>+8.1f}{cur['mdd']:>10}{prv['mdd']:>10}")
    print("\n[연도별 수익률 %]  (첫 해는 시작일부터, 마지막 해는 오늘까지)")
    print(f"{'연도':<6}{'전략':>8}{'단순보유':>9}{'코스피':>8}{'나스닥':>8}")
    for y in out["yearly"]:
        print(f"{y['year']:<6}{y['strategy']:>8}{y['benchmark']:>9}{y.get('kospi', '-'):>8}{y.get('nasdaq', '-'):>8}")
    status.beat("backtest", True, out["settings"][:80])

if __name__ == "__main__":
    main()
