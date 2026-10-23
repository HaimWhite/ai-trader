"""놀고 있는 현금에 이자가 붙는다고 보면 성과가 얼마나 달라지는지, 그리고 동시 보유 5/8/10자리 중 어느 쪽이 나은지 비교합니다.
실행: python compare_cash.py        옵션: --rates=0,0.03   --split=2022-01-01
현금 이자 0%는 지금 백테스트 방식이고, 3%는 CMA·MMF·단기채 ETF 에 넣어둔다고 가정한 값입니다(세금 전)."""
import sys

import pandas as pd

import config
import market
from backtest import live_options, metrics, prepare, simulate

SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT


def pad(text, width):
    return text + " " * max(0, width - len(text) - sum(1 for ch in text if ord(ch) > 127))


def main():
    rates, split = [0.0, 0.03], "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--rates="):
            rates = [float(x) for x in a.split("=", 1)[1].split(",")]
        elif a.startswith("--split="):
            split = a.split("=", 1)[1]
    frames = {c: market.load_prices(c, config.BACKTEST_START) for c in config.SYMBOLS}
    idx, data = prepare(frames, [SHORT, LONG])
    n, START = len(idx), LONG + 1
    r0 = int(idx.searchsorted(pd.Timestamp(split)))
    opts = live_options()
    orig = config.MAX_POSITIONS
    print(f"\n전체={idx[START].date()}~{idx[-1].date()} / 뒤 구간={idx[r0].date()}~")
    print(f"{pad('현금이자', 10)}{'자리':>4}{'연%':>7}{'낙폭':>8}{'CAL':>6}{'| 뒤 연%':>9}{'낙폭':>8}{'CAL':>6}")
    rows = []
    try:
        for r in rates:
            for s in (5, 8, 10):
                config.MAX_POSITIONS = s
                curve, _ = simulate(n, data, SHORT, LONG, STOP, cash_rate=r, **opts)
                a = metrics(curve[START:], idx[START:])
                b = metrics(curve[r0:], idx[r0:]) if r0 > START + 60 else a
                ca = round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0
                cb = round(b["cagr"] / abs(b["mdd"]), 2) if b["mdd"] else 0
                print(f"{pad(f'{r * 100:.0f}%', 10)}{s:>4}{a['cagr']:>7}{a['mdd']:>8}{ca:>6}{b['cagr']:>9}{b['mdd']:>8}{cb:>6}")
                rows.append(dict(rate=r, slots=s, cagr=a["cagr"], mdd=a["mdd"], cal=ca, cagr2=b["cagr"], mdd2=b["mdd"], cal2=cb))
            print()
    finally:
        config.MAX_POSITIONS = orig
    df = pd.DataFrame(rows)
    z = df[(df.rate == 0) & (df.slots == 5)]
    print("[자동 해석]")
    if len(z):
        for r in rates:
            if r == 0:
                continue
            o = df[(df.rate == r) & (df.slots == 5)].iloc[0]
            print(f"- 현금 이자 {r * 100:.0f}%를 인정하면 5자리 기준 연수익이 {z.iloc[0].cagr}% → {o.cagr}% ({o.cagr - z.iloc[0].cagr:+.2f}%p)로 달라져요. 이 차이만큼이 '놀고 있는 현금'의 값어치예요.")
    print("- 현금을 오래 들고 있는 구성일수록 이자 효과가 커요. 자리 수끼리 비교는 같은 이자율 줄에서 하세요.")
    print("- 실제로 이자를 받으려면 남는 현금을 CMA·단기채 ETF 등에 두는 별도 운용이 필요해요. 지금 가상계좌는 현금에 이자를 붙이지 않아요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(config.DATA_DIR / "compare_cash.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_cash.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
