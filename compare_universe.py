"""새로 추가한 종목 10개가 성과·낙폭에 어떤 영향을 줬는지 확인합니다. 실행: python compare_universe.py   (더 긴 기간: --start=2016-01-01)
- 40개 전체 / 기존 30개만 / 새 종목을 하나씩 뺀 경우를 지금 실제 설정 그대로 비교해요.
- 주의: 새 종목은 '지금 와서 보니 잘 알려진 종목'이라 과거 수익이 실제보다 좋게 나올 수 있어요 (선택 편향)."""
import sys

import numpy as np
import pandas as pd

import config
from backtest import live_options, load_data, metrics, prepare, simulate

NEW = ["373220", "012450", "329180", "034020", "035720", "277810", "145020", "AMD", "PLTR", "COST"]
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT
START = 120
RECENT = "2019-01-01"


def pad(text, width):
    return text + " " * max(0, width - len(text) - sum(1 for ch in text if ord(ch) > 127))


def main():
    for a in sys.argv[1:]:
        if a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    n = len(idx)
    r0 = int(idx.searchsorted(pd.Timestamp(RECENT)))
    new = [c for c in NEW if c in data]
    old = [c for c in data if c not in new]
    opts = live_options()

    def run(codes):
        sub = {c: data[c] for c in codes}
        return simulate(n, sub, SHORT, LONG, STOP, **opts)

    def line(name, curve):
        a = metrics(curve[START:], idx[START:])
        b = metrics(curve[r0:], idx[r0:]) if r0 > START else a
        ca = round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0
        cb = round(b["cagr"] / abs(b["mdd"]), 2) if b["mdd"] else 0
        return {"name": name, "cagr": a["cagr"], "mdd": a["mdd"], "cal": ca, "cagr2": b["cagr"], "mdd2": b["mdd"], "cal2": cb}

    rows = []
    full_curve, full_trades = run(list(data))
    rows.append(line(f"전체 {len(data)}종목 (지금)", full_curve))
    rows.append(line(f"기존 {len(old)}종목만", run(old)[0]))
    rows.append(line(f"새 종목 {len(new)}개만", run(new)[0]))
    for c in new:
        rows.append(line(f"전체에서 {config.SYMBOLS[c]} 뺌", run([x for x in data if x != c])[0]))

    print(f"\n[종목 구성별 성과] 전체={idx[START].date()}~{idx[-1].date()} / 최근={idx[r0].date()}~")
    print(f"{pad('구성', 30)}{'연%':>7}{'낙폭':>8}{'CAL':>6}{'  | 최근 연%':>12}{'낙폭':>8}{'CAL':>6}")
    for r in rows:
        print(f"{pad(r['name'], 30)}{r['cagr']:>7}{r['mdd']:>8}{r['cal']:>6}{r['cagr2']:>12}{r['mdd2']:>8}{r['cal2']:>6}")

    base = rows[0]
    print("\n[새 종목을 하나씩 뺐을 때 낙폭 변화] (양수 = 빼면 낙폭이 줄어듦 = 그 종목이 낙폭을 키우고 있었음)")
    loo = sorted(rows[3:], key=lambda r: -(r["mdd"] - base["mdd"]))
    for r in loo:
        d = r["mdd"] - base["mdd"]
        print(f"  {pad(r['name'], 28)} 낙폭 {r['mdd']:>7} ({d:+.1f}%p)  연수익 {r['cagr']:>6} ({r['cagr'] - base['cagr']:+.1f}%p)")

    print("\n[새 종목 개별 특성] 거래 = 전략이 매매한 횟수 / 최악 = 한 번의 거래에서 가장 크게 잃은 %")
    print(f"{pad('종목', 20)}{'데이터일':>8}{'보유시 연%':>10}{'자체낙폭':>9}{'거래':>5}{'승률%':>7}{'최악%':>8}{'누적손익(만)':>12}")
    for c in new:
        close = pd.Series(data[c]["close"], index=idx).dropna()
        yrs = max((close.index[-1] - close.index[0]).days / 365.25, 0.1)
        own_cagr = ((close.iloc[-1] / close.iloc[0]) ** (1 / yrs) - 1) * 100
        own_mdd = (close / close.cummax() - 1).min() * 100
        ts = [t for t in full_trades if t["code"] == c]
        wins = sum(t["pnl"] > 0 for t in ts)
        print(f"{pad(config.SYMBOLS[c], 20)}{len(close):>8}{own_cagr:>10.1f}{own_mdd:>9.1f}{len(ts):>5}{(wins / len(ts) * 100 if ts else 0):>7.0f}"
              f"{min((t['pnl_pct'] for t in ts), default=0):>8.1f}{sum(t['pnl'] for t in ts) / 1e4:>12.0f}")

    print("\n[자동 해석]")
    worse = [r for r in loo if r["mdd"] - base["mdd"] >= 2]
    if rows[1]["mdd"] - base["mdd"] >= 5:
        print(f"- 기존 {len(old)}종목만 쓰면 낙폭이 {rows[1]['mdd']}%로, 새 종목 때문에 낙폭이 {rows[1]['mdd'] - base['mdd']:.0f}%p 커진 상태예요.")
    else:
        print("- 새 종목을 넣고 빼도 낙폭 차이가 크지 않아요. 낙폭은 새 종목보다 전략 자체의 특성에 가까워요.")
    if worse:
        print("- 빼면 낙폭이 2%p 이상 줄어드는 종목: " + ", ".join(r["name"].replace("전체에서 ", "").replace(" 뺌", "") for r in worse))
    print("- 새 종목은 지금 시점에서 고른 종목이라 과거 수익이 부풀려졌을 수 있어요. 수익이 늘었다는 사실보다 '낙폭이 얼마나 커졌는가'를 더 눈여겨보세요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_universe.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
