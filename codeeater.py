"""코드이터 (주식 전략 자동 강화): 평일 09:00~16:30 에 깃허브를 돌아다니며 아이디어를 모아 시험하고 → 금요일 16:30 에 그 주의 최고 후보를 골라 확실히 좋아졌을 때만 V 를 올립니다.
  python codeeater.py --scout      탐색 한 번 (평일 09:00~16:30 사이 30분마다 작업 스케줄러가 실행. 후보 모으기·시험만, 버전은 안 바뀜)
  python codeeater.py --apply      고르기·적용 (금요일 16:30 에 작업 스케줄러가 실행. 버전 상승 + 디스코드 알림)
  python codeeater.py              탐색 + 적용을 한꺼번에 (수동 실행용)
  python codeeater.py --status     현재 버전과 역대 버전 성적, 이번 주 탐색 현황 보기
  python codeeater.py --no-github  깃허브·Ollama 없이 내 PC 안에서만 변형을 시험
  python codeeater.py --fresh      기록을 지우고 처음부터 (V1 부터 다시)
  --force                          시간·요일 제한 없이 탐색
● 코드이터의 '두뇌' = 전략 설정 한 벌(이동평균 기간, 손절·추적손절, RSI·돌파·모멘텀·변동성 진입 필터). 이것이 V1, V2, … 로 진화해요.
● 새 버전은 (1) 전체 기간 '연수익÷낙폭'이 기준 이상 좋아지고 (2) 최근 3년도 나빠지지 않고 (3) 거래 수가 너무 줄지 않을 때만 통과해요.
  시험을 많이 할수록 우연히 좋아 보이는 후보도 늘어나므로, 한 주 시험 수에 상한을 두고 시험 수가 늘수록 기준(기본 5%)을 더 높여요.
● 본 전략(실제 가상 매매)에는 절대 자동 적용되지 않아요. 좋은 버전은 하임님이 보고 정해요."""
import json
import math
import pickle
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

import backtest
import codeknow
import config
import github_scout
import llm
import notify
import status

STATE = config.DATA_DIR / "codeeater.json"
RECENT_DAYS = 756
MIN_GAIN = 0.05
MAX_CANDIDATES = 40
WEEK_TEST_CAP = 20000    # 한 주에 시험하는 후보 수 상한 (사실상 계속 탐색, 대신 시험이 많을수록 기준을 올려요)
SCOUT_START, SCOUT_END = (9, 0), (16, 30)
SCOUT_STOP = (16, 28)    # 탐색 반복은 여기서 멈춰서 16:30 적용과 겹치지 않게 해요
LOCK = Path(tempfile.gettempdir()) / "ai_trader_ce_scout.lock"
POOL_KEEP = 30
FRAME_CACHE = Path(tempfile.gettempdir()) / "ai_trader_ce_frames.pkl"   # 깃허브에 올라가지 않도록 임시 폴더에 저장
GRID = {"short": [10, 15, 20, 30], "long": [60, 90, 120, 150], "stop": [-0.05, -0.07, -0.10], "trail": [0.15, 0.20, 0.25, 0.30],
        "rsi_max": [None, 65, 70, 75, 80], "breakout_n": [None, 20, 60, 120], "mom_min": [None, 0.0, 0.05, 0.10],
        "vol_max": [None, 0.03, 0.04, 0.05], "slope_up": [False, True]}
# '넓은 범위' 탐색 방식이 켜졌을 때만 쓰는 추가 값
WIDE = {"short": [5, 7, 12, 25], "long": [40, 50, 75, 100, 200], "stop": [-0.03, -0.15], "trail": [0.10, 0.35, 0.40], "rsi_max": [60, 85],
        "breakout_n": [10, 40, 200], "mom_min": [-0.05, 0.15, 0.20], "vol_max": [0.02, 0.06]}


def _merge(a, b):
    vals = list(a) + [x for x in b if x not in a]
    return sorted((v for v in vals if v is not None), key=lambda v: float(v)) if not any(isinstance(v, bool) for v in vals) else vals


ALL = {k: ([None] if None in GRID[k] else []) + _merge([v for v in GRID[k] if v is not None], WIDE.get(k, [])) for k in GRID}
ALIAS = {"short_ma": "short", "long_ma": "long"}
MA_LIST = sorted(set(ALL["short"]) | set(ALL["long"]) | {config.SHORT_MA, config.LONG_MA})

# 코드이터가 '탐색하는 방식' 자체의 설정 (E1, E2, … 로 진화). E1 = 기존 방식
ENGINE_DEFAULT = {"genes": 2, "crossover": False, "local": False, "wide": False, "wf": False}
ENGINE_GRID = {"genes": [1, 2, 3], "crossover": [False, True], "local": [False, True], "wide": [False, True], "wf": [False, True]}
ENGINE_GAIN = 0.10       # 탐색 방식은 검증 구간 품질이 10% 이상 좋을 때만 교체
ENGINE_MIN_RECS = 40     # 탐색 방식을 평가하려면 최소 이만큼의 후보를 시험해 봐야 해요
START_I = max(MA_LIST) + 2


def base_genome():
    return {"short": config.SHORT_MA, "long": config.LONG_MA, "stop": config.STOP_LOSS_PCT, "trail": config.TRAIL_STOP_PCT or 0.20,
            "rsi_max": None, "breakout_n": None, "mom_min": None, "vol_max": None, "slope_up": False}


def describe(g):
    parts = [f"{g['short']}/{g['long']}일선", f"손절 {g['stop'] * 100:.0f}%", f"추적 {g['trail'] * 100:.0f}%"]
    if g.get("rsi_max"):
        parts.append(f"RSI≤{g['rsi_max']}")
    if g.get("breakout_n"):
        parts.append(f"{g['breakout_n']}일 고점 근처만 매수")
    if g.get("mom_min") is not None:
        parts.append(f"60일 수익률≥{g['mom_min'] * 100:.0f}%")
    if g.get("vol_max"):
        parts.append(f"변동성≤{g['vol_max'] * 100:.0f}%")
    if g.get("slope_up"):
        parts.append("장기선 우상향만")
    return " · ".join(parts)


