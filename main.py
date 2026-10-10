import json
import sys
from datetime import datetime, time as dtime, timedelta

import pandas as pd

import config
import dividends
import drawdown
import earnings
import forecast
import market
import messages
import news
import notify
import review
import status
import strategy
from broker import PaperBroker


def gap_count(df):
    """최근 120일 중 갭(전날 종가 대비 시가 차이가 GAP_THR 이상)이 난 날의 수"""
    c = df["Close"]
    o = df["Open"].where(df["Open"] > 0, c)
    return int(((o / c.shift(1) - 1).abs() >= config.GAP_THR).tail(120).sum())


def size_budget(code, df, budget, equity):
    """변동성이 크거나 갭이 잦은 종목은 적게 사도록 투자 금액을 줄입니다 (config 옵션이 켜져 있을 때만)."""
    if config.VOL_SIZE_RISK:
        m = df["Close"].pct_change().abs().rolling(20).mean().iloc[-1]
        if m == m:
            budget = min(budget, equity * config.VOL_SIZE_RISK / min(0.20, max(config.VOL_FLOOR, 3 * m)))
    if config.HIGHVOL_SCALE and code in config.WIDE_STOP_CODES:
        budget *= config.HIGHVOL_SCALE
    if config.GAP_MODE == "half" and gap_count(df) >= config.GAP_DAYS:
        budget *= 0.5
    return budget


def sector_full(positions, code):
    """같은 업종을 이미 MAX_PER_SECTOR 종목만큼 들고 있는지"""
    lim = config.MAX_PER_SECTOR
    sec = config.SECTORS.get(code)
    return bool(lim and sec and sum(1 for c in positions if config.SECTORS.get(c) == sec) >= lim)


