"""'시장 상황이 나쁠 때는 새로 사지 않는' 필터를 붙이면 좋아지는지 비교합니다.   실행: python compare_regime.py
이미 매수한 종목의 매도 규칙은 그대로이고, 시장이 나쁜 날의 '신규 매수'만 막습니다.
필터 종류
  A. 상승 추세 종목 비율: 30종목 중 20일선>120일선인 종목이 X% 미만이면 신규 매수 중지 (X=30/40/50/60%)
  B. 시장 평균선: 30종목 평균 지수(동일 비중)가 N일선 아래이면 신규 매수 중지 (N=60/120)
  C. 시장 급락: 30종목 평균 지수가 최근 20일 고점보다 X% 이상 내려가 있으면 신규 매수 중지 (X=5/8%)
옵션: --split=2022-01-01"""
import sys

import numpy as np
import pandas as pd

import config
import market
from backtest import live_options, metrics, prepare, simulate

SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT


def pad(text, width):
    return text + " " * max(0, width - len(text) - sum(1 for ch in text if ord(ch) > 127))


def main():
    split = "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--split="):
            split = a.split("=", 1)[1]
    frames = {c: market.load_prices(c, config.BACKTEST_START) for c in config.SYMBOLS}
    idx, data = prepare(frames, [SHORT, LONG])
    n, START = len(idx), LONG + 1
    r0 = int(idx.searchsorted(pd.Timestamp(split)))
    # 시장 평균 지수: 종목별 일간 수익률의 평균을 이어 붙임 (상장 전 종목은 제외)
    rets = pd.DataFrame({c: pd.Series(data[c]["close"], index=idx).pct_change() for c in data}).mean(axis=1).fillna(0)
    mk = (1 + rets).cumprod()
    # 신호는 '전날 종가까지' 로 만들어 오늘 매수 판단에 미래 정보가 섞이지 않게 함
    def shifted(b):
        b = pd.Series(b, index=idx).shift(1)
        return b.fillna(True).astype(bool).values

    cases = [("필터 없음 (지금)", None, None)]
    for x in (0.3, 0.4, 0.5, 0.6):
        cases.append((f"A 상승종목 {int(x * 100)}% 미만 중지", x, None))
    for N in (60, 120):
        cases.append((f"B 시장 {N}일선 아래 중지", None, shifted(mk > mk.rolling(N).mean())))
    for X in (0.05, 0.08):
        cases.append((f"C 20일 고점 -{int(X * 100)}% 중지", None, shifted(mk / mk.rolling(20).max() - 1 > -X)))
    opts = live_options()
    print(f"\n전체={idx[START].date()}~{idx[-1].date()} / 뒤 구간={idx[r0].date()}~   (CAL = 연수익 ÷ 낙폭)")
    print(f"{pad('필터', 26)}{'연%':>7}{'낙폭':>8}{'CAL':>6}{'| 뒤 연%':>9}{'낙폭':>8}{'CAL':>6}{'  거래':>6}{'  최근1년%':>10}")
    rows = []
    last = n - 252
    for name, bm, gate in cases:
        o = dict(opts)
        o["breadth_min"] = bm
        curve, trades = simulate(n, data, SHORT, LONG, STOP, entry_gate=gate, **o)
        a = metrics(curve[START:], idx[START:])
        b = metrics(curve[r0:], idx[r0:]) if r0 > START + 60 else a
        ca = round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0
        cb = round(b["cagr"] / abs(b["mdd"]), 2) if b["mdd"] else 0
        y1 = (curve[-1] / curve[last] - 1) * 100
        print(f"{pad(name, 26)}{a['cagr']:>7}{a['mdd']:>8}{ca:>6}{b['cagr']:>9}{b['mdd']:>8}{cb:>6}{len(trades):>6}{y1:>10.1f}")
        rows.append(dict(name=name, cagr=a["cagr"], mdd=a["mdd"], cal=ca, cagr2=b["cagr"], mdd2=b["mdd"], cal2=cb, trades=len(trades), last1y=round(y1, 1)))
    df = pd.DataFrame(rows)
    base = df.iloc[0]
    good = df.iloc[1:][(df.iloc[1:].cal > base.cal) & (df.iloc[1:].cal2 > base.cal2) & (df.iloc[1:].cagr >= base.cagr - 1)]
    print("\n[자동 해석]")
    if len(good):
        print("- 전체·뒤 구간 모두에서 CAL 이 좋아지고 연수익도 크게 줄지 않은 필터: " + ", ".join(good.name))
        print("  다만 여러 개를 시험해 가장 좋은 것을 고르면 우연히 좋아 보일 수 있어요. 이웃한 값(예: 40%·50%)도 함께 좋아야 믿을 만해요.")
    else:
        print("- 어떤 필터도 두 구간 모두에서 분명히 좋아지지 않았어요. 필터를 붙이면 좋은 시작 신호까지 놓쳐서 수익이 줄어드는 경우가 많아요.")
    print("- 낙폭이 줄어도 연수익이 많이 줄면 '덜 벌고 덜 잃는' 것일 뿐이에요. 연수익·낙폭·CAL 을 같이 보세요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(config.DATA_DIR / "compare_regime.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_regime.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