def diff_text(old, new):
    ch = [f"{k}: {old.get(k)} → {new.get(k)}" for k in new if new.get(k) != old.get(k)]
    return ", ".join(ch) or "변화 없음"


def nearest(key, v):
    opts = [o for o in GRID[key] if o is not None and not isinstance(o, bool)]
    try:
        return min(opts, key=lambda o: abs(o - float(v)))
    except Exception:
        return None


def clamp(params):
    """외부(AI)가 준 값을 정해진 범위로 깎아서 안전한 변경 목록으로 만듭니다."""
    out = {}
    for k, v in params.items():
        k = ALIAS.get(k, k)
        if k not in GRID:
            continue
        if k == "slope_up":
            if v in (True, "true", "True", 1):
                out[k] = True
            continue
        if v is None:
            continue
        c = nearest(k, v)
        if c is not None:
            out[k] = c
    if "short" in out and "long" in out and out["short"] >= out["long"]:
        out.pop("short")
    return out


def valid(g):
    return g["short"] < g["long"]


# ---------- 시험 환경 ----------
def load_frames():
    """시세를 불러옵니다. 같은 날 같은 시간대(장중/장마감 후)에는 디스크에 저장해 둔 것을 다시 써서 탐색을 빠르게 해요.
    장 마감 전(16시 이전)에 받은 시세는 오늘의 미완성 봉을 잘라내서 쓰고, 저장 구분도 따로 둬요."""
    import market
    now = datetime.now()
    key = f"{now:%Y-%m-%d}-{'pm' if now.hour >= 16 else 'am'}"
    try:
        with open(FRAME_CACHE, "rb") as f:
            c = pickle.load(f)
        if c.get("key") == key and c.get("frames"):
            return c["frames"]
    except Exception:
        pass
    frames = {}
    for code in config.SYMBOLS:
        try:
            df = market.load_prices(code, config.AI_HISTORY_START)
            if now.hour < 16 and len(df) and str(df.index[-1].date()) == f"{now:%Y-%m-%d}":
                df = df.iloc[:-1]
            frames[code] = df
        except Exception as e:
            print(f"[{config.SYMBOLS[code]}] 시세 실패(건너뜀): {str(e)[:50]}")
    try:
        with open(FRAME_CACHE, "wb") as f:
            pickle.dump({"key": key, "frames": frames}, f)
    except Exception:
        pass
    return frames


