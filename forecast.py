"""보유 종목의 가격 예측과 채점 (5분 뒤 / 1시간 뒤 / 다음 거래일 종가).

- 예측 방법은 일부러 단순하게 했어요: "최근 흐름(평균 변화율)이 절반쯤 이어진다"고 가정하고, 최근 흔들림 폭(±1σ)을 예상 범위로 삼아요.
  (머신러닝으로 종목 선택을 실험했을 때 예측력이 없었으므로, 이 예측도 '맞히는 능력'이 아니라 '얼마나 맞는지 기록하고 확인하는 용도'예요.)
- 채점 기준 3가지: ① 방향 적중(오를지 내릴지) ② 범위 적중(예상 범위 안에 들어왔는지) ③ 오차율(예측가와 실제가의 차이 %)
  + 비교용으로 '변동 없음'이라고 찍었을 때의 오차도 함께 기록해요. 예측 오차가 이보다 작아야 의미가 있어요.
- 5분·1시간 예측은 장중 감시(monitor.py)가, 하루 단위는 16:00 점검(main.py)이 만들고 채점해요.
- 결과는 data/forecasts.json 에 쌓여요 (대시보드가 읽음)."""
import json
import math
from datetime import datetime, timedelta, time as dtime

import numpy as np

import config

SHRINK = 0.5          # 최근 흐름을 얼마나 이어갈지 (0.5 = 절반)
MIN_SD = 0.0005       # 예상 범위의 최소 폭 (0.05%)
DONE_KEEP = 300       # 화면에 보여줄 최근 채점 결과 보관 개수
# (이름, 몇 분 뒤, 시계열 몇 칸 뒤, 흐름을 볼 칸 수, 이 시각 이후에는 새 예측 안 함)
INTRADAY = (("5m", 5, 1, 12, dtime(15, 24)), ("1h", 60, 12, 24, dtime(14, 29)))


def _file():
    return config.DATA_DIR / "forecasts.json"


def load():
    st = {}
    if _file().exists():
        try:
            st = json.load(open(_file(), encoding="utf-8"))
        except Exception:
            st = {}
    st.setdefault("intraday", {"date": "", "series": {}})
    st.setdefault("open", [])
    st.setdefault("done", [])
    st.setdefault("stats", {})
    for h in ("5m", "1h", "1d"):
        st["stats"].setdefault(h, {})
    return st


