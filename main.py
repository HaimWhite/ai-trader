import json
import sys
from datetime import datetime, timedelta

import FinanceDataReader as fdr

import config
import dividends
import market
import messages
import news
import notify
import strategy
from broker import PaperBroker


def main():
    broker = PaperBroker()
    n_before = len(broker.trades)
    start = config.PRICE_HISTORY_START
    prices = {}
    failed = []
    news_list, news_blocked, warnings = [], [], []
    latest = {}
    n = len(config.SYMBOLS)

    # 종목당 투자 한도 = 현재 총자산을 종목 수로 나눈 금액
    # (매수 전에 시세를 먼저 모두 읽어 총자산을 계산)
    frames = {}
    for code, name in config.SYMBOLS.items():
        try:
            df = market.load_prices(code, start)
            if len(df) < config.LONG_MA + 1:
                print(f"[{name}] 데이터가 부족해서 건너뜁니다.")
                continue
            frames[code] = df
            prices[code] = float(df["Close"].iloc[-1])
        except Exception as e:
            print(f"[{name}] 시세 조회 실패: {e}")
            failed.append(name)

    budget = broker.equity(prices) / min(n, config.MAX_POSITIONS)
    blocked = broker.account.setdefault("blocked", [])

    # 상승 추세가 강한 종목부터 판단 (자리가 한정되어 있어서 강한 종목이 먼저 채우도록)
    infos = {code: strategy.analyze(df) for code, df in frames.items()}

    def strength(code):
        i = infos[code]
        return i["short_ma"] / i["long_ma"] if i["short_ma"] and i["long_ma"] else 0

    for code in sorted(frames, key=strength, reverse=True):
        df = frames[code]
        name = config.SYMBOLS[code]
        price = prices[code]
        info = infos[code]
        held = broker.account["positions"].get(code)
        action = "관망"

        # 뉴스 확인 (악재일 때 매수 보류용 참고 정보)
        news_info = {"score": 0, "summary": "", "ok": True}
        if config.USE_NEWS:
            news_info = news.get_news(code, name)
            news_list.append({"name": name, **news_info})
            if held and news_info["ok"] and news_info["score"] <= config.NEWS_WARN_HELD_SCORE:
                warnings.append(f"주의: 보유 중인 {name}에 큰 악재 뉴스가 있습니다. {news_info['summary']} 직접 확인해 주세요.")

        # 하락 추세가 확인되면 손절 후 재진입 대기를 해제
        if info["signal"] == "SELL" and code in blocked:
            blocked.remove(code)

        # 매수 후 최고가 갱신 (추적 손절용)
        if held:
            held["peak"] = max(held.get("peak", held["avg_price"]), price)
        trail_hit = bool(held and config.TRAIL_STOP_PCT and price <= held["peak"] * (1 - config.TRAIL_STOP_PCT))

        # 1) 손절 우선
        if held and price / held["avg_price"] - 1 <= config.STOP_LOSS_PCT:
            t = broker.sell(code, price, "손절")
            if t:
                action = f"손절 매도 {t['qty']}주"
                if code not in blocked:
                    blocked.append(code)
        # 1.5) 추적 손절: 번 돈을 다시 토해내기 전에 최고가 대비 크게 내려오면 매도
        elif trail_hit:
            t = broker.sell(code, price, "추적손절")
            if t:
                action = f"추적손절 매도 {t['qty']}주"
                if code not in blocked:
                    blocked.append(code)
        # 2) 전략 신호
        elif info["signal"] == "BUY" and not held:
            if code in blocked:
                action = "관망(손절 후 재진입 대기)"
            elif news_info["ok"] and news_info["score"] <= config.NEWS_BLOCK_BUY_SCORE:
                action = "관망(악재 뉴스로 매수 보류)"
                news_blocked.append(name)
            elif len(broker.account["positions"]) >= config.MAX_POSITIONS:
                action = "관망(동시 보유 한도)"
            else:
                t = broker.buy(code, name, price, budget, info["reason"])
                action = f"매수 {t['qty']}주" if t else "매수 불가(자금 부족)"
        elif info["signal"] == "SELL" and held:
            t = broker.sell(code, price, info["reason"])
            action = f"매도 {t['qty']}주" if t else action

        latest[code] = {
            "name": name,
            "price": price,
            "short_ma": info["short_ma"],
            "long_ma": info["long_ma"],
            "signal": info["signal"],
            "reason": info["reason"],
            "action": action,
            "news": {"score": news_info["score"], "summary": news_info["summary"]},
        }
        print(f"[{name}] 종가 {price:,.0f}원 | {info['reason']} | {action}")

    equity = broker.equity(prices)
    broker.record_history(equity)
    broker.save()

    # 대시보드 주가 그래프용 시세 저장 (조회에 실패한 종목은 이전 기록 유지)
    pfile = config.DATA_DIR / "prices.json"
    pdata = json.load(open(pfile, encoding="utf-8")) if pfile.exists() else {}
    pdata = {c: v for c, v in pdata.items() if c in config.SYMBOLS}
    for code, df in frames.items():
        pdata[code] = {
            "name": config.SYMBOLS[code],
            "dates": [d.strftime("%Y-%m-%d") for d in df.index],
            "close": [int(x) for x in df["Close"]],
        }
    with open(pfile, "w", encoding="utf-8") as f:
        json.dump(pdata, f, ensure_ascii=False, separators=(",", ":"))

    try:
        dividends.update()
    except Exception as e:
        print("배당 정보 갱신 실패:", e)

    latest_out = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_cash": config.INITIAL_CASH,
        "rules": {"stop_loss_pct": config.STOP_LOSS_PCT, "trail_pct": config.TRAIL_STOP_PCT,
                  "short_ma": config.SHORT_MA, "long_ma": config.LONG_MA, "max_positions": config.MAX_POSITIONS},
        "cash": broker.account["cash"],
        "equity": round(equity),
        "return_pct": round((equity / config.INITIAL_CASH - 1) * 100, 2),
        "symbols": latest,
    }
    with open(config.DATA_DIR / "latest.json", "w", encoding="utf-8") as f:
        json.dump(latest_out, f, ensure_ascii=False, indent=2)

    print()
    print(f"현금: {broker.account['cash']:,.0f}원")
    print(f"총 평가금액: {equity:,.0f}원 (수익률 {latest_out['return_pct']}%)")

    # 디스코드 알림 (문구는 messages.py 에서 수정)
    new_trades = broker.trades[n_before:]
    text = messages.daily_message(equity, latest_out["return_pct"], broker.account["cash"], new_trades, failed,
                                  news_list if config.USE_NEWS else None, news_blocked, warnings)
    # 거래가 있었거나 시세 조회에 실패했을 때만 푸시 알림이 울리게 보냄
    notify.send(text, mention=bool(new_trades) or bool(failed) or bool(warnings))