def build_context():
    frames = load_frames()
    idx, data = backtest.prepare(frames, MA_LIST)
    ind = {}
    for code, d in data.items():
        c = pd.Series(d["close"], index=idx)
        delta = c.diff()
        up, dn = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        ind[code] = {"rsi": (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy(), "mom": (c / c.shift(60) - 1).to_numpy(),
                     "vol": c.pct_change().rolling(20).std().to_numpy(), "close": d["close"],
                     "hi": {n: c.shift(1).rolling(n).max().to_numpy() for n in ALL["breakout_n"] if n}}
    return {"idx": idx, "data": data, "ind": ind, "n": len(idx), "cache": {}}


def make_mask(g, ctx):
    n, masks = ctx["n"], {}
    for code, I in ctx["ind"].items():
        m = np.ones(n, dtype=bool)
        if g.get("rsi_max"):
            m &= I["rsi"] <= g["rsi_max"]
        if g.get("breakout_n"):
            m &= I["close"] >= 0.97 * I["hi"][g["breakout_n"]]
        if g.get("mom_min") is not None:
            m &= I["mom"] >= g["mom_min"]
        if g.get("vol_max"):
            m &= I["vol"] <= g["vol_max"]
        if g.get("slope_up"):
            ma = ctx["data"][code]["ma"][g["long"]]
            s = np.full(n, False)
            s[20:] = ma[20:] > ma[:-20]
            m &= s
        masks[code] = np.nan_to_num(m, nan=False).astype(bool) if m.dtype != bool else m
    return masks


def key_of(g):
    return json.dumps(g, sort_keys=True)


def ekey(o):
    return json.dumps(o, sort_keys=True)


def clamp_engine(p):
    """외부(AI)가 준 탐색 방식 옵션을 허용된 값으로만 깎아요."""
    out = {}
    for k, v in (p or {}).items():
        if k not in ENGINE_GRID:
            continue
        if k == "genes":
            try:
                out[k] = min(ENGINE_GRID[k], key=lambda o: abs(o - float(v)))
            except Exception:
                pass
        elif v in (True, "true", "True", 1):
            out[k] = True
    return out


def describe_engine(o):
    parts = [f"한 번에 {o['genes']}곳 변경"]
    for k, t in (("crossover", "좋은 후보 섞기"), ("local", "좋은 후보 주변 탐색"), ("wide", "넓은 값 범위"), ("wf", "뒤 30% 구간 검증")):
        if o.get(k):
            parts.append(t)
    return " · ".join(parts)


def evaluate(g, ctx, since_i=None):
    """전략 설정 한 벌을 같은 조건(같은 시작일·수수료)으로 백테스트해서 성적을 돌려줍니다."""
    if since_i is None and key_of(g) in ctx["cache"]:
        return ctx["cache"][key_of(g)]
    opts = backtest.live_options()
    opts.update(longs=None, long_rule="all", trail=g["trail"])
    start = START_I if since_i is None else since_i
    curve, trades = backtest.simulate(ctx["n"], ctx["data"], g["short"], g["long"], g["stop"], trade_from=start, entry_mask=make_mask(g, ctx), **opts)
    idx = ctx["idx"]
    if since_i is not None:
        return curve
    a = backtest.metrics(curve[START_I:], idx[START_I:])
    r0 = max(START_I, ctx["n"] - RECENT_DAYS)
    b = backtest.metrics(curve[r0:], idx[r0:])
    cal = lambda m: round(float(m["cagr"] / abs(m["mdd"])), 3) if m["mdd"] else 0.0
    sp = START_I + int(0.7 * (ctx["n"] - START_I))   # 앞 70% 로 고르고 뒤 30% 로 확인하는 경계
    tr, ho = backtest.metrics(curve[START_I:sp], idx[START_I:sp]), backtest.metrics(curve[sp:], idx[sp:])
    res = {"cal_tr": cal(tr), "cal_ho": cal(ho), "cagr": float(a["cagr"]), "mdd": float(a["mdd"]), "cal": cal(a), "cagr_r": float(b["cagr"]), "mdd_r": float(b["mdd"]), "cal_r": cal(b), "trades": len(trades)}
    ctx["cache"][key_of(g)] = res
    return res


def passes(new, cur):
    return (new["cal"] >= cur["cal"] * (1 + MIN_GAIN) and new["cal_r"] >= cur["cal_r"] and new["trades"] >= 0.6 * cur["trades"]
            and new["cagr"] >= 0.9 * cur["cagr"])


def neighbors(g, grid, rnd):
    """좋은 후보의 이웃: 설정 하나를 값 목록에서 한 칸 옆 값으로"""
    out = []
    for key in grid:
        vals = grid[key]
        if g.get(key) in vals and len(vals) > 1:
            i = vals.index(g[key])
            for j in (i - 1, i + 1):
                if 0 <= j < len(vals):
                    out.append({**g, key: vals[j]})
    rnd.shuffle(out)
    return out


def gen_candidates(cur, pool_cands, opts, rnd, k):
    """탐색 방식(opts)에 따라 후보를 만들어요: 변형 / 좋은 후보 섞기 / 좋은 후보 주변 탐색"""
    grid = ALL if opts.get("wide") else GRID
    keys = list(grid)
    tops = [c["genome"] for c in pool_cands[:10]]
    n_cross = k // 3 if opts.get("crossover") and tops else 0
    n_local = k // 3 if opts.get("local") else 0
    n_mut = k - n_cross - n_local
    out, seen = [], {key_of(cur)}

    def add(g):
        if valid(g) and key_of(g) not in seen:
            seen.add(key_of(g))
            out.append(g)
    for _ in range(n_mut * 6):
        if len(out) >= n_mut:
            break
        g = dict(cur)
        for key in rnd.sample(keys, rnd.randint(1, opts.get("genes", 2))):
            g[key] = rnd.choice(grid[key])
        add(g)
    parents = [cur] + tops
    for _ in range(n_cross * 6):
        if len(out) >= n_mut + n_cross or len(parents) < 2:
            break
        a, b = rnd.sample(parents, 2)
        add({key: rnd.choice([a[key], b[key]]) for key in keys})
    bases = (tops[:3] or [cur])
    nb = [x for b in bases for x in neighbors(b, grid, rnd)]
    rnd.shuffle(nb)
    for g in nb:
        if len(out) >= k:
            break
        add(g)
    return out


# ---------- 탐색 방식 (코드이터 자신의 강화) ----------
def engine_state(st):
    e = st.setdefault("engine", {})
    if not e.get("versions"):
        e["versions"] = [{"e": 1, "opts": dict(ENGINE_DEFAULT), "born": datetime.now().strftime("%Y-%m-%d"), "source": "기준 (기존 탐색 방식)", "q": None}]
    e.setdefault("arms", {})
    e.setdefault("notes", [])
    return e


def arm_quality(arm):
    """탐색 방식의 품질 = 앞 70% 구간 성적이 좋은 후보 5개를 골랐을 때, 뒤 30% 구간에서의 연수익÷낙폭 평균 (모두 같은 방식으로 비교)"""
    recs = arm.get("recs", [])
    if len(recs) < ENGINE_MIN_RECS:
        return None
    top = sorted(recs, key=lambda r: -r[0])[:5]
    return round(sum(r[1] for r in top) / len(top), 3)


def trial_opts(e):
    """시험해 볼 탐색 방식들: 깃허브에서 배운 것 + 지금 방식에서 옵션 하나만 바꾼 것"""
    base = e["versions"][-1]["opts"]
    out = {}
    for k, vals in ENGINE_GRID.items():
        for v in vals:
            if v != base[k]:
                o = {**base, k: v}
                out[ekey(o)] = (o, "스스로 변형: " + k + "=" + str(v))
    for key, arm in e["arms"].items():
        if arm.get("from_idea"):
            out[key] = (arm["opts"], arm["source"])
    out.pop(ekey(base), None)
    return out


def pick_arm(e, rnd):
    base = e["versions"][-1]["opts"]
    bk = ekey(base)
    e["arms"].setdefault(bk, {"opts": base, "source": "지금 방식", "recs": []})
    if rnd.random() < 0.5:
        return bk
    tr = trial_opts(e)
    for key, (o, src) in tr.items():
        e["arms"].setdefault(key, {"opts": o, "source": src, "recs": []})
    # 시험이 가장 적은 방식부터 (깃허브에서 배운 것 우선)
    return min(tr, key=lambda k: (len(e["arms"][k]["recs"]), 0 if e["arms"][k].get("from_idea") else 1, rnd.random()))


def adopt_engine(st):
    """금요일: 탐색 방식 중 지금 방식보다 확실히 나은 것이 있으면 E 를 올려요. 알림용 글을 돌려줘요."""
    e = engine_state(st)
    base_v = e["versions"][-1]
    bk = ekey(base_v["opts"])
    base_q = arm_quality(e["arms"].get(bk, {}))
    best = None
    if base_q is not None:
        for k, arm in e["arms"].items():
            q = arm_quality(arm)
            if k == bk or q is None:
                continue
            ok = q >= base_q * (1 + ENGINE_GAIN) if base_q > 0 else q >= base_q + 0.2
            if ok and (best is None or q > best[1]):
                best = (k, q)
    text = None
    if best:
        k, q = best
        arm = e["arms"][k]
        pct = f"{(q / base_q - 1) * 100:+.0f}%" if base_q > 0 else f"{q - base_q:+.2f}"
        base_v["q"] = base_q
        e["versions"].append({"e": base_v["e"] + 1, "opts": arm["opts"], "born": datetime.now().strftime("%Y-%m-%d"), "source": arm["source"], "q": q, "vs_prev": pct})
        text = (f"탐색 방식도 **E{base_v['e'] + 1}**로 올라갔어요! ({describe_engine(arm['opts'])}) 이전 방식(E{base_v['e']})보다 검증 구간 품질 {pct} 좋아요 · 배운 곳: {arm['source']}")
        e["arms"] = {k: {"opts": arm["opts"], "source": arm["source"], "recs": arm["recs"][-200:]}}
    else:
        for arm in e["arms"].values():
            arm["recs"] = arm["recs"][-300:]
    e["last_check"] = {"date": datetime.now().strftime("%Y-%m-%d"), "base_q": base_q, "adopted": bool(best)}
    return text


# ---------- 기록 ----------
def read_state():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("versions"), list):   # 예전 업그레이드 도구가 남긴 다른 형식의 파일이면 버리고 새로 시작
            for k in ("runs", "ideas", "seen"):
                d.setdefault(k, [])
            return d
    except Exception:
        pass
    return {"versions": [], "runs": [], "ideas": [], "seen": []}


