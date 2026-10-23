"""동시 보유 종목 수(5/8/10)를 바꿔가며 '지금 30종목' vs '+금·달러 ETF' vs '+6개 전부'를 비교합니다.   실행: python compare_slots.py
자리 수가 늘면 ETF가 주식 자리를 빼앗는 문제가 줄어드는지, 그리고 자리를 늘리는 것 자체가 도움이 되는지 봅니다."""
import sys

import pandas as pd

import config
import market
from backtest import live_options, metrics, prepare, simulate
from compare_assets import ASSETS, LONG, SHORT, STOP, pad

SLOTS = [5, 8, 10]


def main():
    split = "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--split="):
            split = a.split("=", 1)[1]
    orig_tax = config.sell_tax_rate
    config.sell_tax_rate = lambda c: 0.0 if c in ASSETS else orig_tax(c)
    for c, (_, kind) in ASSETS.items():
        config.SECTORS[c] = kind
    frames = {c: market.load_prices(c, config.BACKTEST_START) for c in config.SYMBOLS}
    got = []
    for c, (name, _) in ASSETS.items():
        try:
            frames[c] = market.load_prices(c, config.BACKTEST_START)
            got.append(c)
        except Exception as e:
            print(f"[{name}] 제외: {str(e)[:60]}")
    idx, data = prepare(frames, [SHORT, LONG])
    n, START = len(idx), LONG + 1
    r0 = int(idx.searchsorted(pd.Timestamp(split)))
    stocks = list(config.SYMBOLS)
    gd = [c for c in got if ASSETS[c][1] in ("금", "달러")]
    cases = [("지금 30종목", stocks), ("+ 금·달러 ETF", stocks + gd), ("+ 6개 전부", stocks + got)]
    opts = live_options()
    orig_slots = config.MAX_POSITIONS
    print(f"\n전체={idx[START].date()}~{idx[-1].date()} / 뒤 구간={idx[r0].date()}~   (CAL = 연수익 ÷ 낙폭)")
    print(f"{pad('구성', 18)}{'자리':>4}{'연%':>7}{'낙폭':>8}{'CAL':>6}{'| 뒤 연%':>9}{'낙폭':>8}{'CAL':>6}{'  거래수':>8}")
    rows = []
    try:
        for s in SLOTS:
            config.MAX_POSITIONS = s
            for name, codes in cases:
                curve, trades = simulate(n, {c: data[c] for c in codes}, SHORT, LONG, STOP, **opts)
                a = metrics(curve[START:], idx[START:])
                b = metrics(curve[r0:], idx[r0:]) if r0 > START + 60 else a
                ca = round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0
                cb = round(b["cagr"] / abs(b["mdd"]), 2) if b["mdd"] else 0
                print(f"{pad(name, 18)}{s:>4}{a['cagr']:>7}{a['mdd']:>8}{ca:>6}{b['cagr']:>9}{b['mdd']:>8}{cb:>6}{len(trades):>8}")
                rows.append(dict(slots=s, name=name, cagr=a["cagr"], mdd=a["mdd"], cal=ca, cagr2=b["cagr"], mdd2=b["mdd"], cal2=cb, trades=len(trades)))
            print()
    finally:
        config.MAX_POSITIONS = orig_slots
    df = pd.DataFrame(rows)
    base = df[(df.slots == 5) & (df.name == cases[0][0])].iloc[0]
    print("[자동 해석]")
    s_best = df[df.name == cases[0][0]].sort_values("cal", ascending=False).iloc[0]
    print(f"- ETF 없이 자리만 바꿨을 때 CAL 이 가장 좋은 건 {int(s_best.slots)}자리 ({s_best.cal}) 이고, 지금(5자리)은 {base.cal} 이에요.")
    for nm in (cases[1][0], cases[2][0]):
        sub = df[df.name == nm].sort_values("cal", ascending=False).iloc[0]
        same = df[(df.slots == sub.slots) & (df.name == cases[0][0])].iloc[0]
        better = sub.cal > same.cal and sub.cal2 > same.cal2
        print(f"- '{nm}' 최고는 {int(sub.slots)}자리(CAL {sub.cal}). 같은 자리 수의 ETF 없는 구성({same.cal})보다 {'전체·뒤 구간 모두 좋아요' if better else '두 구간 모두에서 좋아지진 않아요'}.")
    print("- 자리 수를 바꾸면 한 종목당 투자 비중과 낙폭이 같이 변해요. 연수익만 보지 말고 낙폭과 거래수도 같이 보세요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(config.DATA_DIR / "compare_slots.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_slots.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