def save(st, now=None):
    config.DATA_DIR.mkdir(exist_ok=True)
    st["updated"] = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    st["done"] = st["done"][-DONE_KEEP:]
    with open(_file(), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


def predict(series, steps, lookback):
    """series: 최근 가격들(마지막이 현재가), steps: 몇 칸 뒤를 예측할지. 데이터가 부족하면 None"""
    a = np.asarray(series[-(lookback + 1):], dtype=float)
    if len(a) < 4 or (a <= 0).any():
        return None
    r = np.diff(np.log(a))
    mu = float(r.mean()) * SHRINK * steps
    sd = max(float(r.std(ddof=1)), MIN_SD) * math.sqrt(steps)
    base = float(a[-1])
    return {"pred": base * math.exp(mu), "lo": base * math.exp(mu - sd), "hi": base * math.exp(mu + sd)}


def grade(base, pred, lo, hi, actual):
    """한 건 채점: 방향·범위 적중 여부와 오차율(%)"""
    up_pred, up_real = pred > base, actual > base
    flat = abs(pred / base - 1) < 1e-6 or abs(actual / base - 1) < 1e-9
    return {
        "dir_ok": None if flat else (up_pred == up_real),
        "in_band": bool(lo <= actual <= hi),
        "err": abs(actual / pred - 1) * 100,
        "base_err": abs(actual / base - 1) * 100,
    }


def _add_stat(st, h, code, name, g):
    s = st["stats"][h].setdefault(code, {"name": name, "n": 0, "dn": 0, "dh": 0, "bh": 0, "ae": 0.0, "be": 0.0})
    s["name"] = name
    s["n"] += 1
    if g["dir_ok"] is not None:
        s["dn"] += 1
        s["dh"] += int(g["dir_ok"])
    s["bh"] += int(g["in_band"])
    s["ae"] = round(s["ae"] + g["err"], 4)
    s["be"] = round(s["be"] + g["base_err"], 4)


def _finish(st, rec, actual, now_text):
    g = grade(rec["base"], rec["pred"], rec["lo"], rec["hi"], actual)
    _add_stat(st, rec["h"], rec["code"], rec["name"], g)
    st["done"].append({
        "code": rec["code"], "name": rec["name"], "h": rec["h"], "made": rec["made"], "done": now_text,
        "base": round(rec["base"], 2), "pred": round(rec["pred"], 2), "actual": round(actual, 2),
        "dir_ok": g["dir_ok"], "in_band": g["in_band"], "err": round(g["err"], 3), "base_err": round(g["base_err"], 3),
    })


def _new(code, name, qty, h, made, due, base, pr, **extra):
    rec = {"code": code, "name": name, "qty": qty, "h": h, "made": made, "due": due, "base": round(base, 2),
           "pred": round(pr["pred"], 2), "lo": round(pr["lo"], 2), "hi": round(pr["hi"], 2)}
    rec.update(extra)
    return rec


def tick(positions, quotes, now):
    """장중 5분마다 호출: 현재가 기록 -> 기한이 된 예측 채점 -> 새 예측. 대시보드에 올릴 요약을 돌려줍니다."""
    st = load()
    day = now.strftime("%Y-%m-%d")
    if st["intraday"].get("date") != day:
        st["intraday"] = {"date": day, "series": {}}
    st["open"] = [r for r in st["open"] if r["h"] == "1d" or r["made"][:10] == day]   # 어제 남은 분 정리
    series = st["intraday"]["series"]
    for code in positions:
        if code in quotes:
            series[code] = (series.get(code, []) + [round(float(quotes[code]), 2)])[-150:]

    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    keep = []
    for r in st["open"]:
        if r["h"] != "1d":
            due = datetime.strptime(r["due"], "%Y-%m-%d %H:%M:%S")
            if now >= due - timedelta(seconds=20):
                q = quotes.get(r["code"])
                if q is not None:
                    _finish(st, r, float(q), now_text)
                    continue
                if now > due + timedelta(minutes=30):
                    continue   # 시세를 못 받아 채점하지 못한 건 버림
        keep.append(r)
    st["open"] = keep

    for code, p in positions.items():
        if code not in quotes or len(series.get(code, [])) < 6:
            continue
        base = float(quotes[code])
        for h, mins, steps, look, cutoff in INTRADAY:
            if now.time() > cutoff or any(r["code"] == code and r["h"] == h for r in st["open"]):
                continue
            pr = predict(series[code], steps, look)
            if pr:
                st["open"].append(_new(code, p["name"], p["qty"], h, now_text, (now + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S"), base, pr))
    save(st, now)
    return payload(st, positions, now)


def payload(st, positions, now=None):
    """대시보드(live.json)에 같이 올릴 요약: 보유 종목의 진행 중 예측 + 누적 통계 + 최근 채점"""
    held = set(positions)
    return {"updated": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
            "open": [r for r in st["open"] if r["code"] in held], "stats": st["stats"], "done": st["done"][-20:]}


def backtest_1d(closes_by_code, days=250, lookback=10):
    """같은 예측 방식을 과거 일봉에 적용해 본 결과 (하루 단위는 데이터가 많아서 바로 확인할 수 있어요)"""
    n = dn = dh = bh = 0
    ae = be = 0.0
    for closes in closes_by_code.values():
        c = np.asarray(closes, dtype=float)
        for i in range(max(lookback + 1, len(c) - 1 - days), len(c) - 1):
            pr = predict(c[:i + 1], 1, lookback)
            if not pr or c[i + 1] <= 0:
                continue
            g = grade(float(c[i]), pr["pred"], pr["lo"], pr["hi"], float(c[i + 1]))
            n += 1
            dn += g["dir_ok"] is not None
            dh += bool(g["dir_ok"])
            bh += g["in_band"]
            ae += g["err"]
            be += g["base_err"]
    return {"n": n, "dn": dn, "dh": dh, "bh": bh, "ae": round(ae, 3), "be": round(be, 3), "days": days} if n else None


def daily_update(positions, frames, trades):
    """16:00 점검 때 호출: 지난 하루 단위 예측 채점 -> 보유 종목의 다음 거래일 종가 예측 -> 과거 시뮬레이션"""
    import pandas as pd
    st = load()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    final = now.time() >= dtime(15, 40)
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")

    keep = []
    for r in st["open"]:
        if r["h"] == "1d" and r["code"] in frames:
            rows = frames[r["code"]]
            rows = rows[rows.index > pd.Timestamp(r["bdate"])]
            if not rows.empty:
                bar_day = rows.index[0].strftime("%Y-%m-%d")
                if bar_day < today or final:   # 장중의 미완성 종가로는 채점하지 않음
                    _finish(st, r, float(rows["Close"].iloc[0]), now_text)
                    continue
        keep.append(r)
    st["open"] = keep

    for code, p in positions.items():
        df = frames.get(code)
        if df is None or len(df) < 15:
            continue
        bdate = df.index[-1].strftime("%Y-%m-%d")
        if any(r["code"] == code and r["h"] == "1d" and r["bdate"] == bdate for r in st["open"]):
            continue
        pr = predict(df["Close"].dropna().to_numpy(), 1, 10)
        if pr:
            st["open"].append(_new(code, p["name"], p["qty"], "1d", now_text, "다음 거래일 종가", float(df["Close"].iloc[-1]), pr, bdate=bdate))

    codes = {t["code"] for t in trades} | set(positions)
    st["bt1d"] = backtest_1d({c: frames[c]["Close"].dropna().to_numpy() for c in codes if c in frames})
    if final:
        st["intraday"] = {"date": "", "series": {}}   # 장이 끝났으니 오늘의 5분 시세 기록은 비움
    save(st, now)
    return st