def write_state(st):
    config.DATA_DIR.mkdir(exist_ok=True)
    st["runs"], st["ideas"], st["seen"] = st["runs"][-52:], st["ideas"][-60:], st["seen"][-400:]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


def curves(st, ctx):
    """V1 이 태어난 날부터, 지금 버전과 V1 이 각각 했다면의 자산 곡선 (주 단위로 줄여서 대시보드용)"""
    since = pd.Timestamp(st["versions"][0]["born"])
    i0 = int(ctx["idx"].searchsorted(since))
    i0 = min(max(i0, START_I), ctx["n"] - 1)
    out = {}
    for name, v in (("current", st["versions"][-1]), ("v1", st["versions"][0])):
        cv = evaluate(v["genome"], ctx, since_i=i0)
        seg = [(str(ctx["idx"][i].date()), round(float(cv[i]))) for i in range(i0, ctx["n"])]
        out[name] = [x for k, x in enumerate(seg) if k % 5 == 0 or k == len(seg) - 1]
    # V1, V5, V10, V15 … (5의 배수) 버전들을 한 그래프에서 비교할 수 있게 각각의 곡선도 저장
    ms = {}
    for v in st["versions"]:
        if v["v"] == 1 or v["v"] % 5 == 0:
            cv = evaluate(v["genome"], ctx, since_i=i0)
            seg = [(str(ctx["idx"][i].date()), round(float(cv[i]))) for i in range(i0, ctx["n"])]
            ms["V%d" % v["v"]] = [x for k, x in enumerate(seg) if k % 5 == 0 or k == len(seg) - 1]
    out["ms"] = ms
    return out


def forward(st, ctx):
    """각 버전이 태어난 날 '이후'의 성적 (그 날짜 뒤의 데이터는 버전을 고를 때 못 본 것이라 진짜 검증이에요).
    V1(지금 본 전략과 같은 기준)과 같은 기간으로 비교해요."""
    out = []
    base = st["versions"][0]
    for v in st["versions"][1:]:
        i0 = int(ctx["idx"].searchsorted(pd.Timestamp(v["born"])))
        days = ctx["n"] - 1 - i0
        if days < 1:
            continue
        r = {}
        for name, g in (("v", v["genome"]), ("base", base["genome"])):
            cv = evaluate(g, ctx, since_i=i0)
            r[name] = round((float(cv[ctx["n"] - 1]) / float(cv[i0]) - 1) * 100, 2) if cv[i0] else 0.0
        out.append({"v": v["v"], "born": v["born"], "days": int(days), "ret": r["v"], "base": r["base"], "diff": round(r["v"] - r["base"], 2)})
    return out


def live_check(st, ctx, promoted):
    """금요일: ① V 가 올랐으면 본 전략 적용을 물어보고 ② 적용한 뒤 성적이 계속 나쁘면 되돌릴지 물어봐요 (둘 다 하임님이 답해야만 바뀌어요)"""
    import live_apply
    out = []
    cur = st["versions"][-1]
    ls = live_apply.read()
    if promoted:
        fw = ""
        try:
            lv = next((v for v in st["versions"] if v["v"] == ls["live_v"]), st["versions"][0])
            ml, mc = evaluate(lv["genome"], ctx), evaluate(cur["genome"], ctx)
            if ml["cal"] > 0:
                fw = f"- 같은 과거 데이터로 다시 계산하면 V{lv['v']}보다 연수익÷낙폭 {(mc['cal'] / ml['cal'] - 1) * 100:+.0f}% (연 {mc['cagr']:.0f}% · 낙폭 {mc['mdd']:.0f}%)"
        except Exception:
            pass
        t = live_apply.propose_apply(cur["v"], cur["genome"], fw)
        if t:
            out.append(t)
    if ls.get("prev") and ls.get("live_since"):
        try:
            i0 = int(ctx["idx"].searchsorted(pd.Timestamp(ls["live_since"])))
            days = ctx["n"] - 1 - i0
            lv = next(v for v in st["versions"] if v["v"] == ls["live_v"])
            if days >= live_apply.ROLLBACK_MIN_DAYS:
                r = []
                for g in (lv["genome"], ls["prev"]["genome"]):
                    cv = evaluate(g, ctx, since_i=i0)
                    r.append((float(cv[ctx["n"] - 1]) / float(cv[i0]) - 1) * 100)
                if r[0] - r[1] <= live_apply.ROLLBACK_GAP:
                    t = live_apply.propose_rollback(live_apply._text(ls["prev"]["genome"]), r[0], r[1], days)
                    if t:
                        out.append(t)
        except Exception as e:
            out.append("되돌리기 점검 오류(무시): " + str(e)[:50])
    return out


