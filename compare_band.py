"""손절 -5% / 익절 +15% 고정 구간 방식을 지금 전략과 비교합니다.   실행: python compare_band.py
- 복리: 매수할 때마다 '그날의 총 자산'을 기준으로 금액을 정해요. 번 돈이 다음 투자 금액에 그대로 합쳐지고, 잃으면 줄어들어요. (시작 자금 고정이 아님)
- 수수료·세금·슬리피지·갭 필터·5종목 제한·변동성 기반 금액 조절은 지금 매매와 같고, 손절·익절·추적 손절만 바꿔서 비교해요.
- 익절은 종가가 매수가 대비 +15% 이상이면 '다음 날 시가'에 팔아요 (다른 매도 신호와 같은 방식).
- 옵션: --stop=0.05 --take=0.15 (기준 바꾸기)   --split=2022-01-01   --start=2016-01-01"""
import sys

import numpy as np
import pandas as pd

import config
from backtest import live_options, load_data, metrics, prepare, simulate, yearly_returns

SHORT, LONG = config.SHORT_MA, config.LONG_MA


def pad(t, w):
    return t + " " * max(0, w - len(t) - sum(1 for ch in t if ord(ch) > 127))


def main():
    stop, take, split = 0.05, 0.15, "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--stop="):
            stop = abs(float(a.split("=", 1)[1]))
        elif a.startswith("--take="):
            take = float(a.split("=", 1)[1])
        elif a.startswith("--split="):
            split = a.split("=", 1)[1]
        elif a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    T, i0 = len(idx), max(LONG + 1, 1)
    base = live_options()
    st = f"-{stop * 100:.0f}%"
    cases = {
        f"지금 방식 (손절 {config.STOP_LOSS_PCT * 100:.0f}%, 추적 {config.TRAIL_STOP_PCT * 100:.0f}%)": (config.STOP_LOSS_PCT, {}),
        f"손절 {st}, 익절 +{take * 100:.0f}% (재진입 금지)": (-stop, {"trail": None, "take": take, "take_block": True}),
        f"손절 {st}, 익절 +{take * 100:.0f}% (재진입 허용)": (-stop, {"trail": None, "take": take, "take_block": False}),
        f"손절 {st}만 바꿈 (익절 없음, 추적 유지)": (-stop, {}),
    }
    res, trs = {}, {}
    for name, (s, kw) in cases.items():
        curve, tr = simulate(T, data, SHORT, LONG, s, **{**base, **kw, "trade_from": i0})
        res[name], trs[name] = curve, tr
    dates = idx[i0 - 1:]
    series = {k: v[i0 - 1:] for k, v in res.items()}

    def table(title, dts, ser):
        print(f"\n{title}  ({dts[0].date()} ~ {dts[-1].date()})")
        print(f"{pad('전략', 40)}{'연%':>7}{'낙폭%':>8}{'CAL':>6}{'최종금액':>14}")
        rows = []
        for name, v in ser.items():
            m = metrics(v, dts)
            cal = round(m["cagr"] / abs(m["mdd"]), 2) if m["mdd"] else 0
            print(f"{pad(name, 40)}{m['cagr']:>7}{m['mdd']:>8}{cal:>6}{m['final']:>14,}")
            rows.append({"name": name, "cagr": m["cagr"], "mdd": m["mdd"], "cal": cal, "final": m["final"]})
        return rows

    rows = table(f"[1] 전체 기간 (시작 {config.INITIAL_CASH:,}원, 복리)", dates, series)
    sp = int(idx.searchsorted(pd.Timestamp(split)))
    if i0 < sp < T - 60:
        a_i, b_i = list(range(i0 - 1, sp)), list(range(sp - 1, T))
        table(f"[2] 앞 구간 ({split} 이전)", idx[a_i], {k: [v[i] for i in a_i] for k, v in res.items()})
        table(f"[3] 뒤 구간 ({split} 이후, 처음 보는 구간에 가까움)", idx[b_i], {k: [v[i] for i in b_i] for k, v in res.items()})
    print("\n[4] 연도별 수익률 %")
    ys = yearly_returns(dates, series)
    names = list(series)
    print(pad("연도", 6) + "".join(f"{('방식' + str(i + 1)):>9}" for i in range(len(names))))
    for y in ys:
        print(pad(str(y["year"]), 6) + "".join(f"{y[n]:>9}" for n in names))
    for i, n in enumerate(names):
        print(f"  방식{i + 1} = {n}")
    print("\n[5] 거래 통계")
    print(f"{pad('전략', 40)}{'거래':>6}{'승률%':>7}{'이긴평균%':>10}{'진평균%':>9}{'손익비':>7}")
    for n, tr in trs.items():
        w = [t["pnl_pct"] for t in tr if t["pnl"] > 0]
        l = [t["pnl_pct"] for t in tr if t["pnl"] <= 0]
        aw, al = (np.mean(w) if w else 0), (np.mean(l) if l else 0)
        print(f"{pad(n, 40)}{len(tr):>6}{(len(w) / len(tr) * 100 if tr else 0):>7.0f}{aw:>10.1f}{al:>9.1f}{(abs(aw / al) if al else 0):>7.2f}")
    print("\n[자동 해석]")
    b, u = rows[0], rows[1]
    if u["cal"] > b["cal"] and u["cagr"] >= b["cagr"]:
        print("- 손절·익절 고정 방식이 연수익·낙폭 대비 수익 모두에서 지금 방식보다 낫습니다. 뒤 구간([3])과 연도별([4])에서도 같은지 확인하세요.")
    else:
        print("- 손절·익절 고정 방식이 지금 방식보다 낫다고 보기 어려워요. 익절 +15%는 큰 상승 구간의 이익을 일찍 끊어서, 수익이 몇 번의 큰 상승에서 나오는 이 전략에서는 손해가 되는 경우가 많아요.")
    print("- 손절을 -5%로 좁히면 평소 흔들림에도 잘 걸려서 거래 수와 비용이 늘어요. [5]의 거래 수와 승률 변화를 보세요.")
    print("- 복리라서 초반 몇 번의 결과가 이후 전체에 영향을 줘요. 앞/뒤 구간이 같은 방향인지 꼭 확인하세요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_band.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_band.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
