"""Capitale tattico: day-trading su SPY (area di rumore) e acquisti nel panico su VOO."""
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import app
import trading_core as core
from agents import day_trader as dtr
from agents import panic_buyer as pnc
from backtest import noise_area


def minute_bars(days=18, drift_last=0.0, seed=1, start="2026-10-01"):
    """Barre da 1 minuto di SPY, ora di New York: rumore casuale e, nell'ultimo giorno, una tendenza `drift_last`."""
    rng = np.random.default_rng(seed)
    rows, price = [], 600.0
    for i, day in enumerate(pd.bdate_range(start, periods=days)):
        price *= 1 + rng.normal(0, 0.004)
        for m in range(dtr.SESSION_MINUTES):
            step = rng.normal(0, 0.0004) + (drift_last if i == days - 1 else 0.0)
            close = price * (1 + step)
            ts = day + pd.Timedelta(hours=9, minutes=30 + m)
            rows.append((ts, price, max(price, close) * 1.0001, min(price, close) * 0.9999, close, 1000.0))
            price = close
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    df.index = df.index.tz_localize(dtr.ET)
    return df


# ---------------------------------------------------------------- regole dello studio
def test_bands_use_only_previous_days():
    bars = minute_bars()
    frames = dtr.session_frames(bars)
    bands = dtr.noise_bands(frames)
    last = frames["close"].index[-1]
    # cambiare il pomeriggio di oggi non cambia le bande di oggi: nessun lookahead
    altered = bars.copy()
    altered.loc[altered.index.normalize() == altered.index[-1].normalize(), "close"] *= 1.05
    bands2 = dtr.noise_bands(dtr.session_frames(altered))
    assert bands["upper"].loc[last, 60] == pytest.approx(bands2["upper"].loc[last, 60])
    # banda superiore sopra max(apertura, chiusura di ieri), inferiore sotto il minimo
    ref_hi = max(frames["open"].loc[last], bands["prev_close"].loc[last])
    assert bands["upper"].loc[last, 60] > ref_hi > bands["lower"].loc[last, 60]
    # i primi 14 giorni non hanno abbastanza storia
    assert np.isnan(bands["upper"].iloc[dtr.LOOKBACK_DAYS - 1, 60])
    assert not np.isnan(bands["upper"].iloc[dtr.LOOKBACK_DAYS, 60])


def test_decide_entries_stops_and_reversal():
    up, lo = 101.0, 99.0
    assert dtr.decide(0, 101.5, up, lo, 100.0) == (False, 1)                 # sopra la banda: long
    assert dtr.decide(0, 98.5, up, lo, 100.0) == (False, -1)                 # sotto la banda: short
    assert dtr.decide(0, 98.5, up, lo, 100.0, allow_short=False) == (False, 0)
    assert dtr.decide(0, 100.0, up, lo, 100.0) == (False, 0)                 # dentro l'area di rumore
    assert dtr.decide(1, 101.5, up, lo, 101.2) == (False, 0)                 # long confermato
    assert dtr.decide(1, 100.9, up, lo, 101.2) == (True, 0)                  # sotto banda e VWAP: stop
    assert dtr.decide(1, 101.1, up, lo, 101.2) == (False, 0)                 # stop e rientro long: si tiene
    assert dtr.decide(1, 98.0, up, lo, 100.0) == (True, -1)                  # stop e inversione short
    assert dtr.decide(-1, 99.5, up, lo, 99.2) == (True, 0)                   # short: sopra il VWAP
    assert dtr.decide(0, float("nan"), up, lo, 100.0) == (False, 0)


def test_sizing_targets_volatility_and_never_exceeds_cash():
    assert dtr.exposure_fraction(80, 0.01) == pytest.approx(0.8)            # SPY calmo: quota piena
    assert dtr.exposure_fraction(80, 0.04) == pytest.approx(0.4)            # volatilità doppia del 2%: metà
    assert dtr.exposure_fraction(95, None) == pytest.approx(0.8)            # mai oltre l'80%
    assert dtr.shares_for(100_000, 0.8, 600) == 133
    assert dtr.shares_for(100_000, 0.8, 600, cash_cap=30_000) == 50
    assert dtr.shares_for(100_000, 0.8, 600, cash_cap=-5) == 0


def test_checks_every_30_minutes_with_grace_after_restart():
    assert dtr.check_minutes()[0] == 30 and dtr.check_minutes()[-1] == 360   # 10:00 ... 15:30
    assert dtr.check_due(30, set()) is None                                  # la barra delle 10:00 non è ancora chiusa
    assert dtr.check_due(31, set()) == 30
    assert dtr.check_due(31, {30}) is None
    assert dtr.check_due(45, set()) is None                                  # oltre 10 minuti: si aspetta il successivo


def test_backtest_runs_the_bot_module_and_follows_a_trend():
    frames = dtr.session_frames(minute_bars(drift_last=0.0006))
    bands = dtr.noise_bands(frames)
    r = noise_area.simulate(frames, bands)
    assert r.iloc[-1] > 0.003                    # giornata in tendenza: long sopra la banda, chiuso con utile