def scoreboard(st):
    """금요일 보고에 붙이는 한 장 요약"""
    cur = st["versions"][-1]
    e = (st.get("engine") or {}).get("versions") or []
    try:
        kn = codeknow.read()
        ms = kn.get("models") or []
        n = (kn.get("train") or {}).get("count", 0)
        m_txt = f"M{ms[-1]['m']}" if ms else "M없음"
    except Exception:
        n, m_txt = 0, "M?"
    lines = ["📋 이번 주 성적표",
             f"· 버전: V{cur['v']} · 탐색 방식 E{e[-1]['e'] if e else 1} · 두뇌 {m_txt}",
             f"· 학습 데이터 {n}/300개 ({min(100, n * 100 // 300)}%)"]
    p = st.get("runs") or []
    if p:
        lines.append(f"· 이번 주 시험 {p[-1].get('tried', 0)}개 (깃허브에서 배운 것 {p[-1].get('from_github', 0)}개)")
    fw = [f for f in st.get("forward", []) if f["v"] == cur["v"]]
    if fw:
        f = fw[0]
        lines.append(f"· V{cur['v']} 탄생({f['born'][5:]}) 뒤 {f['days']}거래일: {f['ret']:+.1f}% (V1은 {f['base']:+.1f}%)")
    else:
        lines.append(f"· V{cur['v']} 가 태어난 뒤 지난 거래일이 아직 없어요 (검증 데이터가 쌓이는 중)")
    return "\n".join(lines)


def improvement_lines(st, new_metrics_by_v, cur_v):
    lines = []
    for v in st["versions"][:-1]:
        old = new_metrics_by_v[v["v"]]
        if old["cal"] > 0:
            lines.append(f"V{v['v']}보다 {(new_metrics_by_v[cur_v]['cal'] / old['cal'] - 1) * 100:+.0f}%")
    return lines


def week_id():
    y, w, _ = datetime.now().isocalendar()
    return f"{y}-W{w:02d}"


def need_gain(tests):
    """이번 주 시험을 많이 했을수록 요구 개선폭을 높여요 (우연히 좋아 보이는 후보를 거르려고). 40개까지 5%, 400개 약 8.5%, 4,000개 약 12%, 최대 15%"""
    return min(0.15, MIN_GAIN * (1 + 0.7 * math.log10(max(1.0, tests / 40))))


def passes_at(new, cur, gain):
    return (new["cal"] >= cur["cal"] * (1 + gain) and new["cal_r"] >= cur["cal_r"] and new["trades"] >= 0.6 * cur["trades"]
            and new["cagr"] >= 0.9 * cur["cagr"])


def fresh_pool():
    return {"week": week_id(), "tests": 0, "rounds": 0, "tested": [], "cands": [], "last": ""}


def in_scout_window(now=None, end=None):
    now = now or datetime.now()
    hm = (now.hour, now.minute)
    return now.weekday() < 5 and SCOUT_START <= hm <= (end or SCOUT_END)


def ensure_v1(st, today):
    if not st["versions"]:
        st["versions"].append({"v": 1, "genome": base_genome(), "born": today, "source": "기준 (지금 쓰는 본 전략과 같은 설정)", "idea": ""})
        return True
    return False


def scout_engine_ideas(st, eng, rnd, today):
    """깃허브에서 '탐색 방식을 개선하는 글'을 한 곳 읽어요 (코드는 실행하지 않고, 정해진 옵션만 시험 후보로 등록)."""
    try:
        repos = github_scout.pick_repos(st["seen"], n=1, rnd=rnd, queries=github_scout.ENGINE_QUERIES)
    except Exception as e:
        github_scout.note_error("탐색방식 검색 실패: " + str(e))
        return
    base = eng["versions"][-1]["opts"]
    for r in repos:
        st["seen"].append(r["full"])
        try:
            ideas = github_scout.extract_engine_ideas(github_scout.readme(r["full"]), clamp_engine, model=getattr(config, "CODEEATER_MODEL", None))
        except Exception as e:
            github_scout.note_error(f"{r['full']} 읽기 실패: {e}")
            continue
        print(f"  [탐색 방식] {r['full']} (★{r['stars']}): 아이디어 {len(ideas)}개")
        st["ideas"].append({"date": today, "repo": r["full"], "stars": r["stars"], "kind": "engine", "found": [i["summary"] for i in ideas], "tested": 0})
        for it in ideas:
            if it["opts"]:
                o = {**base, **it["opts"]}
                if o != base:
                    eng["arms"].setdefault(ekey(o), {"opts": o, "source": f"깃허브 {r['full']} (★{r['stars']}): {it['summary']}", "recs": [], "from_idea": True})
            if it["human"] and it["human"] not in [n["text"] for n in eng["notes"]]:
                eng["notes"] = (eng["notes"] + [{"date": today, "repo": r["full"], "text": it["human"]}])[-15:]


