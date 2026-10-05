"""보유 수량을 직접 바꿉니다 (가상 계좌, 현재가 기준으로 체결).
사용 예:
  python adjust.py 삼성전자 +3    3주 추가 매수
  python adjust.py 삼성전자 -2    2주 매도
  python adjust.py 삼성전자 =10   수량을 10주로 맞춤
"""
import sys
from datetime import datetime, timedelta

import config
import market
from broker import PaperBroker


def find(key, broker):
    for code, name in config.SYMBOLS.items():
        if key.upper() == code.upper() or key == name:
            return code, name
    for code, p in broker.account["positions"].items():
        if key == p["name"] or key.upper() == code.upper():
            return code, p["name"]
    return None, None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return
    broker = PaperBroker()
    code, name = find(sys.argv[1], broker)
    if not code:
        print("종목을 찾지 못했습니다. 종목 이름이나 코드를 정확히 입력하세요.")
        return
    held = broker.account["positions"].get(code)
    now_qty = held["qty"] if held else 0
    arg = sys.argv[2]
    delta = int(arg[1:]) - now_qty if arg.startswith("=") else int(arg)
    if delta == 0:
        print(f"{name}은(는) 이미 {now_qty}주입니다.")
        return
    df = market.load_prices(code, (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"))
    price = float(df["Close"].iloc[-1])
    t = broker.buy_qty(code, name, price, delta) if delta > 0 else broker.sell_qty(code, price, -delta)
    if not t:
        print("실행하지 못했습니다. (현금이 부족하거나 보유 수량이 없습니다)")
        return
    broker.save()
    side = "매수" if t["side"] == "BUY" else "매도"
    print(f"{name} {t['qty']}주를 {t['price']:,}원에 {side}했습니다. (현재 보유 {now_qty + (t['qty'] if delta > 0 else -t['qty'])}주, 현금 {broker.account['cash']:,.0f}원)")
    print("대시보드에 반영하려면 run.bat 을 실행하세요.")


if __name__ == "__main__":
    main()