# ---------------------------------------------------------------- acquisti nel panico
D = dt.date


def test_panic_episode_rebuilt_from_orders():
    orders = [{"side": "BUY", "date": D(2026, 3, 2), "client_order_id": "px-buy-1"},
              {"side": "SELL", "date": D(2026, 4, 1), "client_order_id": "px-sell-1"},
              {"side": "BUY", "date": D(2026, 11, 2), "client_order_id": "px-buy-2"},
              {"side": "BUY", "date": D(2026, 11, 9), "client_order_id": "px-buy-3"},
              {"side": "BUY", "date": D(2026, 11, 10), "client_order_id": "brd-s300-x"}]   # ordine dello swing: ignorato
    ep = pnc.episode(orders, holding=True)
    assert ep == {"tranches": 2, "first": D(2026, 11, 2), "last": D(2026, 11, 9)}
    assert pnc.episode(orders, holding=False)["tranches"] == 0


def test_panic_entry_rules():
    empty = {"tranches": 0, "first": None, "last": None}
    assert pnc.entry_amount(25.0, empty, D(2026, 11, 23), 100_000, 90_000)["amount"] == 0
    assert pnc.entry_amount(35.9, empty, D(2026, 11, 23), 100_000, 90_000)["amount"] == 10_000
    assert pnc.entry_amount(35.9, empty, D(2026, 11, 23), 100_000, 4_000)["amount"] == 4_000     # solo liquidità vera
    recent = {"tranches": 1, "first": D(2026, 11, 18), "last": D(2026, 11, 18)}
    assert pnc.entry_amount(35.9, recent, D(2026, 11, 23), 100_000, 90_000)["amount"] == 0      # 3 sedute: troppo presto
    assert pnc.entry_amount(35.9, recent, D(2026, 11, 25), 100_000, 90_000)["amount"] == 10_000
    full = {"tranches": 3, "first": D(2026, 10, 1), "last": D(2026, 10, 20)}
    assert pnc.entry_amount(40.0, full, D(2026, 11, 23), 100_000, 90_000)["amount"] == 0


def test_panic_exit_rules():
    ep = {"tranches": 2, "first": D(2026, 11, 2), "last": D(2026, 11, 9)}
    assert pnc.exit_reason(24.0, ep, D(2026, 11, 23), 500, 520) is None
    assert "paura rientrata" in pnc.exit_reason(19.5, ep, D(2026, 11, 23), 500, 520)
    assert "stop" in pnc.exit_reason(30.0, ep, D(2026, 11, 23), 440, 520)
    assert "60 sedute" in pnc.exit_reason(30.0, ep, D(2027, 2, 3), 500, 520)
    # festività: il giorno di Thanksgiving non conta come seduta
    assert pnc.sessions_between(D(2026, 11, 25), D(2026, 11, 27), core.NYSE_HOLIDAYS) == 1


# ---------------------------------------------------------------- separazione dallo swing
POSITIONS = [
    {"symbol": "SPY", "yf_symbol": "SPY", "qty": 100.0, "market_value": 60_000.0, "current_price": 600.0,
     "avg_entry_price": 598.0, "unrealized_pl": 200.0, "unrealized_plpc": 0.33, "side": "LONG", "is_crypto": False},
    {"symbol": "VOO", "yf_symbol": "VOO", "qty": 10.0, "market_value": 5_500.0, "current_price": 550.0,
     "avg_entry_price": 540.0, "unrealized_pl": 100.0, "unrealized_plpc": 1.8, "side": "LONG", "is_crypto": False},
    {"symbol": "NVDA", "yf_symbol": "NVDA", "qty": 20.0, "market_value": 4_000.0, "current_price": 200.0,
     "avg_entry_price": 190.0, "unrealized_pl": 200.0, "unrealized_plpc": 5.2, "side": "LONG", "is_crypto": False},
]


def test_swing_never_sees_tactical_positions_or_capital():
    assert core.tactical_pct() == 80.0
    assert [p["symbol"] for p in app.fetch_bot_positions(POSITIONS)] == ["NVDA"]
    acc = {"portfolio": 100_000.0, "cash": 30_000.0, "buying_power": 60_000.0, "non_marginable_buying_power": 30_000.0}
    seen = app.bot_account(acc, POSITIONS)
    assert seen["portfolio"] == pytest.approx(20_000)
    # riserva = 80.000 - 65.500 già investiti da day-trading e panico
    assert seen["non_marginable_buying_power"] == pytest.approx(30_000 - 14_500)


def test_tactical_off_with_core_spy_or_zero(monkeypatch):
    base = core.get_config()
    monkeypatch.setattr(core, "get_config", lambda: {**base, "core_spy_pct": 50.0})
    assert core.tactical_pct() == 0.0
    monkeypatch.setattr(core, "get_config", lambda: {**base, "daytrade_pct": 0.0})
    assert core.tactical_pct() == 0.0
    assert len(app.fetch_bot_positions(POSITIONS)) == 3
    with pytest.raises(ValueError):
        core._validate_config({"daytrade_pct": 95}, core.DEFAULT_CONFIG)


