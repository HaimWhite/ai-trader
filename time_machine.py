"""타임머신: '지금과 비슷했던 과거 100번'을 찾아서 그때 샀다면 얼마나 올랐는지 보고, 예상 수익률을 적어줍니다.
  python time_machine.py                    오늘 상승 추세인 종목 + 보유 종목
  python time_machine.py --codes=005930,NVDA   원하는 종목만      --all  30종목 전부      --n=100  비슷한 과거 횟수
① 과거 타임머신: 30종목의 모든 날 중 '지금 이 종목의 상태(최근 5·20·60일 등락, 20일선·120일선 위치, 고점 대비 하락, 변동성)'와
   가장 비슷했던 날 n(100)개를 골라요. 같은 종목의 비슷한 날이 며칠 연속이면 하나로 쳐요(10거래일 간격).
   그날 다음 날 시가에 샀다면 20·30·60·90·120거래일 뒤에 얼마였는지의 분포(중앙값·하위10%·상위10%·오른 비율)를 보여줘요.
② 미래 시뮬레이션: 그 종목의 최근 2년 일별 등락을 무작위로 이어 붙여 60거래일 미래를 1000번 만들어요(과거의 상승 추세는 빼고 변동성만 씀).
   60일 뒤 범위와, 중간에 손절선(-7%)에 닿을 확률을 보여줘요.
※ 과거 통계일 뿐 앞으로의 보장이 아니고, 수수료·세금은 빼고 계산했어요. 예상 수익률의 숫자는 코드가 계산하고, Ollama 는 그 숫자를 쉬운 말로만 풀어줘요."""
import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import config
import llm

H = (20, 30, 60, 90, 120)   # 몇 거래일 뒤를 볼지
BASE_H = 60                  # 손절 시뮬레이션·+10% 닿음 기준 기간
SPACING = 10
MC_PATHS = 1000


def build_table(frames):
    """모든 종목·모든 날의 특징과 미래 수익률"""
    rows = []
    for code, df in frames.items():
        if len(df) < config.LONG_MA + H[-1] + 5:
            continue
        c, o = df["Close"].astype(float), df["Open"].astype(float)
        f = pd.DataFrame(index=df.index)
        f["code"] = code
        f["r5"], f["r20"], f["r60"] = (c / c.shift(5) - 1) * 100, (c / c.shift(20) - 1) * 100, (c / c.shift(60) - 1) * 100
        ma20, ma120 = c.rolling(config.SHORT_MA).mean(), c.rolling(config.LONG_MA).mean()
        f["vs20"], f["m20_120"] = (c / ma20 - 1) * 100, (ma20 / ma120 - 1) * 100
        f["dd120"] = (c / c.rolling(120).max() - 1) * 100
        f["vol20"] = c.pct_change().rolling(20).std() * 100
        entry = o.shift(-1)
        for h in H:
            f[f"f{h}"] = (c.shift(-1 - h) / entry - 1) * 100
        f["hit10"] = (c[::-1].rolling(BASE_H).max()[::-1].shift(-1) / entry - 1) * 100   # 이후 60일 중 최고 종가 수익률
        f["pos"] = np.arange(len(f))
        rows.append(f)
    return pd.concat(rows)


FEATS = ["r5", "r20", "r60", "vs20", "m20_120", "dd120", "vol20"]


def analogs(table, code, n):
    now = table[table.code == code].iloc[-1]
    pool = table.dropna(subset=FEATS + [f"f{BASE_H}", "hit10"])   # 긴 기간(90·120일)은 아직 안 지난 최근 날이 빠져서 개수가 조금 줄 수 있어요
    sd = pool[FEATS].std().replace(0, 1)
    dist = (((pool[FEATS] - now[FEATS]) / sd) ** 2).sum(axis=1) ** 0.5
    order = dist.sort_values().index
    chosen, last_pos = [], {}
    # 날짜가 종목마다 겹치므로 번호(위치) 기반으로 순회
    d = dist.reset_index(drop=True)
    pool = pool.reset_index()
    for k in d.sort_values().index:
        r = pool.iloc[k]
        prev = last_pos.setdefault(r["code"], [])
        if any(abs(r["pos"] - p) < SPACING for p in prev):
            continue
        prev.append(r["pos"])
        chosen.append(k)
        if len(chosen) >= n:
            break
    sel = pool.iloc[chosen]
    out = {"n": int(len(sel))}
    for h in H:
        v = sel[f"f{h}"].dropna()
        if len(v) < 10:
            continue
        out[f"h{h}"] = {"n": int(len(v)), "mean": round(v.mean(), 2), "median": round(v.median(), 2), "p10": round(v.quantile(0.1), 2),
                        "p90": round(v.quantile(0.9), 2), "up": round((v > 0).mean() * 100, 1)}
    out["hit10"] = round((sel["hit10"] >= 10).mean() * 100, 1)
    out["avg_dist"] = round(float(d.iloc[chosen].mean()), 2)
    return out


def monte_carlo(df, paths=MC_PATHS, days=BASE_H, seed=7):
    c = df["Close"].astype(float).iloc[-500:]
    r = np.log(c / c.shift(1)).dropna().values
    r = r - r.mean()   # 과거 상승 추세는 빼고 변동성만 사용
    rng = np.random.default_rng(seed)
    sim = rng.choice(r, size=(paths, days)).cumsum(axis=1)
    path = np.exp(sim) - 1
    final = path[:, -1] * 100
    stop = config.STOP_LOSS_PCT * 100 if config.STOP_LOSS_PCT else -7
    return {"paths": paths, "median": round(float(np.median(final)), 2), "p10": round(float(np.percentile(final, 10)), 2),
            "p90": round(float(np.percentile(final, 90)), 2), "up": round(float((final > 0).mean() * 100), 1),
            "stop_hit": round(float((path.min(axis=1) * 100 <= stop).mean() * 100), 1)}


