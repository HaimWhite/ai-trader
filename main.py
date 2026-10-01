import json
from datetime import datetime, timedelta

import FinanceDataReader as fdr

import config
import strategy
from broker import PaperBroker


def main():
    broker = PaperBroker()
    start = (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d")
    prices = {}
    latest = {}
    n = len(config.SYMBOLS)

    # 종목당 투자 한도 = 현재 총자산을 종목 수로 나눈 금액
    # (매수 전에 시세를 먼저 모두 읽어 총자산을 계산)
    frames = {}
    for code, name in config.SYMBOLS.items():
        try:
            df = fdr.DataReader(code, start).dropna()
            if len(df) < config.LONG_MA + 1:
                print(f"[{name}] 데이터가 부족해서 건너뜁니다.")
                continue
            frames[code] = df
            prices[code] = float(df["Close"].iloc[-1])
        except Exception as e:
            print(f"[{name}] 시세 조회 실패: {e}")

    budget = broker.equity(prices) / n

    for code, df in frames.items():
        name = config.SYMBOLS[code]
        price = prices[code]
        info = strategy.analyze(df)
        held = broker.account["positions"].get(code)
        action = "관망"

        # 1) 손절 우선
        if held and price / held["avg_price"] - 1 <= config.STOP_LOSS_PCT:
            t = broker.sell(code, price, "손절")
            action = f"손절 매도 {t['qty']}주" if t else action
        # 2) 전략 신호
        elif info["signal"] == "BUY" and not held:
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
        }
        print(f"[{name}] 종가 {price:,.0f}원 | {info['reason']} | {action}")

    equity = broker.equity(prices)
    broker.record_history(equity)
    broker.save()

    latest_out = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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


if __name__ == "__main__":
    main()