def test_cio_cannot_buy_tactical_symbols():
    pitch = {"symbol": "SPY", "score": 90, "package": {}}
    d = {"action": "BUY", "buy_symbol": "SPY", "sell_symbol": "", "conviction_score": 90, "allocation_pct": 10,
         "reason": "test"}
    account = {"equity": 100_000, "exposure": 0, "funds": 20_000, "funds_crypto": 20_000, "drawdown_pct": 0}
    out = core.validate_desk_decision(d, [pitch], [], account, core.get_config(), {})
    assert out["action"] == "HOLD" and "capitale tattico" in out["reason"]


def test_ledger_and_order_history_label_tactical_orders():
    assert core.NON_SWING_PREFIXES == ("core-", "dt-", "px-")


# ---------------------------------------------------------------- giro del day-trading
class Recorder:
    def __init__(self):
        self.orders = []

    def submit(self, side, qty, tag):
        self.orders.append((side, qty, tag))
        return SimpleNamespace(id=f"o{len(self.orders)}")


@pytest.fixture
def live(monkeypatch):
    rec = Recorder()
    cfg = {**core.get_config(), "auto_execute_trades": True, "panic_buy": False}
    monkeypatch.setattr(core, "get_config", lambda: cfg)
    monkeypatch.setattr(core, "submit_daytrade_order", rec.submit)
    monkeypatch.setattr(core, "wait_for_fill", lambda oid, timeout=20, log=print: SimpleNamespace(filled_avg_price="600"))
    monkeypatch.setattr(core, "get_pending_order_symbols", lambda log=print: set())
    monkeypatch.setattr(app, "get_account_summary", lambda: {"portfolio": 100_000.0, "last_equity": 100_000.0,
                                                              "non_marginable_buying_power": 100_000.0})
    app._dt_state.update(date=None, done=set(), panic_entry=None, panic_exit=None)
    return rec


def _session(monkeypatch, minute, to_close, date):
    monkeypatch.setattr(core, "market_session", lambda: {"open": True, "minute": minute, "to_close": to_close, "date": date})


def test_tick_enters_long_on_breakout(monkeypatch, live):
    bars = minute_bars(drift_last=0.0006)
    day = bars.index[-1].date()
    monkeypatch.setattr(core, "spy_minute_bars", lambda log=print: (bars[bars.index <= bars.index[-1].normalize()
                                                                          + pd.Timedelta(hours=11, minutes=1)], "test"))
    monkeypatch.setattr(app, "fetch_open_positions", lambda: [])
    _session(monkeypatch, 91, 299, day)                                       # 11:01: controllo delle 11:00
    app.daytrade_tick()
    assert live.orders and live.orders[0][0] == "BUY" and live.orders[0][2] == "long"
    assert live.orders[0][1] == dtr.shares_for(100_000, dtr.exposure_fraction(80, None), 600) or live.orders[0][1] > 0
    assert app.bot_state["tactical"]["last_check"]["time"] == "11:00"


def test_tick_closes_before_the_bell_and_leftovers_at_open(monkeypatch, live):
    monkeypatch.setattr(app, "fetch_open_positions", lambda: [dict(POSITIONS[0])])
    _session(monkeypatch, 386, 4, dt.date(2026, 11, 23))                     # 15:56: 4 minuti alla chiusura
    app.daytrade_tick()
    assert live.orders == [("SELL", 100, "exit")]
    live.orders.clear()
    short = {**POSITIONS[0], "qty": -50.0, "side": "SHORT", "market_value": -30_000.0}
    monkeypatch.setattr(app, "fetch_open_positions", lambda: [short])
    _session(monkeypatch, 3, 387, dt.date(2026, 11, 24))                     # 09:33: posizione rimasta da ieri
    app.daytrade_tick()
    assert live.orders == [("BUY", 50, "exit")]


def test_tick_does_nothing_when_market_closed_or_disabled(monkeypatch, live):
    monkeypatch.setattr(core, "market_session", lambda: {"open": False, "minute": None, "to_close": None})
    app.daytrade_tick()
    assert app.bot_state["tactical"]["state"] == "mercato chiuso" and not live.orders


# ---------------------------------------------------------------- fonte Alpaca dei titoli
def test_alpaca_assets_read_as_raw_json():
    from scouts.universe_screener import DynamicUniverseScreener

    class FakeClient:
        def get(self, path, data=None):
            assert path == "/assets"
            if data["asset_class"] == "us_equity":
                return [{"symbol": "AAPL", "tradable": True, "attributes": ["valore_nuovo"]},
                        {"symbol": "OLD", "tradable": False}]
            return [{"symbol": "BTC/USD", "tradable": True}, {"symbol": "BTC/USDT", "tradable": True}]

    screener = DynamicUniverseScreener.__new__(DynamicUniverseScreener)
    screener.alpaca_client = FakeClient()
    assert screener._alpaca_assets() == {"equity": ["AAPL"], "crypto": ["BTC"]}
