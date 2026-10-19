"""익절(매수가 대비 +N% 오르면 매도)을 넣으면 지금 전략보다 나은지 비교합니다.   실행: python compare_takeprofit.py
- 같은 날 현금으로 시작, 수수료·세금·슬리피지·손절·추적 손절·갭 필터·종목 수 제한 모두 지금 매매와 동일
- 익절은 종가가 매수가 대비 기준 이상이면 '다음 날 시가'에 팔아요 (다른 매도 신호와 같은 방식)
- 두 가지 방식을 비교해요:  [재진입 금지] 팔고 나면 추세가 한 번 꺾였다가 다시 오를 때까지 그 종목을 다시 사지 않음
                          [재진입 허용] 팔고 나서도 상승 추세가 이어지면 바로 다시 살 수 있음
- 옵션:  --take=0.10,0.15   익절 기준을 바꾸거나 여러 개 비교 (기본 0.10)
         --start=2016-01-01  더 과거부터 받기 (긴 기간 검증)   --split=2023-01-01  이 날짜 전/후를 따로 보기 (기본 2022-01-01)"""
import sys

import numpy as np
import pandas as pd

import config
from backtest import live_options, load_data, metrics, prepare, simulate, yearly_returns

SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT


def main():
    takes, split = [0.10], "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--take="):
            takes = [float(x) for x in a.split("=", 1)[1].split(",")]
        elif a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
        elif a.startswith("--split="):
            split = a.split("=", 1)[1]
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    T = len(idx)
    i0 = max(LONG + 1, 1)
    opts = live_options()

    cases = {"지금 방식 (익절 없음)": {}}
    for t in takes:
        cases[f"익절 +{t * 100:.0f}% (재진입 금지)"] = {"take": t, "take_block": True}
        cases[f"익절 +{t * 100:.0f}% (재진입 허용)"] = {"take": t, "take_block": False}

    results, trade_lists = {}, {}
    for name, kw in cases.items():
        curve, trades = simulate(T, data, SHORT, LONG, STOP, **{**opts, **kw, "trade_from": i0})
        results[name] = curve
        trade_lists[name] = trades

    base_close = np.array([data[c]["close"][i0 - 1] for c in data])
    ok = ~np.isnan(base_close)
    codes = [c for c, k in zip(data, ok) if k]
    bench = [config.INITIAL_CASH * np.mean([data[c]["close"][i] / data[c]["close"][i0 - 1] for c in codes]) for i in range(i0 - 1, T)]
    dates = idx[i0 - 1:]
    series = {k: v[i0 - 1:] for k, v in results.items()}
    series["단순 보유 (동일 비중)"] = bench

    def table(title, dts, ser):
        print(f"\n{title}  ({dts[0].date()} ~ {dts[-1].date()})")
        print(f"{'전략':<34}{'연%':>7}{'낙폭%':>8}{'CAL':>6}{'최종금액':>14}")
        out = []
        for name, vals in ser.items():
            m = metrics(vals, dts)
            cal = round(m["cagr"] / abs(m["mdd"]), 2) if m["mdd"] else 0
            pad = 34 - sum(1 for ch in name if ord(ch) > 127)
            print(f"{name:<{pad}}{m['cagr']:>7}{m['mdd']:>8}{cal:>6}{m['final']:>14,}")
            out.append({"name": name, "cagr": m["cagr"], "mdd": m["mdd"], "cal": cal, "final": m["final"]})
        return out

    rows = table("[1] 전체 기간", dates, series)

    sp = int(idx.searchsorted(pd.Timestamp(split)))
    if i0 < sp < T - 60:
        a_idx = [k for k in range(i0 - 1, sp)]
        b_idx = [k for k in range(sp - 1, T)]
        pa = {k: [v[k] for k in a_idx] if len(v) == T else v for k, v in results.items()}
        pb = {k: [v[k] for k in b_idx] for k, v in results.items()}
        ba = [config.INITIAL_CASH * np.mean([data[c]["close"][k] / data[c]["close"][a_idx[0]] for c in codes]) for k in a_idx]
        bb = [config.INITIAL_CASH * np.mean([data[c]["close"][k] / data[c]["close"][b_idx[0]] for c in codes]) for k in b_idx]
        pa["단순 보유 (동일 비중)"], pb["단순 보유 (동일 비중)"] = ba, bb
        table(f"[2] 앞 구간 ({split} 이전)", idx[a_idx], pa)
        table(f"[3] 뒤 구간 ({split} 이후, 처음 보는 구간에 가까움)", idx[b_idx], pb)

    print("\n[4] 연도별 수익률 %")
    yearly = yearly_returns(dates, series)
    years = [y["year"] for y in yearly]
    print(f"{'전략':<34}" + "".join(f"{y:>8}" for y in years))
    for name in series:
        pad = 34 - sum(1 for ch in name if ord(ch) > 127)
        print(f"{name:<{pad}}" + "".join(f"{next(r[name] for r in yearly if r['year'] == y):>8}" for y in years))

    print("\n[5] 거래 내용")
    print(f"{'전략':<34}{'거래수':>7}{'승률%':>7}{'평균손익%':>10}{'익절건수':>9}{'추적손절':>9}{'손절':>6}{'하락추세':>9}")
    for name, tr in trade_lists.items():
        n = len(tr)
        if not n:
            continue
        wins = sum(1 for t in tr if t["pnl"] > 0)
        cnt = lambda w: sum(1 for t in tr if t["why"] == w)
        pad = 34 - sum(1 for ch in name if ord(ch) > 127)
        print(f"{name:<{pad}}{n:>7}{wins / n * 100:>7.1f}{np.mean([t['pnl_pct'] for t in tr]):>10.2f}{cnt('익절'):>9}{cnt('추적손절'):>9}{cnt('손절'):>6}{cnt('하락 추세'):>9}")

    base = rows[0]
    better = [r for r in rows[1:-1] if r["cal"] > base["cal"] and r["cagr"] > base["cagr"]]
    print("\n[자동 해석]")
    if better:
        print("- 전체 기간에서 지금 방식보다 연 수익률과 CAL(수익/낙폭)이 모두 좋은 조합: " + ", ".join(r["name"] for r in better))
        print("- 다만 [2]와 [3]에서 앞 구간·뒤 구간 모두 좋아야 믿을 만해요. 한쪽만 좋다면 우연일 수 있어요.")
    else:
        print("- 익절을 넣어도 지금 방식보다 낫다고 말할 근거가 없어요. 지금 방식을 유지하는 게 좋아요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_takeprofit.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_takeprofit.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
