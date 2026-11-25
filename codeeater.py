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
WEEK_TEST_CAP = 400      # 한 주에 시험하는 후보 수 상한
SCOUT_START, SCOUT_END = (9, 0), (16, 30)
POOL_KEEP = 30
FRAME_CACHE = config.BASE_DIR / ".ce_frames.pkl"
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
    return out


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
    """이번 주 시험을 많이 했을수록 요구 개선폭을 높여요 (우연히 좋아 보이는 후보를 거르려고). 40개까지 5%, 400개면 약 10%"""
    return MIN_GAIN * (1 + math.log10(max(1.0, tests / 40)))


def passes_at(new, cur, gain):
    return (new["cal"] >= cur["cal"] * (1 + gain) and new["cal_r"] >= cur["cal_r"] and new["trades"] >= 0.6 * cur["trades"]
            and new["cagr"] >= 0.9 * cur["cagr"])


def fresh_pool():
    return {"week": week_id(), "tests": 0, "rounds": 0, "tested": [], "cands": [], "last": ""}


def in_scout_window(now=None):
    now = now or datetime.now()
    hm = (now.hour, now.minute)
    return now.weekday() < 5 and SCOUT_START <= hm <= SCOUT_END


def ensure_v1(st, today):
    if not st["versions"]:
        st["versions"].append({"v": 1, "genome": base_genome(), "born": today, "source": "기준 (지금 쓰는 본 전략과 같은 설정)", "idea": ""})
        return True
    return False


def scout(st, ctx, args, repos_n=2, n_mut=10):
    """탐색 한 번: 깃허브에서 아이디어를 읽고 + 스스로 변형을 만들어 시험하고, 쓸 만한 후보를 이번 주 후보 풀에 모아요 (버전은 안 바뀜)."""
    now = datetime.now()
    rnd = random.Random(now.strftime("%Y%m%d%H%M"))
    today = now.strftime("%Y-%m-%d")
    pool = st.get("pool")
    if not pool or pool.get("week") != week_id():
        pool = st["pool"] = fresh_pool()
    cur = st["versions"][-1]
    cur_m = evaluate(cur["genome"], ctx)
    cands = []
    n_git = 0
    if "--no-github" not in args:
        try:
            repos = github_scout.pick_repos(st["seen"], n=repos_n, rnd=rnd)
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
                    n_git += 1
    for g in mutations(cur["genome"], rnd, n_mut):
        cands.append((g, "스스로 변형 시험", ""))
    tried = 0
    for g, src, idea in cands:
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
        if src.startswith("깃허브 "):
            for e in reversed(st["ideas"]):
                if src.startswith("깃허브 " + e["repo"]):
                    e["tested"] += 1
                    break
        if m["cal"] >= cur_m["cal"] and m["cal_r"] >= cur_m["cal_r"] * 0.95:   # 현재 이상인 것만 후보 풀에 보관 (최종 판단은 금요일)
            pool["cands"].append({"genome": g, "source": src, "idea": idea, "cal": m["cal"], "found": today})
    pool["cands"].sort(key=lambda c: -c["cal"])
    pool["cands"] = pool["cands"][:POOL_KEEP]
    pool["tested"] = pool["tested"][-WEEK_TEST_CAP:]
    pool["rounds"] += 1
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
    mets = {v["v"]: evaluate(v["genome"], ctx) for v in st["versions"]}
    for v in st["versions"]:
        v["metrics"] = mets[v["v"]]
        v["describe"] = describe(v["genome"])
    tried, n_git = pool.get("tests", 0), sum(1 for c in pool.get("cands", []) if c["source"].startswith("깃허브"))
    git_tested = sum(e.get("tested", 0) for e in st["ideas"] if e["date"] >= (datetime.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
    st["runs"].append({"date": today, "tried": tried, "from_github": git_tested, "promoted": promoted, "version": cur_v, "need": round(gain * 100, 1)})
    st["pool"] = fresh_pool()
    st["pool"]["week"] = "applied-" + week_id()   # 다음 월요일 탐색에서 새 풀로 시작
    st["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    st["curves"] = curves(st, ctx)
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
            f"- 이번 주 시험 {tried}개 (기준 {gain * 100:.1f}% 이상 개선)\n- 설정: {describe(cur['genome'])}\n본 전략에는 자동으로 적용하지 않았어요. 적용하고 싶으시면 말씀해 주세요.")


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
        scout(st, ctx, args)
        if datetime.now().hour >= 16:   # 하루 마지막 즈음의 탐색만 깃허브에 올려 기록이 너무 늘지 않게
            push_data()
        return
    if not is_apply:   # 수동: 한 번 크게 탐색하고 바로 적용
        scout(st, ctx, args, repos_n=4, n_mut=30)
    promoted, tried, n_git, mets, gain = apply_week(st, ctx, args)
    msg = message(st, promoted, tried, n_git, mets, gain)
    print("\n" + msg.replace("**", ""))
    if "--no-dm" not in args:
        notify.send(msg, mention=promoted)


if __name__ == "__main__":
    main()
