"""장중 감시: 평일 장 시간(09:00~15:30)에 5분마다 보유 종목 시세를 확인합니다.
- 개장 알림 1회
- 손절 기준에 닿으면 즉시 매도하고 바로 보고 (그 외에는 조용히 감시)
- 이동평균 기준 매수·매도 판단은 하루 한 번(16:00 main.py)만 합니다."""
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, time as dtime, timedelta

import config
import forecast
import market
import messages
import notify
import status
from broker import PaperBroker

OPEN, CLOSE = dtime(9, 0), dtime(15, 30)
INTERVAL = 300   # 5분


def git_push(msg):
    for cmd in (["git", "add", "data"], ["git", "commit", "-m", msg], ["git", "push"]):
        try:
            subprocess.run(cmd, cwd=config.BASE_DIR, capture_output=True, timeout=120)
        except Exception as e:
            print("깃 업로드 실패:", e)
            return


def run_git(args, data=None):
    r = subprocess.run(["git"] + args, cwd=config.BASE_DIR, input=data, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).decode("utf-8", "ignore").strip()[:200])
    return r.stdout.decode("utf-8").strip()


def publish_live(broker, quotes, t, fc=None):
    """현재 평가금액을 live 브랜치에 올립니다 (대시보드 웹페이지는 이 파일을 읽어 장중에 갱신).
    live 브랜치는 매번 커밋 1개로 덮어써서 기록이 쌓이지 않고, 웹페이지 빌드도 일으키지 않습니다."""
    latest = {}
    lf = config.DATA_DIR / "latest.json"
    if lf.exists():
        latest = json.load(open(lf, encoding="utf-8")).get("symbols", {})
    prices, holdings = {}, []
    for code, p in broker.account["positions"].items():
        price = quotes.get(code) or latest.get(code, {}).get("price") or p["avg_price"]
        prices[code] = price
        holdings.append({"code": code, "name": p["name"], "qty": p["qty"], "avg_price": p["avg_price"], "peak": p.get("peak", p["avg_price"]), "price": price})
    payload = {
        "updated_at": t.strftime("%Y-%m-%d %H:%M:%S"),
        "equity": round(broker.equity(prices)),
        "cash": round(broker.account["cash"]),
        "holdings": holdings,
    }
    if fc:
        payload["fc"] = fc
    try:
        blob = run_git(["hash-object", "-w", "--stdin"], json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        tree = run_git(["mktree"], f"100644 blob {blob}\tlive.json\n".encode("utf-8"))
        commit = run_git(["commit-tree", tree, "-m", "live update"])
        run_git(["push", "--force", "origin", f"{commit}:refs/heads/live"])
    except Exception as e:
        print("실시간 데이터 업로드 실패:", e)


def tick(state, t):
    """한 번 확인. 'exit' 를 돌려주면 오늘 감시를 끝냅니다."""
    broker = PaperBroker()
    start = (t - timedelta(days=10)).strftime("%Y-%m-%d")
    held = {c: p for c, p in broker.account["positions"].items() if not config.is_us(c)}
    ref_code = next(c for c in config.SYMBOLS if not config.is_us(c))

    # 오늘 시세가 들어온 종목만 확인
    quotes = {}
    for code in set(held) | ({ref_code} if not state["opened"] else set()):
        df = market.load_prices(code, start)
        if df.index[-1].date() == t.date():
            quotes[code] = float(df["Close"].iloc[-1])

    if not state["opened"]:
        if ref_code not in quotes:
            if t.time() >= dtime(9, 30):
                if not state.get("quiet"):
                    notify.send(messages.no_data_message())
                return "exit"
            return None
        prices, holdings = {}, []
        for code, p in broker.account["positions"].items():
            df = market.load_prices(code, start)
            price = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else price
            prices[code] = price
            holdings.append({"name": p["name"], "qty": p["qty"], "price": price, "prev": prev})
        equity = broker.equity(prices)
        ret = round((equity / config.INITIAL_CASH - 1) * 100, 2)
        notify.send(messages.open_message(t.strftime("%H:%M"), equity, ret, broker.account["cash"], holdings,
                                          prev=broker.prev_equity(t.strftime("%Y-%m-%d"))), mention=True)
        state["opened"] = True

    blocked = broker.account.setdefault("blocked", [])
    sold, peak_changed = [], False
    for code, p in held.items():
        if code not in quotes:
            continue
        price = quotes[code]
        p.setdefault("peak", p["avg_price"])
        if price > p["peak"]:
            p["peak"], peak_changed = price, True
        reason = None
        if price / p["avg_price"] - 1 <= config.STOP_LOSS_PCT:
            reason = "손절"
        elif config.TRAIL_STOP_PCT and price <= p["peak"] * (1 - config.TRAIL_STOP_PCT):
            reason = "추적손절"
        if reason:
            tr = broker.sell(code, price, reason)
            if tr:
                sold.append(tr)
                if code not in blocked:
                    blocked.append(code)
    if sold:
        broker.save()
        notify.send(messages.trade_alert(sold), mention=True)
        git_push("intraday stop loss")
    elif peak_changed:
        broker.save()   # 최고가 기록 보존
    fc = None
    try:   # 보유 종목의 5분·1시간 뒤 가격 예측과 채점
        fc = forecast.tick({c: p for c, p in broker.account["positions"].items() if c in quotes}, quotes, t)
    except Exception as e:
        print("예측 갱신 실패:", e)
    publish_live(broker, quotes, t, fc)
    status.beat("monitor", True, f"감시 {len(held)}종목")
    print(f"[{t:%H:%M}] 확인 완료 (감시 {len(held)}종목, 손절 {len(sold)}건)")
    return None


def main():
    if "--once" in sys.argv:   # 점검용: 개장 알림 없이 한 번만 확인하고 live 데이터를 올려봅니다
        tick({"opened": True, "err": False, "quiet": True}, datetime.now())
        return
    state = {"opened": False, "err": False}
    while datetime.now().time() < OPEN:
        time.sleep(20)
    while datetime.now().time() <= CLOSE:
        began = time.time()
        try:
            if tick(state, datetime.now()) == "exit":
                break
        except Exception:
            tb = traceback.format_exc()
            print(tb)
            if not state["err"]:    # 오류 알림은 하루 한 번만
                state["err"] = True
                notify.send(messages.error_message(tb), mention=True)
        time.sleep(max(5, INTERVAL - (time.time() - began)))
    print("장중 감시를 마칩니다.")


if __name__ == "__main__":
    main()