def report():
    """점심 중간 보고: 매매도 저장도 하지 않고 현재 평가금액만 디스코드로 알립니다."""
    broker = PaperBroker()
    now = datetime.now()
    start = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    ref = fdr.DataReader(next(c for c in config.SYMBOLS if not config.is_us(c)), start).dropna()
    if ref.index[-1].date() != now.date():
        notify.send(messages.midday_message("", 0, 0, 0, [], [], closed=True))
        print("오늘 시세가 반영되지 않았습니다 (휴장 또는 지연). 보고를 생략합니다.")
        return

    prices, holdings, failed = {}, [], []
    for code, pos in broker.account["positions"].items():
        try:
            price = float(market.load_prices(code, start)["Close"].iloc[-1])
        except Exception as e:
            print(f"[{pos['name']}] 시세 조회 실패: {e}")
            price = pos["avg_price"]
            failed.append(pos["name"])
        prices[code] = price
        holdings.append({"name": pos["name"], "qty": pos["qty"], "price": price, "avg": pos["avg_price"]})

    equity = broker.equity(prices)
    ret = round((equity / config.INITIAL_CASH - 1) * 100, 2)
    text = messages.midday_message(now.strftime("%H:%M"), equity, ret, broker.account["cash"], holdings, failed)
    print(text)
    notify.send(text, mention=bool(failed))


if __name__ == "__main__":
    try:
        report() if "--report" in sys.argv else main()
    except Exception:
        import traceback
        notify.send(messages.error_message(traceback.format_exc()), mention=True)
        raise
