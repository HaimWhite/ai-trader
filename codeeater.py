"""코드이터 (주식 전략 자동 강화): 매주 금요일, 깃허브를 돌아다니며 전략 아이디어를 모으고 → 백테스트로 시험해서 → 확실히 좋아졌을 때만 V 를 올립니다.
  python codeeater.py              이번 주 강화 실행 (평소엔 작업 스케줄러가 금요일 17:30 에 실행)
  python codeeater.py --status     현재 버전과 역대 버전 성적 보기
  python codeeater.py --no-github  깃허브·Ollama 없이 내 PC 안에서만 변형을 시험
  python codeeater.py --fresh      기록을 지우고 처음부터 (V1 부터 다시)
● 코드이터의 '두뇌' = 전략 설정 한 벌(이동평균 기간, 손절·추적손절, RSI·돌파·모멘텀·변동성 진입 필터). 이것이 V1, V2, … 로 진화해요.
● 새 버전은 (1) 전체 기간 '연수익÷낙폭'이 5% 이상 좋아지고 (2) 최근 3년도 나빠지지 않고 (3) 거래 수가 너무 줄지 않을 때만 통과해요. 시험을 너무 많이 하면 우연히 좋아 보이는 것도 나와서 한 주에 후보 수를 제한해요.
● 본 전략(실제 가상 매매)에는 절대 자동 적용되지 않아요. 좋은 버전은 하임님이 보고 정해요."""
import json
import random
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import backtest
import config
import github_scout
import llm
import notify
import status

STATE = config.DATA_DIR / "codeeater.json"
RECENT_DAYS = 756
MIN_GAIN = 0.05
MAX_CANDIDATES = 40
GRID = {"short": [10, 15, 20, 30], "long": [60, 90, 120, 150], "stop": [-0.05, -0.07, -0.10], "trail": [0.15, 0.20, 0.25, 0.30],
        "rsi_max": [None, 65, 70, 75, 80], "breakout_n": [None, 20, 60, 120], "mom_min": [None, 0.0, 0.05, 0.10],
        "vol_max": [None, 0.03, 0.04, 0.05], "slope_up": [False, True]}