EXPLAIN_SYSTEM = (
    "당신은 주식 모의투자 비서입니다. JSON 의 숫자만 근거로 이 종목의 '예상 수익률'을 초보자가 이해하기 쉬운 한국어 존댓말 2문장으로 설명하세요.\n"
    "규칙: JSON 에 없는 숫자를 만들지 마세요. 사라/팔라는 권유나 확정적 예측은 하지 마세요. 과거 통계라는 점과 범위(하위 10%~상위 10%)를 함께 말하세요. 제목·목록 없이 문장만 쓰세요."
)


def explain(item):
    if not config.OLLAMA_TIMEMACHINE_EXPLAIN:
        return None
    src = json.dumps({"종목": item["name"], "과거 비슷했던 날": item["analog"], "미래 시뮬레이션": item["mc"]}, ensure_ascii=False)
    t = llm.chat(EXPLAIN_SYSTEM, src, timeout=config.OLLAMA_POLISH_TIMEOUT)
    if t and llm.numbers_subset(src, t) and 20 <= len(t) <= 400:
        return t
    return None


def targets(frames, codes=None, all_=False):
    if codes:
        return [c for c in codes if c in frames]
    if all_:
        return list(frames)
    held = []
    f = config.DATA_DIR / "account.json"
    if f.exists():
        held = list(json.load(open(f, encoding="utf-8")).get("positions", {}))
    up = []
    for code, df in frames.items():
        c = df["Close"].astype(float)
        if len(c) > config.LONG_MA and c.rolling(config.SHORT_MA).mean().iloc[-1] > c.rolling(config.LONG_MA).mean().iloc[-1]:
            up.append(code)
    return [c for c in dict.fromkeys(held + up) if c in frames]


def long_frames(frames):
    """'비슷했던 과거'를 찾기 위해 2016년부터의 긴 시세를 불러옵니다 (실패한 종목은 기존 시세 사용)."""
    import market
    out = {}
    for code in frames:
        try:
            df = market.load_prices(code, config.AI_HISTORY_START)
            out[code] = df if len(df) > len(frames[code]) else frames[code]
        except Exception:
            out[code] = frames[code]
    return out


def run(frames, codes=None, all_=False, n=100):
    table = build_table(frames)
    items, held = [], set()
    f = config.DATA_DIR / "account.json"
    if f.exists():
        held = set(json.load(open(f, encoding="utf-8")).get("positions", {}))
    for code in targets(frames, codes, all_):
        if code not in set(table.code):
            continue
        now = table[table.code == code].iloc[-1]
        item = {"code": code, "name": config.SYMBOLS.get(code, code), "held": code in held,
                "state": {k: round(float(now[k]), 2) for k in FEATS}, "analog": analogs(table, code, n), "mc": monte_carlo(frames[code])}
        items.append(item)
    budget_left = 8   # AI 한 줄 설명은 보유 종목 우선 최대 8개
    for it in sorted(items, key=lambda x: not x["held"]):
        if budget_left <= 0:
            break
        txt = explain(it)
        budget_left -= 1
        if txt:
            it["comment"] = txt
    items.sort(key=lambda x: -x["analog"]["h60"]["median"])
    out = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "n": n, "items": items,
           "note": "과거 통계이며 앞으로의 보장이 아닙니다. 수수료·세금은 빼고 계산했습니다."}
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(config.DATA_DIR / "time_machine.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    return out


def show(out):
    print(f"\n타임머신 ({out['updated']}) - 지금과 비슷했던 과거 {out['n']}번을 찾아 그때 샀다면:")
    print(f"{'종목':<12}{'보유':>4}{'20일 중앙':>9}{'60일 중앙':>9}{'60일 하위10%':>12}{'상위10%':>9}{'오른 비율':>9}{'+10%닿음':>9}{'시뮬 손절확률':>13}")
    for it in out["items"]:
        a, m = it["analog"], it["mc"]
        pad = it["name"] + " " * max(0, 12 - len(it["name"]) - sum(1 for ch in it["name"] if ord(ch) > 127))
        print(f"{pad}{'O' if it['held'] else '':>4}{a['h20']['median']:>8.1f}%{a['h60']['median']:>8.1f}%{a['h60']['p10']:>11.1f}%{a['h60']['p90']:>8.1f}%{a['h60']['up']:>8.0f}%{a['hit10']:>8.0f}%{m['stop_hit']:>12.0f}%")
    for it in out["items"]:
        if it.get("comment"):
            print(f"\n[{it['name']}] {it['comment']}")
    print("\n" + out["note"])


def main():
    codes, all_, n = None, "--all" in sys.argv, 100
    for a in sys.argv[1:]:
        if a.startswith("--codes="):
            codes = a.split("=", 1)[1].split(",")
        elif a.startswith("--n="):
            n = int(a.split("=", 1)[1])
    import market
    frames = {}
    for code in config.SYMBOLS:
        try:
            frames[code] = market.load_prices(code, config.PRICE_HISTORY_START)
        except Exception as e:
            print(f"[{config.SYMBOLS[code]}] 시세 실패(건너뜀): {str(e)[:50]}")
    show(run(frames, codes, all_, n))


if __name__ == "__main__":
    main()
