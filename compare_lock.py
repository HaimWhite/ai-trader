"""'본전 보호' 비교: 한 번 +N% 이상 오른 적이 있는 종목이 매수가 근처(+0.5%)까지 내려오면 팔아서, 이익이 났던 종목이 손실로 끝나는 걸 막는 방식.
실행: python compare_lock.py      옵션: --lock=0.08,0.10,0.15  --exit=0.005  --split=2022-01-01  --start=2016-01-01
나머지(손절 -7%, 추적 손절 20%, 갭 필터, 5종목, 수수료·세금, 복리)는 지금 매매와 같아요.
본전 보호는 종가 기준으로 판단해서 '다음 날 시가'에 팔아요(다른 매도 신호와 같은 방식)."""
import sys

import numpy as np
import pandas as pd

import config
from backtest import live_options, load_data, metrics, prepare, simulate, yearly_returns

SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT


def pad(t, w):
    return t + " " * max(0, w - len(t) - sum(1 for ch in t if ord(ch) > 127))


def main():
    locks, ex, split = [0.08, 0.10, 0.15], 0.005, "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--lock="):
            locks = [float(x) for x in a.split("=", 1)[1].split(",")]
        elif a.startswith("--exit="):
            ex = float(a.split("=", 1)[1])
        elif a.startswith("--split="):
            split = a.split("=", 1)[1]
        elif a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    T, i0 = len(idx), max(LONG + 1, 1)
    base = live_options()
    cases = {"지금 방식 (본전 보호 없음)": {}}
    for L in locks:
        cases[f"본전 보호 (+{L * 100:.0f}% 넘으면)"] = {"lock_at": L, "lock_exit": ex}
    res, trs = {}, {}
    for name, kw in cases.items():
        curve, tr = simulate(T, data, SHORT, LONG, STOP, **{**base, **kw, "trade_from": i0})
        res[name], trs[name] = curve, tr
    dates = idx[i0 - 1:]
    series = {k: v[i0 - 1:] for k, v in res.items()}

    def table(title, dts, ser):
        print(f"\n{title}  ({dts[0].date()} ~ {dts[-1].date()})")
        print(f"{pad('전략', 32)}{'연%':>7}{'낙폭%':>8}{'CAL':>6}{'최종금액':>14}")
        rows = []
        for name, v in ser.items():
            m = metrics(v, dts)
            cal = round(m["cagr"] / abs(m["mdd"]), 2) if m["mdd"] else 0
            print(f"{pad(name, 32)}{m['cagr']:>7}{m['mdd']:>8}{cal:>6}{m['final']:>14,}")
            rows.append({"name": name, "cagr": m["cagr"], "mdd": m["mdd"], "cal": cal, "final": m["final"]})
        return rows

    rows = table(f"[1] 전체 기간 (시작 {config.INITIAL_CASH:,}원, 복리)", dates, series)
    sp = int(idx.searchsorted(pd.Timestamp(split)))
    rows_b = None
    if i0 < sp < T - 60:
        a_i, b_i = list(range(i0 - 1, sp)), list(range(sp - 1, T))
        table(f"[2] 앞 구간 ({split} 이전)", idx[a_i], {k: [v[i] for i in a_i] for k, v in res.items()})
        rows_b = table(f"[3] 뒤 구간 ({split} 이후, 처음 보는 구간에 가까움)", idx[b_i], {k: [v[i] for i in b_i] for k, v in res.items()})
    print("\n[4] 연도별 수익률 %")
    ys = yearly_returns(dates, series)
    names = list(series)
    print(pad("연도", 6) + "".join(f"{('방식' + str(i + 1)):>9}" for i in range(len(names))))
    for y in ys:
        print(pad(str(y["year"]), 6) + "".join(f"{y[n]:>9}" for n in names))
    for i, n in enumerate(names):
        print(f"  방식{i + 1} = {n}")
    print("\n[5] 거래 통계")
    print(f"{pad('전략', 32)}{'거래':>6}{'승률%':>7}{'이긴평균%':>10}{'진평균%':>9}{'손익비':>7}{'본전보호 매도':>14}")
    for n, tr in trs.items():
        w = [t["pnl_pct"] for t in tr if t["pnl"] > 0]
        l = [t["pnl_pct"] for t in tr if t["pnl"] <= 0]
        aw, al = (np.mean(w) if w else 0), (np.mean(l) if l else 0)
        k = sum(1 for t in tr if t["why"] == "본전 보호")
        print(f"{pad(n, 32)}{len(tr):>6}{(len(w) / len(tr) * 100 if tr else 0):>7.0f}{aw:>10.1f}{al:>9.1f}{(abs(aw / al) if al else 0):>7.2f}{k:>14}")
    print("\n[자동 해석]")
    b = rows[0]
    good = [r for r in rows[1:] if r["cal"] > b["cal"] and r["cagr"] >= b["cagr"] - 0.5]
    if good and rows_b:
        bb = rows_b[0]
        both = [r for r, rb in zip(rows[1:], rows_b[1:]) if r in good and rb["cal"] > bb["cal"]]
        if both:
            print("- 전체와 뒤 구간 모두에서 CAL 이 좋아진 기준: " + ", ".join(r["name"] for r in both))
            print("  이웃한 기준(예: +8%, +10%)도 같이 좋아야 믿을 만해요. 하나만 좋다면 우연일 수 있어요.")
        else:
            print("- 전체에서는 좋아졌지만 뒤 구간에서는 아니에요. 우연일 수 있어서 바로 적용하지 않는 게 좋아요.")
    else:
        print("- 본전 보호가 분명히 도움이 된다고 보기 어려워요. 이익 중이던 종목을 본전에 팔고 나서 다시 크게 오르는 경우를 놓치는 비용이 더 클 수 있어요.")
    print("- [5]의 '본전보호 매도' 건수가 많을수록 큰 상승을 타다 중간에 내리는 경우가 잦다는 뜻이에요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_lock.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_lock.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