ALIAS = {"short_ma": "short", "long_ma": "long"}
MA_LIST = sorted(set(GRID["short"]) | set(GRID["long"]) | {config.SHORT_MA, config.LONG_MA})
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
def build_context():
    import market
    frames = {}
    for code in config.SYMBOLS:
        try:
            frames[code] = market.load_prices(code, config.AI_HISTORY_START)
        except Exception as e:
            print(f"[{config.SYMBOLS[code]}] 시세 실패(건너뜀): {str(e)[:50]}")
    idx, data = backtest.prepare(frames, MA_LIST)
    ind = {}
    for code, d in data.items():
        c = pd.Series(d["close"], index=idx)
        delta = c.diff()
        up, dn = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        ind[code] = {"rsi": (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy(), "mom": (c / c.shift(60) - 1).to_numpy(),
                     "vol": c.pct_change().rolling(20).std().to_numpy(), "close": d["close"],
                     "hi": {n: c.shift(1).rolling(n).max().to_numpy() for n in GRID["breakout_n"] if n}}
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
    res = {"cagr": float(a["cagr"]), "mdd": float(a["mdd"]), "cal": cal(a), "cagr_r": float(b["cagr"]), "mdd_r": float(b["mdd"]), "cal_r": cal(b), "trades": len(trades)}
    ctx["cache"][key_of(g)] = res
    return res


def passes(new, cur):
    return (new["cal"] >= cur["cal"] * (1 + MIN_GAIN) and new["cal_r"] >= cur["cal_r"] and new["trades"] >= 0.6 * cur["trades"]
            and new["cagr"] >= 0.9 * cur["cagr"])


def mutations(cur, rnd, k):
    """깃허브·Ollama 를 못 쓸 때(또는 후보를 채울 때) 현재 버전을 한두 군데 바꿔 본 변형들"""
    out, seen = [], set()
    keys = list(GRID)
    for _ in range(k * 6):
        if len(out) >= k:
            break
        g = dict(cur)
        for key in rnd.sample(keys, rnd.choice([1, 2])):
            g[key] = rnd.choice(GRID[key])
        if valid(g) and g != cur and key_of(g) not in seen:
            seen.add(key_of(g))
            out.append(g)
    return out


# ---------- 기록 ----------
def read_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
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
    return out


def improvement_lines(st, new_metrics_by_v, cur_v):
    lines = []
    for v in st["versions"][:-1]:
        old = new_metrics_by_v[v["v"]]
        if old["cal"] > 0:
            lines.append(f"V{v['v']}보다 {(new_metrics_by_v[cur_v]['cal'] / old['cal'] - 1) * 100:+.0f}%")
    return lines


def run(args):
    rnd = random.Random(datetime.now().strftime("%Y%V"))
    st = {"versions": [], "runs": [], "ideas": [], "seen": []} if "--fresh" in args else read_state()
    print("시세와 시험 환경을 준비하는 중...")
    ctx = build_context()
    today = datetime.now().strftime("%Y-%m-%d")
    first = not st["versions"]
    if first:
        g = base_genome()
        st["versions"].append({"v": 1, "genome": g, "born": today, "source": "기준 (지금 쓰는 본 전략과 같은 설정)", "idea": ""})
    cur = st["versions"][-1]
    cur_m = evaluate(cur["genome"], ctx)
    cands = []   # (genome, source, idea)
    if "--no-github" not in args:
        try:
            repos = github_scout.pick_repos(st["seen"], n=4, rnd=rnd)
        except Exception as e:
            repos = []
            print("깃허브 탐색 실패(건너뜀):", str(e)[:60])
        for r in repos:
            st["seen"].append(r["full"])
            try:
                ideas = github_scout.extract_ideas(github_scout.readme(r["full"]), clamp, model=getattr(config, "CODEEATER_MODEL", None))
            except Exception as e:
                print(f"  {r['full']} 읽기 실패: {str(e)[:50]}")
                continue
            print(f"  {r['full']} (★{r['stars']}): 아이디어 {len(ideas)}개")
            st["ideas"].append({"date": today, "repo": r["full"], "stars": r["stars"], "found": [i["summary"] for i in ideas], "tested": 0})
            for it in ideas:
                g = {**cur["genome"], **it["params"]}
                if valid(g):
                    cands.append((g, f"깃허브 {r['full']} (★{r['stars']})", it["summary"]))
    n_git = len(cands)
    for g in mutations(cur["genome"], rnd, max(0, MAX_CANDIDATES - n_git)):
        cands.append((g, "스스로 변형 시험", ""))
    cands = cands[:MAX_CANDIDATES]
    print(f"현재 V{cur['v']} ({describe(cur['genome'])}): 연 {cur_m['cagr']}% / 낙폭 {cur_m['mdd']}% / 연수익÷낙폭 {cur_m['cal']}")
    print(f"후보 {len(cands)}개 시험 중 (깃허브에서 배운 것 {n_git}개)...")
    best, tried = None, 0
    for g, src, idea in cands:
        m = evaluate(g, ctx)
        tried += 1
        if "깃허브" in src:
            for e in reversed(st["ideas"]):
                if src.startswith("깃허브 " + e["repo"]):
                    e["tested"] += 1
                    break
        if passes(m, cur_m) and (best is None or m["cal"] > best[1]["cal"]):
            best = (g, m, src, idea)
    promoted = best is not None
    if promoted:
        g, m, src, idea = best
        st["versions"].append({"v": cur["v"] + 1, "genome": g, "born": today, "source": src, "idea": idea or diff_text(cur["genome"], g)})
    cur_v = st["versions"][-1]["v"]
    mets = {v["v"]: evaluate(v["genome"], ctx) for v in st["versions"]}
    for v in st["versions"]:
        v["metrics"] = mets[v["v"]]
        v["describe"] = describe(v["genome"])
    st["runs"].append({"date": today, "tried": tried, "from_github": n_git, "promoted": promoted, "version": cur_v})
    st["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    st["curves"] = curves(st, ctx)
    write_state(st)
    status.beat("codeeater", True, f"V{cur_v}, 후보 {tried}개 시험")
    return st, promoted, tried, n_git, mets


def message(st, promoted, tried, n_git, mets):
    cur = st["versions"][-1]
    m = mets[cur["v"]]
    if len(st["versions"]) == 1:
        return (f"하임님, 코드이터를 처음 시작했어요. 지금 기준은 **V1** (본 전략과 같은 설정)이에요. 이번 주 후보 {tried}개(깃허브에서 배운 것 {n_git}개)를 시험했지만 V1보다 확실히 좋은 건 없었어요. "
                f"매주 금요일에 다시 찾아볼게요.")
    if not promoted:
        return f"하임님, 코드이터 이번 주 강화 결과예요. 후보 {tried}개(깃허브에서 배운 것 {n_git}개)를 시험했지만 확실히 좋아진 게 없어서 **V{cur['v']}** 그대로 유지합니다."
    imp = improvement_lines(st, mets, cur["v"])
    return (f"하임님, 코드이터가 **V{cur['v']}**로 올라갔어요! 역대 버전과 비교하면 " + ", ".join(imp) + " 더 좋아요 (연수익÷낙폭 기준, 같은 과거 데이터로 다시 계산).\n"
            f"- 이번에 바뀐 점: {cur['idea']}\n- 배운 곳: {cur['source']}\n- 성적: 연 {m['cagr']}% · 최대 낙폭 {m['mdd']}% · 최근 3년 연 {m['cagr_r']}%\n"
            f"- 설정: {describe(cur['genome'])}\n본 전략에는 자동으로 적용하지 않았어요. 적용하고 싶으시면 말씀해 주세요.")


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


def main():
    args = sys.argv[1:]
    if "--status" in args:
        return show_status()
    if not config.DATA_DIR.exists():
        config.DATA_DIR.mkdir()
    st, promoted, tried, n_git, mets = run(args)
    msg = message(st, promoted, tried, n_git, mets)
    print("\n" + msg.replace("**", ""))
    if "--no-dm" not in args:
        notify.send(msg, mention=promoted)


if __name__ == "__main__":
    main()
