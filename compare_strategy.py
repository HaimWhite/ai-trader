"""전략 개선 옵션 조합을 비교합니다. 실행: python compare_strategy.py (몇 분 걸릴 수 있어요)
앞 구간(2021~2024)에서 비교하고, 뒤 구간(2025~)은 확인용으로만 봅니다."""
import itertools
import time

import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate

SPLIT = "2025-01-01"
START = 120
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT

SIGNALS = {"기본": (1, 0.0), "3일유지": (3, 0.0), "격차2%": (1, 0.02), "3일+2%": (3, 0.02)}
TRAILS = {"없음": None, "15%": 0.15}
STOPS = {"-7%": None, "넓게": config.WIDE_STOP_PCT}   # 넓게: 코스닥·나스닥만 손절선 완화
PULLBACKS = {"없음": None, "3%": 0.03}


def trade_stats(trades):
    if not trades:
        return 0, 0.0, 0.0, 0
    wins = [t["pnl_pct"] for t in trades if t["pnl"] > 0]
    losses = [-t["pnl_pct"] for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    ratio = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0.0
    avg = sum(t["pnl_pct"] for t in trades) / len(trades)
    return round(win_rate, 1), round(ratio, 2), round(avg, 2), len(trades)


def main():
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)

    rows, t0 = [], time.time()
    combos = list(itertools.product(SIGNALS, TRAILS, STOPS, PULLBACKS))
    for k, (sg, tr, st, pb) in enumerate(combos, 1):
        confirm, gap = SIGNALS[sg]
        curve, trades = simulate(len(idx), data, SHORT, LONG, STOP, None, confirm, gap, TRAILS[tr], STOPS[st], PULLBACKS[pb])
        a = metrics(curve[START:split_i], idx[START:split_i])
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        win, ratio, avg, n_tr = trade_stats([t for t in trades if t["i"] < split_i])
        rows.append({
            "label": f"신호:{sg} 추적:{tr} 손절:{st} 눌림:{pb}",
            "is_win": win, "is_ratio": ratio, "is_avg": avg, "is_trades": n_tr,
            "is_cagr": a["cagr"], "is_mdd": a["mdd"],
            "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"],
        })
        print(f"\r진행 {k}/{len(combos)} ({time.time() - t0:.0f}초)", end="", flush=True)
    print()

    rows.sort(key=lambda r: r["is_cal"], reverse=True)
    ba = metrics(bench[:split_i - START], idx[START:split_i])
    print()
    print(f"[설정 비교 구간] {idx[START].date()} ~ {idx[split_i - 1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("승률=이긴 거래 비율 / 손익비=평균 이익÷평균 손실 / 평균=거래당 평균 손익(%) / CAL=연수익률÷|최대낙폭| (높을수록 좋음)")
    print("IS=설정 비교 구간 / OOS=확인 구간")
    print()
    print(f"{'설정':<44}{'승률':>6}{'손익비':>7}{'평균%':>7}{'거래':>5}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}")
    for r in rows:
        print(f"{r['label']:<{44 - sum(1 for ch in r['label'] if ord(ch) > 127)}}{r['is_win']:>6}{r['is_ratio']:>7}{r['is_avg']:>7}{r['is_trades']:>5}"
              f"{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}{r['oos_cagr']:>8}{r['oos_mdd']:>8}")
    print(f"\n참고: 단순 보유(설정 비교 구간) 연 {ba['cagr']}% / 최대낙폭 {ba['mdd']}%")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_strategy.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_strategy.csv 에도 저장했습니다.")


if __name__ == "__main__":
    main()
