"""변동성 크기 조절 값을 촘촘히 비교합니다. 실행: python compare_vol.py
크기조절 X% = 종목당 예상 손실이 총자산의 X% 안팎이 되도록 투자 금액을 줄임 (출렁이는 종목은 적게)
바닥 5% = 지금 방식(예상 손실을 최소 5%로 계산, 사실상 모든 종목을 비슷하게 줄임)
바닥 2.5% = 종목별 변동성 차이를 더 크게 반영 (조용한 종목은 많이, 출렁이는 종목은 적게)"""
import itertools

import pandas as pd

import config
from backtest import benchmark_curve, load_data, metrics, prepare, simulate
from compare_exit import capture

SPLIT = "2025-01-01"
START = 120
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT
RISKS = [None, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.010]
FLOORS = {"5%": 0.05, "2.5%": 0.025}


def main():
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)
    dates_is = idx[START:split_i]

    rows, base_trades = [], None
    for risk, (fn, fv) in itertools.product(RISKS, FLOORS.items()):
        if risk is None and fn != "5%":
            continue
        curve, trades = simulate(len(idx), data, SHORT, LONG, STOP, trail=config.TRAIL_STOP_PCT, vol_size=risk, vol_floor=fv)
        if risk is None:
            base_trades = trades
        a = metrics(curve[START:split_i], dates_is)
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        _, down_cap = capture(curve[START:split_i], bench[:split_i - START], dates_is)
        tis = [t for t in trades if t["i"] < split_i]
        losses = [t["pnl_pct"] for t in tis if t["pnl"] <= 0]
        rows.append({
            "label": "크기조절:끔" if risk is None else f"크기조절:{risk * 100:.1f}% 바닥:{fn}",
            "down": down_cap,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "worst": round(min((t["pnl_pct"] for t in tis), default=0), 2),
            "is_cagr": a["cagr"], "is_mdd": a["mdd"],
            "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"],
        })

    print()
    print(f"[설정 비교 구간] {dates_is[0].date()} ~ {dates_is[-1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("(크기조절 값 순서대로 표시) 하락=하락 포착률(%) / 최악=가장 크게 잃은 거래% / CAL=연수익률÷|최대낙폭|")
    print()
    print(f"{'설정':<32}{'하락':>5}{'평균손실':>8}{'최악':>8}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}")
    for r in rows:
        pad = 32 - sum(1 for ch in r["label"] if ord(ch) > 127)
        print(f"{r['label']:<{pad}}{r['down']:>5}{r['avg_loss']:>8}{r['worst']:>8}{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}{r['oos_cagr']:>8}{r['oos_mdd']:>8}")

    print("\n[지금 설정에서 가장 크게 잃은 거래 5건 - 원인 확인용]")
    worst = sorted(base_trades, key=lambda t: t["pnl_pct"])[:5]
    for t in worst:
        print(f"  {idx[t['i']].date()}  {config.SYMBOLS.get(t['code'], t['code']):<10} {t['why']:<8} {t['pnl_pct']:+.1f}%")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_vol.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
