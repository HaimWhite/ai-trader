"""다음 실적 발표일 수집 (yfinance, 최선 노력). 한국 종목은 정보가 없을 수 있고, 그러면 아무 영향이 없습니다.
config.EARNINGS_AVOID_DAYS 를 켜면 발표 N일 전부터는 새로 사지 않습니다."""
import json
from datetime import date, datetime

import config
from dividends import yf_symbol

PATH = config.DATA_DIR / "earnings.json"


def _first_future(cal, today):
    ed = None
    if isinstance(cal, dict):
        ed = cal.get("Earnings Date")
    elif cal is not None and hasattr(cal, "loc"):
        try:
            ed = list(cal.loc["Earnings Date"])
        except Exception:
            ed = None
    for d in (ed if isinstance(ed, (list, tuple)) else [ed]):
        if d is None:
            continue
        d = d.date() if hasattr(d, "date") else d
        if isinstance(d, date) and d >= today:
            return d.isoformat()
    return None


def update():
    today = datetime.now().date()
    data = json.load(open(PATH, encoding="utf-8")) if PATH.exists() else {}
    if data.get("_updated") == today.isoformat():
        return
    try:
        import yfinance as yf
    except ImportError:
        return
    got = 0
    for code in config.SYMBOLS:
        try:
            data[code] = _first_future(yf.Ticker(yf_symbol(code)).calendar, today)
            got += 1 if data[code] else 0
        except Exception:
            data.setdefault(code, None)
    data["_updated"] = today.isoformat()
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"실적 발표일 확인: {got}/{len(config.SYMBOLS)}종목")


def days_until(code):
    """다음 실적 발표까지 남은 일수 (모르면 None)"""
    if not PATH.exists():
        return None
    d = json.load(open(PATH, encoding="utf-8")).get(code)
    if not d:
        return None
    return (date.fromisoformat(d) - datetime.now().date()).days