def scout(st, ctx, args, repos_n=2, n_mut=10, gh=True):
    """탐색 한 번: 깃허브에서 아이디어를 읽고 + 스스로 변형을 만들어 시험하고, 쓸 만한 후보를 이번 주 후보 풀에 모아요 (버전은 안 바뀜)."""
    now = datetime.now()
    rnd = random.Random(f"{now:%Y%m%d%H%M%S}{time.time_ns() % 100000}")
    today = now.strftime("%Y-%m-%d")
    gh = gh and "--no-github" not in args   # 깃허브 호출 여유가 없는 회차는 PC 안에서 시험만 해요
    pool = st.get("pool")
    if not pool or pool.get("week") != week_id():
        pool = st["pool"] = fresh_pool()
    cur = st["versions"][-1]
    cur_m = evaluate(cur["genome"], ctx)
    eng = engine_state(st)
    if gh:
        scout_engine_ideas(st, eng, rnd, today)
    if gh:   # 자유 라이선스 코드를 읽어 지식 창고에 팁을 쌓아요 (읽기만 함)
        try:
            kn = codeknow.read()
            new_tips = codeknow.read_round(kn, rnd, model=getattr(config, "CODEEATER_MODEL", None))
            codeknow.write(kn)
            if new_tips:
                print(f"지식 창고에 새 팁 {new_tips}개 저장 (총 {len(kn['tips'])}개)")
        except Exception as e:
            github_scout.note_error("코드 읽기 오류: " + str(e))
    akey = pick_arm(eng, rnd)
    arm = eng["arms"][akey]
    cands = []
    n_git = 0
    if gh:
        try:
            repos = github_scout.pick_repos(st["seen"], n=repos_n, rnd=rnd)
        except Exception as e:
            repos = []
            print("깃허브 탐색 실패(건너뜀):", str(e)[:60])
            github_scout.note_error("탐색 실패: " + str(e))
        for r in repos:
            st["seen"].append(r["full"])
            try:
                ideas = github_scout.extract_ideas(github_scout.readme(r["full"]), clamp, model=getattr(config, "CODEEATER_MODEL", None))
            except Exception as e:
                print(f"  {r['full']} 읽기 실패: {str(e)[:50]}")
                github_scout.note_error(f"{r['full']} 읽기 실패: {e}")
                continue
            print(f"  {r['full']} (★{r['stars']}): 아이디어 {len(ideas)}개")
            st["ideas"].append({"date": today, "repo": r["full"], "stars": r["stars"], "found": [i["summary"] for i in ideas], "tested": 0})
            for it in ideas:
                g = {**cur["genome"], **it["params"]}
                if valid(g):
                    cands.append((g, f"깃허브 {r['full']} (★{r['stars']})", it["summary"]))
                    n_git += 1
    tried = 0
    for g in gen_candidates(cur["genome"], pool["cands"], arm["opts"], rnd, n_mut):
        cands.append((g, "스스로 변형 시험", "", akey))
    cands = [x if len(x) == 4 else (*x, None) for x in cands]
    print(f"이번 탐색 방식: E{eng['versions'][-1]['e']} 기준 {'(지금 방식)' if akey == ekey(eng['versions'][-1]['opts']) else '(새 방식 시험: ' + describe_engine(arm['opts']) + ')'}")
    for g, src, idea, ak in cands:
        if pool["tests"] >= WEEK_TEST_CAP:
            print("이번 주 시험 상한에 도달 — 더 시험하지 않아요")
            break
        k = key_of(g)
        if k in pool["tested"]:
            continue
        pool["tested"].append(k)
        pool["tests"] += 1
        tried += 1
        m = evaluate(g, ctx)
        if ak:
            eng["arms"][ak]["recs"].append([m["cal_tr"], m["cal_ho"]])
            eng["arms"][ak]["recs"] = eng["arms"][ak]["recs"][-400:]
        if src.startswith("깃허브 "):
            for e in reversed(st["ideas"]):
                if src.startswith("깃허브 " + e["repo"]):
                    e["tested"] += 1
                    break
        if rnd.random() < 0.3:   # 시험 기록의 일부를 학습용 문제·정답 쌍으로 쌓아요
            codeknow.record_trial(describe(cur["genome"]), cur_m["cal"], diff_text(cur["genome"], g), m, passes_at(m, cur_m, need_gain(pool["tests"])))
        wf_ok = (not arm["opts"].get("wf")) or (m["cal_tr"] >= cur_m["cal_tr"] and m["cal_ho"] >= cur_m["cal_ho"] * 0.95)   # '뒤 30% 구간 검증' 방식이면 두 구간 모두 확인
        if m["cal"] >= cur_m["cal"] and m["cal_r"] >= cur_m["cal_r"] * 0.95 and (wf_ok or src.startswith("깃허브 ")):   # 현재 이상인 것만 후보 풀에 보관 (최종 판단은 금요일)
            pool["cands"].append({"genome": g, "source": src, "idea": idea, "cal": m["cal"], "found": today})
    pool["cands"].sort(key=lambda c: -c["cal"])
    pool["cands"] = pool["cands"][:POOL_KEEP]
    pool["tested"] = pool["tested"][-WEEK_TEST_CAP:]
    pool["git_ideas"] = pool.get("git_ideas", 0) + n_git
    pool["rounds"] += 1
    pool["token"] = github_scout.has_token()
    stamp = datetime.now().strftime("%m-%d %H:%M")
    if github_scout.ERRORS:
        pool["errors"] = (pool.get("errors", []) + [f"{stamp} {e}" for e in github_scout.ERRORS])[-10:]
        github_scout.ERRORS.clear()
    pool["rounds_github_ok"] = pool.get("rounds_github_ok", 0) + (1 if n_git else 0)
    pool["last"] = now.strftime("%Y-%m-%d %H:%M")
    pool["cur_cal"] = cur_m["cal"]
    pool["need"] = round(need_gain(pool["tests"]) * 100, 1)
    pool["top"] = [{"cal": c["cal"], "source": c["source"], "idea": c["idea"] or diff_text(cur["genome"], c["genome"])} for c in pool["cands"][:3]]
    st["updated"] = pool["last"]
    write_state(st)
    status.beat("codeeater_scout", True, f"이번 주 {pool['tests']}개 시험, 후보 {len(pool['cands'])}개")
    print(f"탐색 {pool['rounds']}번째: 이번에 {tried}개 시험(깃허브에서 배운 것 {n_git}개), 이번 주 누적 {pool['tests']}개, 후보 풀 {len(pool['cands'])}개")
    return tried, n_git