def save_indices(start):
    """코스피·나스닥 지수 기록 (대시보드의 지수 비교용)"""
    path = config.DATA_DIR / "indices.json"
    data = json.load(open(path, encoding="utf-8")) if path.exists() else {}
    for sym, yf_sym, name in (("KS11", "^KS11", "코스피"), ("IXIC", "^IXIC", "나스닥")):
        try:
            df = market._fetch(sym, yf_sym, start).dropna(subset=["Close"])
            data[sym] = {"name": name, "dates": [d.strftime("%Y-%m-%d") for d in df.index],
                         "close": [round(float(x), 2) for x in df["Close"]]}
        except Exception as e:
            print(f"[{name}] 지수 조회 실패: {str(e)[:80]}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def execute_pending(broker, frames, prices, pending, fills):
    """전 영업일 종가 후에 낸 주문을 '신호 다음 거래일의 시가'에 체결합니다 (백테스트와 같은 방식)."""
    now = datetime.now()
    todo = []
    for code, o in pending.items():
        if code not in frames:
            continue
        if (now - datetime.strptime(o["created"][:10], "%Y-%m-%d")).days > 7:
            continue   # 너무 오래된 주문은 버림
        rows = frames[code][frames[code].index > pd.Timestamp(o["date"])]
        if rows.empty:   # 아직 다음 거래일 시세가 없음
            continue
        r = rows.iloc[0]
        todo.append((code, o, float(r["Open"]) if r["Open"] > 0 else float(r["Close"])))

    positions = broker.account["positions"]
    for code, o, op in todo:
        if o["side"] == "SELL" and code in positions:
            t = broker.sell(code, op, o["reason"])
            if t:
                fills[code] = f"체결 매도 {t['qty']}주(시가)"
    buys = sorted([x for x in todo if x[1]["side"] == "BUY" and x[0] not in positions], key=lambda x: -x[1].get("rank", 0))
    if buys:
        eq_open = broker.equity(prices)
        budget = eq_open / min(len(config.SYMBOLS), config.MAX_POSITIONS)
        for code, o, op in buys:
            if len(positions) >= config.MAX_POSITIONS or sector_full(positions, code):
                continue
            t = broker.buy(code, config.SYMBOLS[code], op, size_budget(code, frames[code], budget, eq_open), o["reason"])
            if t:
                fills[code] = f"체결 매수 {t['qty']}주(시가)"


def main():
    broker = PaperBroker()
    n_before = len(broker.trades)

    # 장중(평일 09:00~15:30)에 직접 실행하면 장중 가격으로 판단하게 되므로 매매 없이 점검만 합니다
    now = datetime.now()
    market_open = now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(15, 30)
    trading_allowed = (not market_open) or ("--force" in sys.argv)
    if not trading_allowed:
        print("장중이라 이번 실행은 매매 없이 점검만 합니다. (장 마감 후 실행하거나, 꼭 필요하면 --force 를 붙이세요)")
    start = config.PRICE_HISTORY_START
    prices = {}
    failed = []
    news_list, news_blocked, warnings = [], [], []
    latest = {}

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

    try:
        save_indices(start)
    except Exception as e:
        print("지수 기록 실패:", e)
    try:
        earnings.update()
    except Exception as e:
        print("실적 발표일 확인 실패:", e)

    watch = {}   # 관찰 목록: 매매 없이 신호만 기록
    for code, w in config.WATCH.items():
        try:
            df = market.load_prices(code, start)
            if len(df) < config.LONG_MA + 1:
                continue
            info = strategy.analyze(df)
            watch[code] = {"name": w["name"], "sector": w["sector"], "group": config.group_of(code), "price": float(df["Close"].iloc[-1]),
                           "prev_close": float(df["Close"].iloc[-2]) if len(df) > 1 else None, "signal": info["signal"],
                           "short_ma": info["short_ma"], "long_ma": info["long_ma"], "mas": info.get("mas", {})}
        except Exception as e:
            print(f"[관찰:{w['name']}] 시세 조회 실패(건너뜀): {str(e)[:60]}")

    blocked = broker.account.setdefault("blocked", [])
    infos = {code: strategy.analyze(df) for code, df in frames.items()}
    valid = [i for i in infos.values() if i["signal"] != "HOLD"]
    breadth = sum(i["signal"] == "BUY" for i in valid) / len(valid) if valid else 1.0   # 상승 추세 종목 비율
    weak_market = bool(config.BREADTH_MIN and breadth < config.BREADTH_MIN)

    def strength(code):
        return infos[code].get("rank", 0)

    # A) 전 영업일에 낸 주문을 오늘(다음 거래일) 시가에 체결
    fills = {}
    if trading_allowed and broker.account.get("pending"):
        execute_pending(broker, frames, prices, broker.account["pending"], fills)

    # B) 오늘 종가 기준으로 판단하고, 다음 거래일 시가에 낼 주문을 예약
    new_pending = {}
    for code in sorted(frames, key=strength, reverse=True):
        df = frames[code]
        name = config.SYMBOLS[code]
        price = prices[code]
        info = infos[code]
        held = broker.account["positions"].get(code)
        decision = "관망"

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

        pend = None
        if not trading_allowed:
            decision = "관망(장중이라 매매 보류, 장 마감 후 판단)"
        elif held and price / held["avg_price"] - 1 <= config.STOP_LOSS_PCT:
            pend, decision = ("SELL", "손절"), "매도 예약(손절)"
            if code not in blocked:
                blocked.append(code)
        elif trail_hit:
            pend, decision = ("SELL", "추적손절"), "매도 예약(추적손절)"
            if code not in blocked:
                blocked.append(code)
        elif info["signal"] == "BUY" and not held:
            days_left = earnings.days_until(code) if config.EARNINGS_AVOID_DAYS else None
            if code in blocked:
                decision = "관망(손절 후 재진입 대기)"
            elif news_info["ok"] and news_info["score"] <= config.NEWS_BLOCK_BUY_SCORE:
                decision = "관망(악재 뉴스로 매수 보류)"
                news_blocked.append(name)
            elif config.GAP_MODE == "skip" and gap_count(df) >= config.GAP_DAYS:
                decision = "관망(갭 하락이 잦은 종목이라 매수 보류)"
            elif weak_market:
                decision = "관망(시장 약세로 신규 매수 보류)"
            elif days_left is not None and 0 <= days_left <= config.EARNINGS_AVOID_DAYS:
                decision = f"관망(실적 발표 {days_left}일 전이라 매수 보류)"
            else:
                pend, decision = ("BUY", info["reason"]), "매수 예약"
        elif info["signal"] == "SELL" and held:
            pend, decision = ("SELL", info["reason"]), "매도 예약(추세 하락)"
        if pend:
            new_pending[code] = {"side": pend[0], "reason": pend[1], "name": name, "rank": strength(code),
                                 "date": df.index[-1].strftime("%Y-%m-%d"), "created": now.strftime("%Y-%m-%d %H:%M:%S")}

        action = (fills[code] + (" · " + decision if decision != "관망" else "")) if code in fills else decision
        latest[code] = {
            "name": name,
            "sector": config.SECTORS.get(code, ""),
            "group": config.group_of(code),
            "price": price,
            "prev_close": float(df["Close"].iloc[-2]) if len(df) > 1 else None,
            "short_ma": info["short_ma"],
            "long_ma": info["long_ma"],
            "mas": info.get("mas", {}),
            "trend_sell": (round(x, 1) if (x := strategy.trend_sell_price(df)) else None),
            "signal": info["signal"],
            "reason": info["reason"],
            "action": action,
            "news": {"score": news_info["score"], "summary": news_info["summary"]},
        }
        print(f"[{name}] 종가 {price:,.0f}원 | {info['reason']} | {action}")

    # 보유 자리보다 많은 매수 예약은 '대기'로 표시 (매도 예약이 체결되어 자리가 나야 살 수 있음)
    free = config.MAX_POSITIONS - len(broker.account["positions"]) + sum(1 for o in new_pending.values() if o["side"] == "SELL")
    buy_codes = sorted([c for c, o in new_pending.items() if o["side"] == "BUY"], key=lambda c: -new_pending[c]["rank"])
    waiting = set(buy_codes[max(free, 0):])
    for c in waiting:
        latest[c]["action"] = latest[c]["action"].replace("매수 예약", "매수 대기(보유 자리가 나면)")

    if trading_allowed:
        broker.account["pending"] = new_pending
    equity = broker.equity(prices)
    prev = broker.prev_equity()   # 전 영업일 마감 기록 (오늘 기록을 쓰기 전에 가져옴)
    broker.record_history(equity)
    broker.save()
    if trading_allowed:   # 고점 대비 낙폭 경보 (장 마감 후 기록 기준)
        try:
            dd_info = drawdown.current(broker.history)
            kind, lvl = drawdown.decide(dd_info["dd"])
            if kind:
                notify.send(messages.drawdown_alert(dd_info, lvl, kind, drawdown.backtest_mdd()), mention=(kind == "deeper"))
        except Exception as e:
            print("낙폭 점검 실패:", e)
    hold_rows = [{"name": p["name"], "qty": p["qty"], "price": prices.get(c, p["avg_price"]),
                  "prev": latest.get(c, {}).get("prev_close")} for c, p in broker.account["positions"].items()]
    try:   # 거래 복기 자료 갱신 (대시보드의 '거래 복기' 칸)
        review.update()
    except Exception as e:
        print("거래 복기 갱신 실패:", e)
    try:   # 하루 단위 예측 (보유 종목의 다음 거래일 종가 예상과 지난 예측 채점)
        forecast.daily_update(broker.account["positions"], frames, broker.trades)
    except Exception as e:
        print("예측 갱신 실패:", e)

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

    pending_list = [{"code": c, "name": o["name"], "side": o["side"], "reason": o["reason"]}
                    for c, o in broker.account.get("pending", {}).items() if c not in waiting]
    latest_out = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_cash": config.INITIAL_CASH,
        "breadth_pct": round(breadth * 100),
        "news_mode": news.mode_name() if config.USE_NEWS else "off",
        "rules": {"stop_loss_pct": config.STOP_LOSS_PCT, "trail_pct": config.TRAIL_STOP_PCT,
                  "short_ma": config.SHORT_MA, "long_ma": config.LONG_MA, "max_positions": config.MAX_POSITIONS,
                  "long_mas": list(config.LONG_MAS) if config.LONG_MAS else None, "long_rule": config.LONG_RULE,
                  "show_mas": list(config.SHOW_MAS)},
        "pending": pending_list,
        "cash": broker.account["cash"],
        "equity": round(equity),
        "return_pct": round((equity / config.INITIAL_CASH - 1) * 100, 2),
        "symbols": latest,
        "watch": watch,
    }
    with open(config.DATA_DIR / "latest.json", "w", encoding="utf-8") as f:
        json.dump(latest_out, f, ensure_ascii=False, indent=2)

    print()
    print(f"현금: {broker.account['cash']:,.0f}원")
    print(f"총 평가금액: {equity:,.0f}원 (수익률 {latest_out['return_pct']}%)")

    # 디스코드 알림 (문구는 messages.py 에서 수정)
    new_trades = broker.trades[n_before:]
    text = messages.daily_message(equity, latest_out["return_pct"], broker.account["cash"], new_trades, failed,
                                  news_list if config.USE_NEWS else None, news_blocked, warnings,
                                  pending_list if trading_allowed else None, prev=prev, holdings=hold_rows)
    # 거래가 있었거나 시세 조회에 실패했을 때만 푸시 알림이 울리게 보냄
    notify.send(text, mention=bool(new_trades) or bool(failed) or bool(warnings))
    status.beat("main", True, f"거래 {len(new_trades)}건, 예약 {len(pending_list)}건")


