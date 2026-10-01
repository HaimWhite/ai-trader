import json
from datetime import datetime
import config


def _read_json(path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


class PaperBroker:
    """가상 계좌. 나중에 실제 증권사 브로커로 교체할 수 있도록 매수/매도 함수 형태를 맞춰둡니다."""

    def __init__(self):
        config.DATA_DIR.mkdir(exist_ok=True)
        self.account_file = config.DATA_DIR / "account.json"
        self.trades_file = config.DATA_DIR / "trades.json"
        self.history_file = config.DATA_DIR / "history.json"

        self.account = _read_json(
            self.account_file, {"cash": config.INITIAL_CASH, "positions": {}}
        )
        self.trades = _read_json(self.trades_file, [])
        self.history = _read_json(self.history_file, [])

    # ---------- 주문 ----------
    def buy(self, code, name, market_price, budget, reason=""):
        if code in self.account["positions"]:
            return None
        price = round(market_price * (1 + config.SLIPPAGE_RATE))
        unit_cost = price * (1 + config.FEE_RATE)
        affordable = min(budget, self.account["cash"])
        qty = int(affordable // unit_cost)
        if qty <= 0:
            return None

        amount = price * qty
        fee = int(amount * config.FEE_RATE)
        self.account["cash"] -= amount + fee
        self.account["positions"][code] = {
            "name": name,
            "qty": qty,
            "avg_price": price,
            "cost_basis": amount + fee,
        }
        return self._record("BUY", code, name, price, qty, fee, 0, 0, reason)

    def sell(self, code, market_price, reason=""):
        pos = self.account["positions"].get(code)
        if not pos:
            return None
        price = round(market_price * (1 - config.SLIPPAGE_RATE))
        qty = pos["qty"]
        amount = price * qty
        fee = int(amount * config.FEE_RATE)
        tax = int(amount * config.SELL_TAX_RATE)
        proceeds = amount - fee - tax
        pnl = proceeds - pos["cost_basis"]

        self.account["cash"] += proceeds
        del self.account["positions"][code]
        return self._record("SELL", code, pos["name"], price, qty, fee, tax, pnl, reason)

    def _record(self, side, code, name, price, qty, fee, tax, pnl, reason):
        trade = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "side": side,
            "code": code,
            "name": name,
            "price": price,
            "qty": qty,
            "fee": fee,
            "tax": tax,
            "pnl": pnl,
            "reason": reason,
        }
        self.trades.append(trade)
        return trade

    # ---------- 평가 ----------
    def equity(self, prices):
        total = self.account["cash"]
        for code, pos in self.account["positions"].items():
            total += pos["qty"] * prices.get(code, pos["avg_price"])
        return total

    def record_history(self, equity):
        today = datetime.now().strftime("%Y-%m-%d")
        ret = (equity / config.INITIAL_CASH - 1) * 100
        row = {"date": today, "equity": round(equity), "return_pct": round(ret, 2)}
        if self.history and self.history[-1]["date"] == today:
            self.history[-1] = row
        else:
            self.history.append(row)

    # ---------- 저장 ----------
    def save(self):
        _write_json(self.account_file, self.account)
        _write_json(self.trades_file, self.trades)
        _write_json(self.history_file, self.history)
