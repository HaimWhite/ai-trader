"""종목별로 이동평균 규칙(120일 단독 / 60·90·120 모두 위 / 과반 / 하나라도 ...)을 고르는 방식이 정말 도움이 되는지 검증하는 실험.
실행: python ma_select_experiment.py            (더 긴 기간: python ma_select_experiment.py --start=2016-01-01 --test-start=2019-01-01)
- 매매 코드는 건드리지 않고 결과표만 보여줘요.
- 방식(워크포워드): 6개월마다, 그때까지 '최근 3년' 성적만 보고 종목마다 규칙을 고름 -> 바로 다음 6개월에 그 규칙으로 매매.
  기본 규칙(120일 단독)보다 점수가 MARGIN 이상 좋을 때만 바꿔요 (우연히 좋아 보이는 것을 거르기 위해).
- 비교: 전 종목 같은 규칙으로 고정한 경우 / 종목별 선택 / (참고) 시험 기간 전체를 미리 보고 고른 '사후 선택'(실제로는 불가능)"""
import sys
import warnings

import numpy as np
import pandas as pd

import config
from backtest import live_options, load_data, metrics, prepare, simulate, yearly_returns

warnings.filterwarnings("ignore")
TEST_START = "2019-01-01"
RETRAIN = 126        # 약 6개월마다 다시 고름
LOOKBACK = 756       # 규칙을 고를 때 보는 과거 기간 (약 3년)
MARGIN = 10.0        # 기본 규칙보다 점수가 이만큼(%p) 더 좋아야 바꿈
MIN_TRADES = 4       # 고르는 기간에 거래가 이보다 적으면 기본 규칙 유지
RULES = [   # (이름, 장기선, 규칙) - 첫 번째가 기본 규칙
    ("120일 단독", (120,), "all"), ("90일 단독", (90,), "all"),
    ("60·90·120 모두 위", (60, 90, 120), "all"), ("60·90·120 과반", (60, 90, 120), "majority"),
    ("60·90·120 하나라도", (60, 90, 120), "any"),
]
DEFS = [(l, r) for _, l, r in RULES]
SHORT, STOP = config.SHORT_MA, config.STOP_LOSS_PCT


def one_stock(dd, a, b, k, opts):
    """한 종목만 [a, b) 구간에서 규칙 k 로 매매했을 때의 (점수, 거래 수). 점수 = 수익률 - 0.5 x |최대낙폭| (%p)"""
    sub = {"open": dd["open"][a:b], "close": dd["close"][a:b], "mad": dd["mad"][a:b], "ma": {n: v[a:b] for n, v in dd["ma"].items()}}
    lg, lr = DEFS[k]
    o = {**opts, "longs": lg, "long_rule": lr, "sector_limit": None, "breadth_min": None}
    curve, trades = simulate(b - a, {"x": sub}, SHORT, 120, STOP, **o)
    c = np.asarray(curve, dtype=float)
    ok = ~np.isnan(c)
    if ok.sum() < 60:
        return None
    c = c[ok]
    ret = (c[-1] / c[0] - 1) * 100
    mdd = (c / np.maximum.accumulate(c) - 1).min() * 100
    return ret - 0.5 * abs(mdd), len(trades)


def choose(dd, a, b, opts):
    res = [one_stock(dd, a, b, k, opts) for k in range(len(RULES))]
    base = res[0]
    if base is None or base[1] < MIN_TRADES:
        return 0
    best_k, best = 0, base[0]
    for k in range(1, len(RULES)):
        if res[k] and res[k][1] >= MIN_TRADES and res[k][0] >= base[0] + MARGIN and res[k][0] > best:
            best_k, best = k, res[k][0]
    return best_k


