"""'오를 때는 덜 먹고, 내릴 때는 더 잃는' 문제를 확인하고 개선안을 비교합니다. 실행: python compare_exit.py
상승 포착 = 시장(3종목 이상 동일비중 보유)이 오른 달에 전략이 얼마나 따라갔는지 (높을수록 좋음)
하락 포착 = 시장이 내린 달에 전략이 얼마나 같이 내렸는지 (낮을수록 좋음)"""
import itertools

import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate

SPLIT = "2025-01-01"
START = 120
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT
FAST_EXITS = {"기본": None, "단기선1일": 1, "단기선2일": 2, "단기선3일": 3}
TRAILS = {"없음": None, "10%": 0.10, "15%": 0.15, "20%": 0.20}


def capture(strategy, bench, dates):
    s = pd.Series(strategy, index=dates)
    b = pd.Series(bench, index=dates)
    sm = s.groupby(s.index.to_period("M")).last().pct_change().dropna()
    bm = b.groupby(b.index.to_period("M")).last().pct_change().dropna()
    up, down = bm > 0, bm < 0
    up_cap = sm[up].mean() / bm[up].mean() * 100 if up.any() else 0
    down_cap = sm[down].mean() / bm[down].mean() * 100 if down.any() else 0
    return round(up_cap), round(down_cap)


def main():
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)
    dates_is = idx[START:split_i]

    rows = []
    for (fe_name, fe), (tr_name, tr) in itertools.product(FAST_EXITS.items(), TRAILS.items()):
        curve, trades = simulate(len(idx), data, SHORT, LONG, STOP, trail=tr, fast_exit=fe)
        a = metrics(curve[START:split_i], dates_is)
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        up_cap, down_cap = capture(curve[START:split_i], bench[:split_i - START], dates_is)
        tis = [t for t in trades if t["i"] < split_i]
        win = round(len([t for t in tis if t["pnl"] > 0]) / len(tis) * 100, 1) if tis else 0
        rows.append({
            "label": f"청산:{fe_name} 추적:{tr_name}", "up": up_cap, "down": down_cap, "spread": up_cap - down_cap,
            "win": win, "trades": len(tis), "is_cagr": a["cagr"], "is_mdd": a["mdd"],
            "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"],
        })

    rows.sort(key=lambda r: r["spread"], reverse=True)
    print()
    print(f"[설정 비교 구간] {dates_is[0].date()} ~ {dates_is[-1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("상승=상승 포착률(%, 높을수록 좋음) / 하락=하락 포착률(%, 낮을수록 좋음) / 차이=상승-하락 / CAL=연수익률÷|최대낙폭|")
    print("청산: 기본=장기선 아래로 내려갈 때 매도 / 단기선N일=종가가 단기선 아래로 N일 연속이면 빨리 매도")
    print()
    print(f"{'설정':<30}{'상승':>5}{'하락':>5}{'차이':>5}{'승률':>6}{'거래':>5}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}")
    for r in rows:
        pad = 30 - sum(1 for ch in r["label"] if ord(ch) > 127)
        print(f"{r['label']:<{pad}}{r['up']:>5}{r['down']:>5}{r['spread']:>5}{r['win']:>6}{r['trades']:>5}"
              f"{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}{r['oos_cagr']:>8}{r['oos_mdd']:>8}")
    print("\n지금 전략은 '청산:기본 추적:없음' 줄입니다.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_exit.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
