"""종목별 배당 정보 수집 (yfinance 사용, 하루 한 번). 실패하면 그냥 건너뜁니다.
설치: pip install yfinance"""
import json
from datetime import datetime

import config


def yf_symbol(code):
    if config.is_us(code):
        return code
    return code + (".KQ" if code in config.KOSDAQ_CODES else ".KS")


def update():
    path = config.DATA_DIR / "dividends.json"
    today = datetime.now().strftime("%Y-%m-%d")
    data = json.load(open(path, encoding="utf-8")) if path.exists() else {}
    if data.get("_updated") == today:
        return
    try:
        import pandas as pd
        import yfinance as yf
    except ImportError:
        print("yfinance 가 설치되어 있지 않아 배당 정보를 건너뜁니다. (pip install yfinance)")
        return
    got = 0
    for code in config.SYMBOLS:
        try:
            t = yf.Ticker(yf_symbol(code))
            price = float(t.history(period="5d")["Close"].iloc[-1])
            div = t.dividends
            if div is None or len(div) == 0:
                data[code] = {"ok": True, "yield_pct": 0.0, "annual": 0, "last_date": None}
            else:
                cutoff = pd.Timestamp.now(tz=div.index.tz) - pd.Timedelta(days=365)
                annual = float(div[div.index >= cutoff].sum())
                data[code] = {
                    "ok": True,
                    "yield_pct": round(annual / price * 100, 2),
                    "annual": round(annual, 2),
                    "last_date": div.index[-1].strftime("%Y-%m-%d"),
                    "currency": "USD" if config.is_us(code) else "KRW",
                }
        except Exception as e:
            print(f"[{config.SYMBOLS[code]}] 배당 조회 실패: {str(e)[:80]}")
            data.setdefault(code, {"ok": False})
            continue
        got += 1
    if got:   # 하나도 못 가져왔으면 날짜를 기록하지 않아서 다음 실행 때 다시 시도합니다
        data["_updated"] = today
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":   # 점검용: python dividends.py
    p = config.DATA_DIR / "dividends.json"
    if p.exists():
        d = json.load(open(p, encoding="utf-8"))
        d.pop("_updated", None)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    update()
    d = json.load(open(p, encoding="utf-8")) if p.exists() else {}
    ok = sum(1 for k, v in d.items() if k != "_updated" and v.get("ok"))
    print(f"배당 정보 {ok}/{len(config.SYMBOLS)}종목 수집 완료")