def main():
    global TEST_START
    for a in sys.argv[1:]:
        if a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
        elif a.startswith("--test-start="):
            TEST_START = a.split("=", 1)[1]
    frames = load_data()
    idx, data = prepare(frames, sorted({SHORT, 60, 90, 120}))
    T = len(idx)
    i0 = int(idx.searchsorted(pd.Timestamp(TEST_START)))
    if i0 < 250 or i0 >= T - 60:
        print("데이터 기간이 짧아서 실험할 수 없어요. --start=2016-01-01 --test-start=2019-01-01 처럼 더 과거부터 받으세요.")
        return
    codes = list(data)
    opts = {k: v for k, v in live_options().items() if k not in ("longs", "long_rule")}

    # 1) 워크포워드: 구간마다 종목별 규칙 선택
    sel = {c: np.zeros(T, dtype=int) for c in codes}
    points = list(range(i0, T, RETRAIN))
    changes = nonbase = total = 0
    last = {}
    print(f"\n규칙 고르는 중... (종목 {len(codes)}개 x 구간 {len(points)}개)")
    for pi, t in enumerate(points):
        end = min(points[pi + 1] if pi + 1 < len(points) else T, T)
        for c in codes:
            k = choose(data[c], max(0, t - LOOKBACK), t, opts)
            sel[c][t:end] = k
            total += 1
            nonbase += k != 0
            changes += (c in last and last[c] != k)
            last[c] = k
    pick_count = {name: 0 for name, _, _ in RULES}
    for c in codes:
        pick_count[RULES[last[c]][0]] += 1

    # 2) 사후 선택: 시험 기간 전체를 보고 종목마다 최고 규칙을 하나 고름
    oracle = {}
    for c in codes:
        res = [one_stock(data[c], i0, T, k, opts) for k in range(len(RULES))]
        oracle[c] = int(np.argmax([r[0] if r else -1e9 for r in res]))

    def run(rule_idx=None, k=None):
        o = {**opts, "trade_from": i0}
        if rule_idx is not None:
            return simulate(T, data, SHORT, 120, STOP, rule_idx=rule_idx, rule_defs=DEFS, **o)[0]
        lg, lr = DEFS[k]
        return simulate(T, data, SHORT, 120, STOP, longs=lg, long_rule=lr, **o)[0]

    runs = {}
    for k, (name, _, _) in enumerate(RULES):
        runs[f"전 종목 고정: {name}" + (" (지금)" if k == 0 else "")] = run(k=k)
    runs["종목별 선택 (워크포워드, 실제 가능)"] = run(rule_idx=sel)
    runs["[참고] 사후 선택 (미리 알 수 없음)"] = run(rule_idx={c: np.full(T, oracle[c]) for c in codes})

    dates = idx[i0 - 1:]
    series = {k: v[i0 - 1:] for k, v in runs.items()}
    yearly = yearly_returns(dates, series)
    if (dates.year == dates[0].year).sum() == 1:
        yearly = [y for y in yearly if y["year"] != dates[0].year]
    years = [y["year"] for y in yearly]
    print(f"\n[결과] 시험 기간 {idx[i0].date()} ~ {idx[-1].date()} (같은 날 현금으로 시작, 손절·추적 손절·갭 필터·비용 동일)")
    print(f"{'전략':<42}{'연%':>7}{'낙폭':>8}{'CAL':>6}" + "".join(f"{y:>8}" for y in years))
    rows = []
    for name, vals in series.items():
        m = metrics(vals, dates)
        cal = round(m["cagr"] / abs(m["mdd"]), 2) if m["mdd"] else 0
        per = [next(r[name] for r in yearly if r["year"] == y) for y in years]
        pad = 42 - sum(1 for ch in name if ord(ch) > 127)
        print(f"{name:<{pad}}{m['cagr']:>7}{m['mdd']:>8}{cal:>6}" + "".join(f"{p:>8}" for p in per))
        rows.append({"name": name, "cagr": m["cagr"], "mdd": m["mdd"], "cal": cal})

    print(f"\n[선택 내용] 종목-구간 {total}건 중 기본 규칙(120일 단독)이 아닌 걸 고른 비율 {nonbase / total * 100:.0f}%, 이전 구간과 규칙이 바뀐 비율 {changes / max(total - len(codes), 1) * 100:.0f}%")
    print("가장 최근 선택 분포: " + ", ".join(f"{n} {v}종목" for n, v in pick_count.items() if v))
    base = rows[0]
    sel_row = next(r for r in rows if r["name"].startswith("종목별 선택"))
    orc = next(r for r in rows if r["name"].startswith("[참고]"))
    fixed_best = max(rows[:len(RULES)], key=lambda r: r["cal"])
    print("\n[자동 해석]")
    print(f"- 사후 선택(시험 기간 전체를 미리 보고 고른 값)은 연 {orc['cagr']}%지만 미리 알 수 없는 값이에요. 실제로 가능한 '종목별 선택'은 연 {sel_row['cagr']}%예요 (지금 방식 {base['cagr']}%).")
    if sel_row["cal"] >= base["cal"] * 1.1 and sel_row["cagr"] > base["cagr"] and sel_row["cal"] >= fixed_best["cal"]:
        print("- 종목별 선택이 지금 방식보다 뚜렷하게 좋고 전 종목 고정 규칙보다도 나아요. 다만 한 번의 결과라 바로 쓰지 말고 기간을 바꿔 한 번 더 확인하세요.")
    else:
        print("- 종목별로 규칙을 고르는 방식이 지금 방식보다(또는 전 종목 같은 규칙보다) 뚜렷하게 낫다는 근거가 부족해요. 적용을 권하지 않아요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "ma_select_experiment.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/ma_select_experiment.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
