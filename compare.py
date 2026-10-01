"""설정값 조합을 비교합니다. 실행: python compare.py
앞 구간(2021~2024)에서 설정을 비교하고, 뒤 구간(2025~)은 확인용으로만 봅니다."""
import itertools

import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate

SPLIT = "2025-01-01"
MA_PAIRS = [(5, 20), (10, 60), (20, 120)]
STOPS = [-0.07, -0.15, None]
FILTER_MA = 120
FILTERS = [None, FILTER_MA]
START = 120   # 모든 조합을 같은 날짜부터 비교


def label(pair, stop, flt):
    s = "SL" + (f"{int(stop * 100)}%" if stop is not None else "none")
    return f"MA{pair[0]}/{pair[1]} {s:<7} {'FILT120' if flt else 'nofilt '}"


def main():
    frames = load_data()
    ma_list = sorted({n for p in MA_PAIRS for n in p} | {FILTER_MA})
    idx, data = prepare(frames, ma_list)
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))

    def cut(curve):
        a = metrics(curve[START:split_i], idx[START:split_i])        # 설정 비교 구간
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])           # 확인 구간
        return a, b

    rows = []
    for pair, stop, flt in itertools.product(MA_PAIRS, STOPS, FILTERS):
        curve, trades = simulate(len(idx), data, pair[0], pair[1], stop, flt)
        a, b = cut(curve)
        calmar = a["cagr"] / abs(a["mdd"]) if a["mdd"] else 0
        rows.append({
            "label": label(pair, stop, flt),
            "is_cagr": a["cagr"], "is_mdd": a["mdd"], "is_calmar": round(calmar, 2),
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"], "trades": len(trades),
        })

    bench = benchmark_curve(data, START)
    bench_full = [None] * START + bench
    ba = metrics(bench[:split_i - START], idx[START:split_i])
    bb = metrics(bench_full[split_i - 1:], idx[split_i - 1:])

    rows.sort(key=lambda r: r["is_calmar"], reverse=True)
    print()
    print(f"[설정 비교 구간] {idx[START].date()} ~ {idx[split_i - 1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("IS = 설정 비교 구간 / OOS = 확인 구간 / CAGR = 연 수익률(%) / MDD = 최대 낙폭(%) / CAL = CAGR÷|MDD| (높을수록 좋음)")
    print("MA = 이동평균 기간 / SL = 손절선 / FILT120 = 120일선 위에서만 매수")
    print()
    print(f"{'설정':<28}{'IS CAGR':>9}{'IS MDD':>9}{'IS CAL':>8}{'OOS CAGR':>10}{'OOS MDD':>9}{'거래':>6}")
    for r in rows:
        print(f"{r['label']:<28}{r['is_cagr']:>9}{r['is_mdd']:>9}{r['is_calmar']:>8}{r['oos_cagr']:>10}{r['oos_mdd']:>9}{r['trades']:>6}")
    bc = ba["cagr"] / abs(ba["mdd"]) if ba["mdd"] else 0
    print(f"{'단순 보유(BUY&HOLD)':<28}{ba['cagr']:>9}{ba['mdd']:>9}{round(bc, 2):>8}{bb['cagr']:>10}{bb['mdd']:>9}{'-':>6}")

    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare.csv", index=False, encoding="utf-8-sig")
    print()
    print("결과는 data/compare.csv 에도 저장했습니다.")


if __name__ == "__main__":
    main()
