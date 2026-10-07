"""장기 이동평균을 120일 하나만 쓰는 것과 60일·90일을 함께 쓰는 경우를 비교합니다. 실행: python compare_ma.py
- 단독: 20일선이 60일선(또는 90, 120일선) 위일 때 상승
- 모두 위: 60·90·120일선 모두 위에 있을 때만 상승 (신중, 신호가 늦고 적음)
- 과반: 3개 중 2개 이상 위 / 하나라도: 3개 중 하나라도 위 (빠르게 진입)
지금 실제 설정(손절·추적 손절·갭 필터 등)은 모두 똑같이 적용하고 이동평균 규칙만 바꿔서 비교해요.
더 긴 기간으로 확인: python compare_ma.py --start=2014-01-01 --split=2020-01-01   (--start=데이터 시작일, --split=설정 비교 구간과 확인 구간을 나누는 날)"""
import sys

import pandas as pd

import config
from backtest import benchmark_curve, load_data, live_options, metrics, prepare, simulate
from compare_exit import capture

SPLIT = "2025-01-01"
START = 120
SHORT, STOP = config.SHORT_MA, config.STOP_LOSS_PCT
CASES = [   # (이름, 장기선 목록, 규칙)
    ("20/60 단독", (60,), None), ("20/90 단독", (90,), None), ("20/120 단독 (지금)", (120,), None),
    ("60·90·120 모두 위", (60, 90, 120), "all"), ("60·90·120 과반 위", (60, 90, 120), "majority"),
    ("60·90·120 하나라도 위", (60, 90, 120), "any"),
    ("90·120 모두 위", (90, 120), "all"), ("60·120 모두 위", (60, 120), "all"),
]


def main():
    global SPLIT
    for a in sys.argv[1:]:
        if a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
        elif a.startswith("--split="):
            SPLIT = a.split("=", 1)[1]
    frames = load_data()
    idx, data = prepare(frames, sorted({SHORT, 60, 90, 120}))
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    bench = benchmark_curve(data, START)
    dates_is = idx[START:split_i]

    rows = []
    for name, longs, rule in CASES:
        opts = live_options()
        opts["longs"], opts["long_rule"] = (longs if len(longs) > 1 else None), (rule or "all")
        curve, trades = simulate(len(idx), data, SHORT, max(longs), STOP, **opts)
        a = metrics(curve[START:split_i], dates_is)
        b = metrics(curve[split_i - 1:], idx[split_i - 1:])
        _, down_cap = capture(curve[START:split_i], bench[:split_i - START], dates_is)
        full = metrics(curve[START:], idx[START:])
        rows.append({
            "label": name, "trades": len(trades), "down": down_cap,
            "is_cagr": a["cagr"], "is_mdd": a["mdd"], "is_cal": round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0,
            "oos_cagr": b["cagr"], "oos_mdd": b["mdd"], "all_cagr": full["cagr"], "all_mdd": full["mdd"],
        })

    print()
    print(f"[설정 비교 구간] {dates_is[0].date()} ~ {dates_is[-1].date()}   [확인 구간] {idx[split_i].date()} ~ {idx[-1].date()}")
    print("IS=설정 비교 구간 / OOS=확인 구간 / 하락=하락 포착률(낮을수록 하락장에서 덜 잃음) / CAL=연수익률÷|최대낙폭|")
    print()
    print(f"{'이동평균 규칙':<26}{'거래':>5}{'하락':>5}{'IS연%':>7}{'IS낙폭':>8}{'CAL':>6}{'OOS연%':>8}{'OOS낙폭':>8}{'전체연%':>8}{'전체낙폭':>8}")
    for r in rows:
        pad = 26 - sum(1 for ch in r["label"] if ord(ch) > 127)
        print(f"{r['label']:<{pad}}{r['trades']:>5}{r['down']:>5}{r['is_cagr']:>7}{r['is_mdd']:>8}{r['is_cal']:>6}"
              f"{r['oos_cagr']:>8}{r['oos_mdd']:>8}{r['all_cagr']:>8}{r['all_mdd']:>8}")
    best = max(rows, key=lambda r: r["is_cal"])
    cur = next(r for r in rows if "지금" in r["label"])
    print()
    if best is cur or best["is_cal"] < cur["is_cal"] * 1.1 or best["oos_cagr"] < cur["oos_cagr"]:
        print("결론: 지금 설정(20/120)을 바꿀 만큼 뚜렷하게 나은 조합이 없어요. (CAL 10% 이상 좋고, 확인 구간에서도 뒤지지 않아야 바꿀 가치가 있어요)")
    else:
        print(f"참고: '{best['label']}' 이 비교 구간 CAL {best['is_cal']}로 가장 좋고 확인 구간에서도 뒤지지 않았어요.")
        print("적용하려면 config.py 의 LONG_MAS / LONG_RULE 를 바꾸세요 (예: LONG_MAS = (60, 90, 120), LONG_RULE = \"majority\").")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_ma.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
