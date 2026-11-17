"""Storico ordini Alpaca per la diagnosi: tutti gli ordini dal giorno scelto, compresi quelli del core SPY."""
import datetime as dt
from types import SimpleNamespace

import app
import trading_core as core

UTC = dt.timezone.utc


def _order(i, symbol, side, cid, day, notional=None, qty=None, price=None, status="filled"):
    ts = dt.datetime(2026, 11, day, 15, 0, tzinfo=UTC)
    return SimpleNamespace(id=f"o{i}", symbol=symbol, side=SimpleNamespace(value=side), client_order_id=cid,
                           submitted_at=ts, filled_at=ts if status == "filled" else None,
                           notional=notional, qty=qty, filled_qty=qty or (notional / price if notional and price else 0),
                           filled_avg_price=price, status=SimpleNamespace(value=status), type=SimpleNamespace(value="market"))


class FakeAlpaca:
    def __init__(self, orders):
        self.orders, self.requests = orders, []

    def get_orders(self, req):
        self.requests.append(req)
        after = req.after
        return [o for o in self.orders if o.submitted_at > after][: req.limit]


ORDERS = [
    _order(1, "SPY", "buy", "core-buy-aaa", 3, notional=76000, price=754.35),
    _order(2, "SPY", "sell", "core-sell-bbb", 4, notional=50321, price=766.81),
    _order(3, "AAPL", "buy", "brd-x-1", 5, qty=10, price=230.0),
    _order(4, "SPY", "sell", "manual-1", 6, qty=5, price=735.0),
    _order(5, "NVDA", "buy", "brd-x-2", 7, qty=3, price=180.0, status="canceled"),
]


def test_order_history_classifies_core_bot_and_manual(monkeypatch):
    monkeypatch.setattr(core, "alpaca_client", FakeAlpaca(ORDERS))
    rows = core.order_history(dt.date(2026, 11, 3))
    assert [r["source"] for r in rows] == ["core SPY", "core SPY", "bot", "altro", "bot"]
    assert rows[0]["notional"] == 76000 and rows[0]["side"] == "BUY" and rows[1]["side"] == "SELL"
    assert rows[4]["status"] == "canceled" and rows[4]["filled_at"] is None


def test_order_history_filters_symbol_and_returns_none_without_alpaca(monkeypatch):
    monkeypatch.setattr(core, "alpaca_client", FakeAlpaca(ORDERS))
    assert [r["id"] for r in core.order_history(dt.date(2026, 11, 3), symbol="spy")] == ["o1", "o2", "o4"]
    monkeypatch.setattr(core, "alpaca_client", None)
    assert core.order_history(dt.date(2026, 11, 3)) is None


def test_api_orders_requires_token_and_validates_date(monkeypatch):
    monkeypatch.setattr(core, "alpaca_client", FakeAlpaca(ORDERS))
    client = app.app.test_client()
    assert client.get("/api/orders?since=2026-11-03").status_code == 401
    headers = {"X-API-Key": core.get_api_token()}
    assert client.get("/api/orders?since=03-11-2026", headers=headers).status_code == 400
    res = client.get("/api/orders?since=2026-11-03&symbol=SPY", headers=headers)
    data = res.get_json()
    assert res.status_code == 200 and data["count"] == 3
    assert data["summary"]["core SPY"] == {"orders": 2, "bought_usd": 76000.0, "sold_usd": 50321.0}
