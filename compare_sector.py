"""같은 업종 쏠림 제한을 비교합니다. 실행: python compare_sector.py
업종당 최대 보유 종목 수를 1/2/3개로 제한했을 때와 제한 없을 때(현재)를 비교합니다."""
import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate
from compare_exit import capture

SPLIT = "2025-01-01"
START = 120
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT
LIMITS = {"제한 없음": None, "업종당 1개": 1, "업종당 2개": 2, "업종당 3개": 3}


def main():
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)
    dates_is = idx[START:split_i]
    rows = []
    for name, lim in LIMITS.items():
        curve, trades = simulate(len(idx), data, SHORT, LONG, STOP, trail=config.TRAIL_STOP_PCT, gap_mode=config.GAP_MODE,
                                 gap_thr=config.GAP_THR, gap_days=config.GAP_DAYS, sector_limit=lim)
        a = metrics(curve[START:split_i], dates_is)
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        _, down_cap = capture(curve[START:split_i], bench[:split_i - START], dates_is)
        tis = [t for t in trades if t["i"] < split_i]
        rows.append({
            "label": name, "down": down_cap, "trades": len(tis),
            "worst": round(min((t["pnl_pct"] for t in tis), default=0), 2),
            "is_cagr": a["cagr"], "is_mdd": a["mdd"], "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"],
        })
    print()
    print(f"[설정 비교 구간] {dates_is[0].date()} ~ {dates_is[-1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("하락=하락 포착률(%) / 최악=가장 크게 잃은 거래% / CAL=연수익률÷|최대낙폭|")
    print()
    print(f"{'설정':<14}{'하락':>5}{'거래':>5}{'최악':>8}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}")
    for r in rows:
        pad = 14 - sum(1 for ch in r["label"] if ord(ch) > 127)
        print(f"{r['label']:<{pad}}{r['down']:>5}{r['trades']:>5}{r['worst']:>8}{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}{r['oos_cagr']:>8}{r['oos_mdd']:>8}")
    print("\n지금 설정은 '제한 없음' 줄입니다.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_sector.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
