"""머신러닝(딥러닝 포함) 종목 선택 실험. 실행: python ml_experiment.py   (처음 한 번: pip install scikit-learn)
- 매매 코드는 전혀 건드리지 않는 '실험'입니다. 결과표만 보여줘요.
- 방식: 6개월마다, 그때까지의 과거 데이터만으로 학습 -> 바로 다음 6개월을 예측 (미래 정보가 섞이지 않는 '워크포워드' 검증)
- 예측 목표: 앞으로 20거래일 동안 '30종목 중 상대적으로 더 오를 종목'인지
  python ml_experiment.py --fast   신경망을 빼고 빠르게 (선형·부스팅만)
  --start=2016-01-01       데이터를 더 과거부터 받기 (긴 기간 검증)
  --test-start=2019-01-01  이 날짜부터 검증 (그 전은 학습용)"""
import sys
import warnings

import numpy as np
import pandas as pd

import config
from backtest import live_options, load_data, metrics, prepare, simulate, yearly_returns

warnings.filterwarnings("ignore")
H = 20                    # 예측 기간(거래일)
TEST_START = "2023-01-01"
RETRAIN = 126             # 약 6개월마다 다시 학습
FEATURES = ["ret5", "ret20", "ret60", "ret120", "c_ma20", "c_ma60", "ma20_ma120", "vol20", "dd120", "up120", "gap60", "volratio"]
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT


def build_panel(frames, idx, data):
    codes = list(data)
    T, N = len(idx), len(codes)
    feats = {k: np.full((T, N), np.nan) for k in FEATURES}
    fwd = np.full((T, N), np.nan)
    for j, code in enumerate(codes):
        c = pd.Series(data[code]["close"], index=idx)
        o = pd.Series(data[code]["open"], index=idx)
        r1 = c.pct_change()
        f = {
            "ret5": c.pct_change(5), "ret20": c.pct_change(20), "ret60": c.pct_change(60), "ret120": c.pct_change(120),
            "c_ma20": c / c.rolling(20).mean() - 1, "c_ma60": c / c.rolling(60).mean() - 1,
            "ma20_ma120": c.rolling(20).mean() / c.rolling(120).mean() - 1,
            "vol20": r1.rolling(20).std(), "dd120": c / c.rolling(120).max() - 1, "up120": c / c.rolling(120).min() - 1,
            "gap60": ((o / c.shift(1) - 1).abs() >= 0.05).astype(float).rolling(60).sum(),
        }
        if "Volume" in frames[code].columns:
            v = frames[code]["Volume"].reindex(idx).fillna(0)
            f["volratio"] = v.rolling(5).mean() / v.rolling(60).mean().replace(0, np.nan)
        for k, s in f.items():
            feats[k][:, j] = s.to_numpy(dtype=float)
        fwd[:, j] = (c.shift(-H) / c - 1).to_numpy(dtype=float)

    def xrank(a):   # 날짜마다 종목 간 순위(0~1)로 바꿔서, 시장 전체의 오르내림이 아니라 '종목 간 상대 비교'만 보게 함
        return pd.DataFrame(a).rank(axis=1, pct=True).to_numpy()

    keep = [k for k in FEATURES if not np.isnan(feats[k]).all()]
    X = np.stack([xrank(feats[k]) for k in keep], axis=2)
    return codes, keep, X, xrank(fwd), fwd


def walk_forward(factory, X, y, i_first):
    T, N, F = X.shape
    scores = np.full((T, N), np.nan)
    for s0 in range(i_first, T, RETRAIN):
        s1 = min(s0 + RETRAIN, T)
        Xtr, ytr = X[: s0 - H].reshape(-1, F), y[: s0 - H].reshape(-1)   # 시험 시작 H일 전까지만 학습 (정답이 겹치지 않게)
        ok = ~np.isnan(Xtr).any(1) & ~np.isnan(ytr)
        if ok.sum() < 500:
            continue
        model = factory()
        model.fit(Xtr[ok], ytr[ok])
        Xte = X[s0:s1].reshape(-1, F)
        okt = ~np.isnan(Xte).any(1)
        pred = np.full(len(Xte), np.nan)
        pred[okt] = model.predict(Xte[okt])
        scores[s0:s1] = pred.reshape(s1 - s0, N)
    return scores


