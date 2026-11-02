"""미국 장중 감시: 미국 장이 열려 있는 동안 5분마다 보유 미국 종목의 현재가를 가져와서 대시보드에 보여줍니다.
- 한국 시간으로 겨울(서머타임 아님) 23:30~06:00, 여름 22:30~05:00 에 장이 열려요. 작업은 평일 22:25 에 시작하고, 장이 열릴 때까지 기다려요.
- 보기 전용이에요: 장중에 자동으로 사고팔지 않아요 (미국 종목 매매는 지금처럼 한국 시간 다음 날 점검 때 결정).
- 평가금액·총 자산은 실시간 환율(원화)로 환산해서 live 브랜치에 올려요. 한국 보유 종목은 마지막 종가를 그대로 써요.
- 실행: python monitor_us.py          한 번만 확인(점검용): python monitor_us.py --once"""
import json
import sys
import time
import traceback
from datetime import date, datetime, timedelta

import config
import monitor
import notify
import status
from broker import PaperBroker

INTERVAL = 300


def _nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def us_dst(d):
    """미국 서머타임 여부 (3월 둘째 일요일 ~ 11월 첫째 일요일 전날)"""
    return _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)


def session_kst(day):
    """KST 날짜 day 저녁에 시작하는 미국 정규장의 (시작, 끝) 한국 시각"""
    h = 22 if us_dst(day) else 23
    start = datetime(day.year, day.month, day.day, h, 30)
    return start, start + timedelta(hours=6, minutes=30)


def fetch_quote(code):
    """(현재가 달러, 전일 종가 달러). 실패하면 None"""
    import yfinance as yf
    t = yf.Ticker(code)
    try:
        fi = t.fast_info
        last, prev = float(fi["last_price"]), float(fi["previous_close"])
        if last > 0:
            return last, prev
    except Exception:
        pass
    try:
        df = t.history(period="2d", interval="5m", auto_adjust=False)
        if df is not None and len(df):
            return float(df["Close"].iloc[-1]), None
    except Exception:
        pass
    return None


def fetch_fx():
    import yfinance as yf
    try:
        v = float(yf.Ticker("KRW=X").fast_info["last_price"])
        if v > 0:
            return v
    except Exception:
        pass
    import market
    return float(market.load_fx((datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")).iloc[-1])


def tick(t):
    broker = PaperBroker()
    held = [c for c in broker.account["positions"] if config.is_us(c)]
    watch = sorted(set(held) | {c for c in config.SYMBOLS if config.is_us(c)})
    fx = fetch_fx()
    quotes, moves = {}, {}
    for code in watch:
        q = fetch_quote(code)
        if q:
            quotes[code] = round(q[0] * fx)
            if q[1]:
                moves[code] = round((q[0] / q[1] - 1) * 100, 2)
    if not quotes:
        return False
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(config.DATA_DIR / "us_quotes.json", "w", encoding="utf-8") as f:
        json.dump({"updated": t.strftime("%Y-%m-%d %H:%M:%S"), "fx": round(fx, 2), "quotes": quotes, "moves": moves}, f, ensure_ascii=False)
    us = {"updated": t.strftime("%Y-%m-%d %H:%M:%S"), "fx": round(fx, 2), "quotes": quotes, "moves": moves}
    monitor.publish_live(broker, {c: p for c, p in quotes.items() if c in held}, t, None, extra={"us": us})
    status.beat("monitor_us", True, f"미국 {len(held)}종목")
    print(f"[{t:%m-%d %H:%M}] 미국 확인 완료 (보유 {len(held)}종목, 환율 {fx:.0f}원)")
    return True


def main():
    if "--once" in sys.argv:
        tick(datetime.now())
        return
    now = datetime.now()
    day = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)   # 새벽에 시작하면 전날 저녁 장
    start, end = session_kst(day)
    if day.weekday() >= 5:
        print("주말이라 미국 장이 열리지 않아요.")
        return
    while datetime.now() < start - timedelta(minutes=5):
        time.sleep(30)
    empty, err = 0, False
    while datetime.now() <= end:
        began = time.time()
        try:
            if tick(datetime.now()):
                empty = 0
            else:
                empty += 1
        except Exception:
            print(traceback.format_exc())
            empty += 1
            if not err:
                err = True
                notify.send("하임님, 미국 장중 감시에서 오류가 났습니다. monitor_log.txt 를 확인해 주세요.")
        if empty >= 6 and datetime.now() >= start + timedelta(minutes=30):
            print("시세가 계속 들어오지 않아 오늘은 휴장으로 보고 마칩니다.")
            break
        time.sleep(max(5, INTERVAL - (time.time() - began)))
    print("미국 장중 감시를 마칩니다.")


if __name__ == "__main__":
    main()
