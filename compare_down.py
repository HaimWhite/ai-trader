"""하락할 때 덜 잃는 방법을 비교합니다. 실행: python compare_down.py
- 변동성 크기 조절: 출렁임이 큰 종목은 적게 산다 (한 번 손절당해도 총자산의 0.5~1.5% 안팎만 잃도록)
- 약세장 필터: 상승 추세 종목이 전체의 30~40%보다 적으면 새로 사지 않는다
기본 설정(손절 -7%, 추적 손절)은 지금 매매 설정과 같습니다."""
import itertools

import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate
from compare_exit import capture

SPLIT = "2025-01-01"
START = 120
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT
VOL = {"끔": None, "0.5%": 0.005, "1.0%": 0.01, "1.5%": 0.015}
BREADTH = {"끔": None, "30%": 0.30, "40%": 0.40}


def main():
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)
    dates_is = idx[START:split_i]

    rows = []
    for (vn, vs), (bn, bs) in itertools.product(VOL.items(), BREADTH.items()):
        curve, trades = simulate(len(idx), data, SHORT, LONG, STOP, trail=config.TRAIL_STOP_PCT, vol_size=vs, breadth_min=bs)
        a = metrics(curve[START:split_i], dates_is)
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        _, down_cap = capture(curve[START:split_i], bench[:split_i - START], dates_is)
        tis = [t for t in trades if t["i"] < split_i]
        losses = [t["pnl_pct"] for t in tis if t["pnl"] <= 0]
        rows.append({
            "label": f"크기조절:{vn} 약세장필터:{bn}", "down": down_cap,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "worst": round(min((t["pnl_pct"] for t in tis), default=0), 2),
            "win": round(len([t for t in tis if t["pnl"] > 0]) / len(tis) * 100, 1) if tis else 0,
            "is_cagr": a["cagr"], "is_mdd": a["mdd"],
            "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"],
        })

    rows.sort(key=lambda r: r["is_cal"], reverse=True)
    print()
    print(f"[설정 비교 구간] {dates_is[0].date()} ~ {dates_is[-1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("하락=하락 포착률(%, 낮을수록 덜 잃음) / 평균손실=손실 거래의 평균 손익% / 최악=가장 크게 잃은 거래% / CAL=연수익률÷|최대낙폭|")
    print()
    print(f"{'설정':<34}{'하락':>5}{'평균손실':>8}{'최악':>8}{'승률':>6}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}")
    for r in rows:
        pad = 34 - sum(1 for ch in r["label"] if ord(ch) > 127)
        print(f"{r['label']:<{pad}}{r['down']:>5}{r['avg_loss']:>8}{r['worst']:>8}{r['win']:>6}{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}{r['oos_cagr']:>8}{r['oos_mdd']:>8}")
    print("\n지금 설정은 '크기조절:끔 약세장필터:끔' 줄입니다.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_down.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