def apply_week(st, ctx, args):
    """금요일: 이번 주 후보 풀에서 최고를 골라 기준을 넘으면 새 버전으로 올려요."""
    today = datetime.now().strftime("%Y-%m-%d")
    pool = st.get("pool") or fresh_pool()
    cur = st["versions"][-1]
    cur_m = evaluate(cur["genome"], ctx)
    gain = need_gain(pool.get("tests", 0))
    best = None
    for c in pool.get("cands", []):
        m = evaluate(c["genome"], ctx)   # 최신 시세로 다시 계산해서 확인
        if passes_at(m, cur_m, gain) and (best is None or m["cal"] > best[1]["cal"]):
            best = (c["genome"], m, c["source"], c["idea"])
    promoted = best is not None
    if promoted:
        g, m, src, idea = best
        st["versions"].append({"v": cur["v"] + 1, "genome": g, "born": today, "source": src, "idea": idea or diff_text(cur["genome"], g)})
    cur_v = st["versions"][-1]["v"]
    st["engine_msg"] = adopt_engine(st)
    try:   # 금요일: 두뇌 강화(모델) + 플러그인 초안 + 다음 키워드 + 학습 데이터 알림
        kn = codeknow.read()
        st["know_msgs"] = codeknow.weekly(kn, model=getattr(config, "CODEEATER_MODEL", None))
        codeknow.write(kn)
    except Exception as e:
        st["know_msgs"] = ["지식 창고 단계 오류: " + str(e)[:60]]
    mets = {v["v"]: evaluate(v["genome"], ctx) for v in st["versions"]}
    for v in st["versions"]:
        v["metrics"] = mets[v["v"]]
        v["describe"] = describe(v["genome"])
    tried, git_tested = pool.get("tests", 0), pool.get("git_ideas", 0)   # 이번 주 시험 수 / 그중 깃허브 아이디어로 만든 후보 수
    st["runs"].append({"date": today, "tried": tried, "from_github": git_tested, "promoted": promoted, "version": cur_v, "need": round(gain * 100, 1)})
    st["pool"] = fresh_pool()
    st["pool"]["week"] = "applied-" + week_id()   # 다음 월요일 탐색에서 새 풀로 시작
    st["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    st["curves"] = curves(st, ctx)
    st["forward"] = forward(st, ctx)
    write_state(st)
    status.beat("codeeater", True, f"V{cur_v}, 이번 주 {tried}개 시험")
    return promoted, tried, git_tested, mets, gain


def message(st, promoted, tried, n_git, mets, gain=MIN_GAIN):
    cur = st["versions"][-1]
    m = mets[cur["v"]]
    if not promoted:
        extra = f" 이번 주 시험이 많을수록 기준이 올라가서 이번엔 {gain * 100:.1f}% 이상 좋아져야 했어요." if tried else ""
        return (f"하임님, 코드이터 이번 주 강화 결과예요. 평일 동안 후보 {tried}개(깃허브에서 배운 것 {n_git}개)를 시험했지만 확실히 좋아진 게 없어서 **V{cur['v']}** 그대로 유지합니다."
                f"{extra} 다음 주 월요일부터 다시 찾아볼게요.")
    imp = improvement_lines(st, mets, cur["v"])
    return (f"하임님, 코드이터가 **V{cur['v']}**로 올라갔어요! 역대 버전과 비교하면 " + ", ".join(imp) + " 더 좋아요 (연수익÷낙폭 기준, 같은 과거 데이터로 다시 계산).\n"
            f"- 이번에 바뀐 점: {cur['idea']}\n- 배운 곳: {cur['source']}\n- 성적: 연 {m['cagr']}% · 최대 낙폭 {m['mdd']}% · 최근 3년 연 {m['cagr_r']}%\n"
            f"- 이번 주 시험 {tried}개 (기준 {gain * 100:.1f}% 이상 개선)\n- 설정: {describe(cur['genome'])}\n본 전략에는 하임님이 승인하실 때만 적용돼요 (아래 안내 참고).")


def show_status():
    st = read_state()
    if not st["versions"]:
        print("아직 기록이 없어요. python codeeater.py 를 한 번 실행하세요.")
        return
    cur = st["versions"][-1]
    print(f"코드이터 현재 버전: V{cur['v']} (마지막 실행 {st.get('updated', '?')})")
    for v in st["versions"]:
        m = v.get("metrics") or {}
        print(f"  V{v['v']} {v['born']}  연 {m.get('cagr', '?')}%  낙폭 {m.get('mdd', '?')}%  연수익÷낙폭 {m.get('cal', '?')}  | {v.get('describe', '')}")
    p = st.get("pool")
    if p and p.get("week") == week_id():
        print(f"이번 주 탐색: {p['rounds']}번, 시험 {p['tests']}개, 후보 {len(p['cands'])}개 (마지막 {p.get('last', '?')})")
    else:
        print("이번 주 탐색: 아직 없어요")


def push_data():
    """가상 계산 결과를 깃허브에 올려 대시보드에 보이게 해요 (창이 뜨지 않게)"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for cmd in (["git", "add", "data"], ["git", "commit", "-m", "codeeater"], ["git", "push"]):
        try:
            subprocess.run(cmd, cwd=str(config.BASE_DIR), capture_output=True, timeout=120, creationflags=flags)
        except Exception as e:
            print("깃 올리기 실패:", str(e)[:60])
            return


def set_low_priority():
    """탐색은 하루 종일 돌기 때문에 다른 작업(점검·감시)을 방해하지 않게 우선순위를 낮춰요 (윈도우)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)   # BELOW_NORMAL
    except Exception:
        pass