def report():
    """점심 중간 보고: 매매도 저장도 하지 않고 현재 평가금액만 디스코드로 알립니다."""
    broker = PaperBroker()
    now = datetime.now()
    start = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    ref = market.load_prices(next(c for c in config.SYMBOLS if not config.is_us(c)), start)
    if ref.index[-1].date() != now.date():
        notify.send(messages.midday_message("", 0, 0, 0, [], [], closed=True))
        print("오늘 시세가 반영되지 않았습니다 (휴장 또는 지연). 보고를 생략합니다.")
        return

    prices, holdings, failed = {}, [], []
    for code, pos in broker.account["positions"].items():
        dfp = None
        try:
            dfp = market.load_prices(code, start)
            price = float(dfp["Close"].iloc[-1])
        except Exception as e:
            print(f"[{pos['name']}] 시세 조회 실패: {e}")
            price = pos["avg_price"]
            failed.append(pos["name"])
        prices[code] = price
        prev_close = float(dfp["Close"].iloc[-2]) if dfp is not None and len(dfp) > 1 else None
        holdings.append({"name": pos["name"], "qty": pos["qty"], "price": price, "avg": pos["avg_price"], "prev": prev_close})

    equity = broker.equity(prices)
    ret = round((equity / config.INITIAL_CASH - 1) * 100, 2)
    text = messages.midday_message(now.strftime("%H:%M"), equity, ret, broker.account["cash"], holdings, failed,
                                   prev=broker.prev_equity(now.strftime("%Y-%m-%d")))
    print(text)
    notify.send(text, mention=bool(failed))
    status.beat("report", True, "중간 보고")


if __name__ == "__main__":
    try:
        report() if "--report" in sys.argv else main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        status.beat("report" if "--report" in sys.argv else "main", False, tb.strip().splitlines()[-1])
        notify.send(messages.error_message(tb), mention=True)
        raise
