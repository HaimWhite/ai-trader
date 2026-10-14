"""'1주' 그래프를 촘촘하게 만들기 위한 시간 단위(1시간) 시세와 5분 단위 자산 기록.
- 종목별 1시간봉(최근 7일): main.py(16:00 점검)가 받아서 data/prices_1h.json 에 저장 (yfinance 사용, 한국 시간으로 통일)
- 자산 기록: monitor.py 가 5분마다 총 평가금액을 data/equity_intraday.json 에 덧붙임 (최근 10일치만 보관)
둘 다 실패해도 매매·보고에는 영향이 없어요. 대시보드는 이 파일이 없으면 예전처럼 일봉으로 그려요."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import config

KEEP_DAYS = 10
KST = "Asia/Seoul"


def _yf_symbol(code):
    if config.is_us(code):
        return code
    return code + (".KQ" if code in config.KOSDAQ_CODES else ".KS")


def _one(code, fx):
    import yfinance as yf
    df = yf.Ticker(_yf_symbol(code)).history(period="7d", interval="60m", auto_adjust=False)
    if df is None or len(df) == 0:
        return code, None
    idx = df.index.tz_convert(KST).tz_localize(None) if df.index.tz is not None else df.index
    mul = fx if config.is_us(code) else 1.0
    cols = {k: [round(float(v) * mul) for v in df[c]] for k, c in (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"))}
    if any(v <= 0 for v in cols["c"]):
        return code, None
    return code, {"t": [d.strftime("%Y-%m-%d %H:%M") for d in idx], **cols}


def update_hourly(codes):
    """종목별 1시간봉 저장. 받아 온 종목 수를 돌려줍니다."""
    import market
    fx = 1.0
    if any(config.is_us(c) for c in codes):
        try:
            fx = float(market.load_fx((datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")).iloc[-1])
        except Exception:
            fx = 0.0
    out = {}

    def job(c):
        try:
            if config.is_us(c) and fx <= 0:
                return c, None
            return _one(c, fx)
        except Exception:
            return c, None

    with ThreadPoolExecutor(6) as ex:
        for code, d in ex.map(job, list(codes)):
            if d:
                out[code] = d
    if out:
        config.DATA_DIR.mkdir(exist_ok=True)
        with open(config.DATA_DIR / "prices_1h.json", "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "fx": fx, "items": out}, f, ensure_ascii=False, separators=(",", ":"))
    return len(out)


def append_equity(t, equity):
    """5분마다 총 평가금액을 한 줄씩 덧붙임 ([시각, 금액])"""
    p = config.DATA_DIR / "equity_intraday.json"
    rows = []
    if p.exists():
        try:
            rows = json.load(open(p, encoding="utf-8"))
        except Exception:
            rows = []
    stamp = t.strftime("%Y-%m-%d %H:%M")
    if rows and rows[-1][0] == stamp:
        rows[-1][1] = round(equity)
    else:
        rows.append([stamp, round(equity)])
    lim = (t - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M")
    rows = [r for r in rows if r[0] >= lim]
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f, separators=(",", ":"))