def touch_lock():
    try:
        LOCK.write_text(str(time.time()))
    except Exception:
        pass


def scout_busy():
    try:
        return time.time() - LOCK.stat().st_mtime < 150
    except Exception:
        return False


def wait_for_scout(max_sec=180):
    """16:30 적용은 탐색 반복이 끝나길 잠깐 기다려요."""
    t0 = time.time()
    while scout_busy() and time.time() - t0 < max_sec:
        time.sleep(10)


def scout_loop(st, ctx, args):
    """평일 09:00~16:28 쉬지 않고 계속 탐색해요. 깃허브 호출 여유가 있는 회차에는 깃허브도 읽고, 없는 회차에는 PC 안에서 후보 시험만 해요."""
    set_low_priority()
    last_push, rounds, last_gh = time.time(), 0, 0.0
    print("탐색 반복을 시작합니다 (16:28 까지 쉬지 않고 계속).")
    while in_scout_window(end=SCOUT_STOP):
        touch_lock()
        pool = st.get("pool") or {}
        if pool.get("week") == week_id() and pool.get("tests", 0) >= WEEK_TEST_CAP:
            time.sleep(300)
            continue
        # 깃허브는 토큰이 없으면 6분, 있으면 1분에 한 번만 (한 회차에 검색을 여러 번 써서 한도가 금방 차요)
        gh = (time.time() - last_gh >= (60 if github_scout.has_token() else 360)) and github_scout.budget_ok()
        if gh:
            last_gh = time.time()
        try:
            tried, _ = scout(st, ctx, args, n_mut=30, gh=gh)
        except Exception as e:
            print("탐색 회차 오류(계속):", str(e)[:80])
            github_scout.note_error("회차 오류: " + str(e))
            time.sleep(30)
            continue
        rounds += 1
        if time.time() - last_push > 3600:   # 한 시간에 한 번 깃허브에 올려 대시보드에 보이게 해요
            push_data()
            last_push = time.time()
        time.sleep(2 if tried else 60)   # 새로 시험할 후보가 없으면 잠깐 쉬었다가 다시 만들어요
    push_data()
    try:
        LOCK.unlink()
    except Exception:
        pass
    print(f"오늘 탐색을 마칩니다 (회차 {rounds}번).")


def main():
    args = sys.argv[1:]
    if sys.stdout is None or sys.stderr is None:   # pythonw(창 없음)로 실행되면 출력 대신 로그 파일에 기록
        log = open(config.BASE_DIR / "codeeater_log.txt", "a", encoding="utf-8")
        log.write(f"===== {datetime.now():%Y-%m-%d %H:%M} codeeater {' '.join(args)} =====\n")
        sys.stdout = sys.stderr = log
    if "--status" in args:
        return show_status()
    if not config.DATA_DIR.exists():
        config.DATA_DIR.mkdir()
    is_scout, is_apply = "--scout" in args, "--apply" in args
    llm._state["scout"] = is_scout   # 탐색은 점검·보고서가 Ollama 를 쓰는 동안 비켜 줘요
    if is_scout and "--force" not in args and not in_scout_window():
        print("탐색 시간(평일 09:00~16:30)이 아니라서 건너뜁니다. (--force 로 강제 실행)")
        return
    st = {"versions": [], "runs": [], "ideas": [], "seen": []} if "--fresh" in args else read_state()
    print("시세와 시험 환경을 준비하는 중...")
    ctx = build_context()
    today = datetime.now().strftime("%Y-%m-%d")
    ensure_v1(st, today)
    cur = st["versions"][-1]
    print(f"현재 V{cur['v']} ({describe(cur['genome'])})")
    if is_scout:
        if "--force" in args or "--once" in args:   # 한 회차만 (시험·수동용)
            scout(st, ctx, args, gh=github_scout.budget_ok())
            return
        scout_loop(st, ctx, args)
        return
    if is_apply:
        wait_for_scout()
        st = read_state()   # 탐색이 마지막으로 쓴 기록을 다시 읽어요
        ensure_v1(st, today)
    if not is_apply:   # 수동: 한 번 크게 탐색하고 바로 적용
        scout(st, ctx, args, repos_n=4, n_mut=30)
    promoted, tried, n_git, mets, gain = apply_week(st, ctx, args)
    msg = message(st, promoted, tried, n_git, mets, gain)
    if st.get("engine_msg"):
        msg += "\n\n" + st["engine_msg"]
    if st.get("know_msgs"):
        msg += "\n\n" + "\n".join("· " + t for t in st["know_msgs"])
    e = st.get("engine") or {}
    if e.get("versions") and not st.get("engine_msg"):
        msg += f"\n(탐색 방식 현재 E{e['versions'][-1]['e']}: {describe_engine(e['versions'][-1]['opts'])})"
    try:
        lc = live_check(st, ctx, promoted) if "--no-dm" not in args else []
        if lc:
            msg += "\n\n" + "\n".join("🔗 " + t for t in lc)
    except Exception as e:
        print("본 전략 연결 단계 오류(무시):", str(e)[:80])
    try:
        ls = __import__("live_apply").read()
        msg += f"\n\n(지금 본 전략: V{ls['live_v']})"
    except Exception:
        pass
    try:
        msg += "\n\n" + scoreboard(st)
    except Exception as e:
        print("성적표 오류(무시):", str(e)[:60])
    print("\n" + msg.replace("**", ""))
    try:   # 승인·설치된 도구가 있으면 격리해서 실행하고, 결과를 글로만 덧붙여요
        import plugins
        outs = plugins.run_all(msg)
        if outs:
            msg += "\n\n🧰 설치된 도구 결과\n" + "\n".join(f"· {t}: {o}" for t, o in outs)
    except Exception as e:
        print("도구 실행 오류(무시):", str(e)[:60])
    if "--no-dm" not in args:
        notify.send(msg, mention=promoted)


if __name__ == "__main__":
    main()