def quality(scores, fwd, i0):
    """모델 점수가 실제로 앞으로의 수익률 순서를 맞췄는지: 순위상관(IC), 상위20%-하위20% 수익률 차"""
    ics, spreads = [], []
    for i in range(i0, len(scores) - H):
        s, f = scores[i], fwd[i]
        ok = ~np.isnan(s) & ~np.isnan(f)
        if ok.sum() < 10:
            continue
        ics.append(np.corrcoef(pd.Series(s[ok]).rank().to_numpy(), pd.Series(f[ok]).rank().to_numpy())[0, 1])
        order, k = np.argsort(s[ok]), max(1, ok.sum() // 5)
        spreads.append(f[ok][order[-k:]].mean() - f[ok][order[:k]].mean())
    if not ics:
        return None
    ics = np.array(ics)
    n_eff = max(len(ics) / H, 1)   # 20일씩 겹치는 예측이라 실제로 독립인 표본 수는 훨씬 적음
    return {"ic": ics.mean(), "pos": (ics > 0).mean() * 100, "spread": np.mean(spreads) * 100, "t": ics.mean() / (ics.std() + 1e-12) * np.sqrt(n_eff)}


def main():
    global TEST_START
    fast = "--fast" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
        elif a.startswith("--test-start="):
            TEST_START = a.split("=", 1)[1]
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.linear_model import Ridge
        from sklearn.neural_network import MLPRegressor
    except ImportError:
        print("scikit-learn 이 필요해요:  pip install scikit-learn")
        return
    frames = load_data()
    idx, data = prepare(frames, [SHORT, LONG])
    T = len(idx)
    i0 = int(idx.searchsorted(pd.Timestamp(TEST_START)))
    if i0 < 300 or i0 >= T - 60:
        print("데이터 기간이 짧아서 실험할 수 없어요. config.py 의 BACKTEST_START 를 더 과거로 두세요.")
        return
    codes, keep, X, y, fwd = build_panel(frames, idx, data)
    print(f"\n학습 재료(특징) {len(keep)}개: {', '.join(keep)}")

    models = {"선형(기준)": lambda: Ridge(alpha=10.0),
              "부스팅": lambda: HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, random_state=0)}
    if not fast:
        models["신경망"] = lambda: MLPRegressor(hidden_layer_sizes=(32, 16), alpha=1e-3, max_iter=200, early_stopping=True, random_state=0)

    scores, qual = {}, {}
    for name, fac in models.items():
        print(f"학습 중: {name} ...")
        s = walk_forward(fac, X, y, i0)
        scores[name] = {c: pd.DataFrame(s).rank(axis=1, pct=True).to_numpy()[:, j] for j, c in enumerate(codes)}   # 날짜별 순위(0~1)
        qual[name] = quality(s, fwd, i0)

    print(f"\n[1] 모델이 실제로 맞췄나? (시험 기간 {idx[i0].date()} ~ {idx[-1].date()})")
    print("IC=점수와 실제 수익률 순위의 상관(0이면 예측력 없음, 0.03 이상이면 약한 신호) / 상위-하위=점수 상위 20%가 하위 20%보다 20일 동안 더 번 수익률(%p)")
    print("t값=대략적인 믿을 만한 정도(2 이상이어야 우연이 아닐 가능성이 높아요)")
    print(f"{'모델':<12}{'IC 평균':>9}{'IC>0 비율%':>11}{'상위-하위':>10}{'t값(근사)':>10}")
    for name, q in qual.items():
        pad = 12 - sum(1 for ch in name if ord(ch) > 127)
        print(f"{name:<{pad}}" + (f"{q['ic']:>9.3f}{q['pos']:>11.0f}{q['spread']:>10.2f}{q['t']:>10.1f}" if q else "     (계산 불가)"))

    opts = live_options()

    def run(**kw):
        return simulate(T, data, SHORT, LONG, STOP, **{**opts, **kw, "trade_from": i0})[0]

    dates = idx[i0 - 1:]
    runs = {"현재 전략 (추세 강한 순)": run()}
    for name in models:
        runs[f"{name}: 점수 높은 순으로 고름"] = run(score=scores[name], score_mode="order")
        runs[f"{name}: 추세+점수 상위 50%만"] = run(score=scores[name], score_mode="filter", score_in=0.5)
        runs[f"{name}: 점수만 (상위30% 진입/하위50% 청산)"] = run(score=scores[name], score_mode="only", score_in=0.7, score_out=0.5)
    base_close = np.array([data[c]["close"][i0 - 1] for c in codes])
    bench = [config.INITIAL_CASH * np.nanmean([data[c]["close"][i] / base_close[j] for j, c in enumerate(codes)]) for i in range(i0 - 1, T)]
    runs["단순 보유 (동일 비중)"] = [None] * 0 + bench

    print(f"\n[2] 매매 시험 (같은 날 현금으로 시작, 손절·추적 손절·갭 필터·비용 모두 동일)")
    series_all = {k: (v[i0 - 1:] if len(v) == T else v) for k, v in runs.items()}
    yearly = yearly_returns(dates, series_all)
    if (dates.year == dates[0].year).sum() == 1:   # 시작 기준일 하루뿐인 첫 해는 표에서 뺌
        yearly = [y_ for y_ in yearly if y_["year"] != dates[0].year]
    years = [y_["year"] for y_ in yearly]
    print(f"{'전략':<40}{'연%':>7}{'낙폭':>8}{'CAL':>6}" + "".join(f"{y_:>8}" for y_ in years))
    rows = []
    for name, vals in series_all.items():
        m = metrics(vals, dates)
        cal = round(m["cagr"] / abs(m["mdd"]), 2) if m["mdd"] else 0
        per_year = [next(r[name] for r in yearly if r["year"] == y_) for y_ in years]
        pad = 40 - sum(1 for ch in name if ord(ch) > 127)
        print(f"{name:<{pad}}{m['cagr']:>7}{m['mdd']:>8}{cal:>6}" + "".join(f"{p:>8}" for p in per_year))
        rows.append({"name": name, "cagr": m["cagr"], "mdd": m["mdd"], "cal": cal, **{str(y_): p for y_, p in zip(years, per_year)}})

    base = next(r for r in rows if r["name"].startswith("현재"))
    better = [r for r in rows if r["name"] not in (base["name"], "단순 보유 (동일 비중)") and r["cal"] > base["cal"] and r["cagr"] > base["cagr"]]
    good_model = any(q and q["t"] >= 2 and q["ic"] > 0 for q in qual.values())
    print("\n[자동 해석]")
    if better and good_model:
        print("- 예측력이 있어 보이고 현재 전략보다 성과가 좋은 조합이 있어요: " + ", ".join(r["name"] for r in better[:3]))
        print("- 그래도 시험 기간이 짧고 한 번의 결과라서, 바로 쓰지 말고 며칠~몇 주 더 지켜본 뒤 정하세요.")
    elif better:
        print("- 일부 조합의 성과가 좋아 보이지만 모델의 예측력(t값)이 약해서 우연일 가능성이 커요. 적용을 권하지 않아요.")
    else:
        print("- 이번 실험에서는 어떤 모델도 현재 전략보다 낫다고 말할 근거가 부족해요. 지금 전략을 유지하는 게 좋아요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "ml_experiment.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/ml_experiment.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
