"""갭 하락(밤사이 큰 하락) 대응을 비교합니다. 실행: python compare_gap.py
- 갭이 잦은 종목: 최근 120일 안에 '전날 종가 대비 시가가 7%(또는 10%) 이상 벌어진 날'이 2~3번 이상인 종목
  건너뜀 = 그 종목은 새로 사지 않음 / 절반 = 평소의 절반만 삼
- 고변동 절반: 코스닥·나스닥 종목은 평소의 절반만 삼"""
import itertools

import numpy as np
import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate
from compare_exit import capture

SPLIT = "2025-01-01"
START = 120
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT
GAPS = [(None, 0.07, 2), ("skip", 0.07, 2), ("skip", 0.07, 3), ("skip", 0.10, 2),
        ("half", 0.07, 2), ("half", 0.07, 3), ("half", 0.10, 2)]
CLASS = {"100%": None, "50%": 0.5}


def gap_label(mode, thr, days):
    if mode is None:
        return "갭:끔"
    return f"갭:{'건너뜀' if mode == 'skip' else '절반'} {thr * 100:.0f}%x{days}"


def main():
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    n_days = len(idx)
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)
    dates_is = idx[START:split_i]

    print("\n[갭이 잦은 종목 순위] 전날 종가 대비 시가가 7% 이상 벌어진 날 (전체 기간)")
    years = n_days / 252
    counts = []
    for code, dd in data.items():
        o, c = dd["open"], dd["close"]
        counts.append((int((np.abs(o[1:] / c[:-1] - 1) >= 0.07).sum()), code))
    for cnt, code in sorted(counts, reverse=True)[:10]:
        print(f"  {config.SYMBOLS.get(code, code):<12} {cnt:>3}번  (연 {cnt / years:.1f}번)")

    rows = []
    for (mode, thr, days), (cn, cs) in itertools.product(GAPS, CLASS.items()):
        curve, trades = simulate(len(idx), data, SHORT, LONG, STOP, trail=config.TRAIL_STOP_PCT,
                                 class_scale=cs, gap_mode=mode, gap_thr=thr, gap_days=days)
        a = metrics(curve[START:split_i], dates_is)
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        _, down_cap = capture(curve[START:split_i], bench[:split_i - START], dates_is)
        tis = [t for t in trades if t["i"] < split_i]
        stops = [t["pnl_pct"] for t in tis if t["why"] == "손절"]
        rows.append({
            "label": f"{gap_label(mode, thr, days)} 고변동:{cn}", "down": down_cap,
            "stop_avg": round(sum(stops) / len(stops), 2) if stops else 0,
            "worst": round(min((t["pnl_pct"] for t in tis), default=0), 2), "trades": len(tis),
            "is_cagr": a["cagr"], "is_mdd": a["mdd"],
            "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"],
        })

    rows.sort(key=lambda r: r["is_cal"], reverse=True)
    print()
    print(f"[설정 비교 구간] {dates_is[0].date()} ~ {dates_is[-1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("하락=하락 포착률(%) / 손절평균=손절 거래의 평균 손익%(-7%에 가까울수록 갭 피해가 적음) / 최악=가장 크게 잃은 거래% / CAL=연수익률÷|최대낙폭|")
    print()
    print(f"{'설정':<34}{'하락':>5}{'손절평균':>8}{'최악':>8}{'거래':>5}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}")
    for r in rows:
        pad = 34 - sum(1 for ch in r["label"] if ord(ch) > 127)
        print(f"{r['label']:<{pad}}{r['down']:>5}{r['stop_avg']:>8}{r['worst']:>8}{r['trades']:>5}"
              f"{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}{r['oos_cagr']:>8}{r['oos_mdd']:>8}")
    print("\n지금 설정은 '갭:끔 고변동:100%' 줄입니다.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_gap.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
