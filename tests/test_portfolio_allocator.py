import asyncio

import pandas as pd
import pytest

import app
import quant_core
import trading_core as core
from agents import portfolio_allocator as pa
from agents.agent_04_macro import MacroSentimentAgent
from agents.agent_05_cio import CIOStrategistAgent
from agents.agent_06_sentinel import PortfolioGuardianAgent

EQUITY = 100000.0
CHANNELS = {"macro": {"vix": 16.0, "trend_up": {"stock": True, "crypto": True}, "regime": {"stock": "RISK-ON", "crypto": "RISK-ON"}}}


def account(exposure=0.0):
    return {"equity": EQUITY, "exposure": exposure, "funds": EQUITY - exposure, "funds_crypto": EQUITY - exposure, "drawdown_pct": 0.0}


def pitch(symbol, ensemble=80, stop=-5.0, rank=0.85):
    return {"symbol": symbol, "ensemble": ensemble, "score": 60, "trend_rank": rank,
            "package": {"stop_pct": stop, "entry_price": 100.0, "target_price": 115.0, "horizon": "INTRADAY_MOMENTUM"}}


def holding(symbol, value=8000.0, risk=400.0, degraded=False):
    return {"symbol": symbol, "yf_symbol": symbol, "market_value": value, "weight_pct": value / EQUITY * 100, "pnl_pct": 1.0,
            "score": 60, "status": "OK", "degraded": degraded, "thesis_note": "test", "open_risk": risk}


def buy(symbol):
    return {"action": "BUY", "buy_symbol": symbol, "sell_symbol": "", "reason": "test"}


@pytest.mark.parametrize("trend,vix,expected", [(True, 15, 1.0), (True, 26, 0.6), (False, 22, 0.35), (False, 31, 0.0), (True, None, 1.0)])
def test_regime_scale(trend, vix, expected):
    assert pa.regime_scale(trend, vix) == expected


@pytest.mark.parametrize("dd,expected", [(0, 1.0), (-4.9, 1.0), (-6, 0.5), (-12, 0.25)])
def test_drawdown_scale(dd, expected):
    assert pa.drawdown_scale(dd) == expected


def test_limits_shrink_with_regime_and_never_use_margin():
    good, bad = pa.risk_limits(True, 15), pa.risk_limits(False, 22, -6)
    assert good["gross_pct"] == 95 and good["heat_pct"] == 8
    assert bad["gross_pct"] < 40 and bad["risk_pct"] < good["risk_pct"] / 4


def test_more_volatile_titles_get_less_capital():
    limits = pa.risk_limits(True, 15)
    quiet = pa.size_trade(EQUITY, 0, EQUITY, 0, 0, limits, pa.stop_pct(2.0), rank=0.7)
    wild = pa.size_trade(EQUITY, 0, EQUITY, 0, 0, limits, pa.stop_pct(3.0), rank=0.7)
    assert quiet["amount"] > wild["amount"] > 0


def test_size_never_exceeds_cap_or_cash_floor():
    limits = pa.risk_limits(True, 15)
    assert pa.size_trade(EQUITY, 0, EQUITY, 0, 0, limits, 1.5, rank=1.0)["allocation_pct"] == pa.MAX_POSITION_PCT
    sized = pa.size_trade(EQUITY, 90000, 10000, 0, 5, limits, 5.0, rank=1.0)
    assert sized["amount"] == pytest.approx(5000)


def test_crypto_cap():
    limits = pa.risk_limits(True, 15)
    assert pa.size_trade(EQUITY, 19500, EQUITY, 0, 1, limits, 5.0, crypto=True, crypto_exposure=19500)["amount"] == 0


def test_open_risk_of_a_runner_is_smaller():
    assert pa.open_risk_usd(10000, 0, -5) == pytest.approx(500)
    assert pa.open_risk_usd(10000, 10, 0.05) < pa.open_risk_usd(10000, 0, -5) * 2.1
    assert pa.open_risk_usd(10000, 1, 2) == 0


@pytest.mark.parametrize("status", ["NO_NEWS", "STALE"])
def test_missing_news_is_not_a_veto(status):
    assert MacroSentimentAgent().news_veto({"status": status, "impact_score": 0.0}, 95) is None


def test_negative_news_stays_a_veto():
    assert MacroSentimentAgent().news_veto({"status": "OK", "impact_score": -0.5, "thesis_summary": "x"}, 95)


def test_trade_is_possible_without_news():
    cio = CIOStrategistAgent()
    assert cio.ensemble_score(72, 50, 50) >= cio.buy_threshold
    assert cio.ensemble_score(72, 90, 50) > cio.ensemble_score(72, 50, 50)


def test_full_portfolio_is_not_a_veto_so_no_cooldown():
    full = {"slots_full": True, "exposure_room_pct": 0, "positions": 15, "max_positions": 15}
    res = CIOStrategistAgent().synthesize({"quant_score": 80}, {"metrics": {"order_flow_imbalance": 0.0}},
                                          {"risk_approved": True, "safety_net": full, "position_parameters": {"position_units": 1.0}},
                                          {"macro_approved": True, "news_score": 50.0}, {"guardian_approved": True}, symbol="AAA", price=10.0)
    assert res["final_decision"] == "BUY"


def test_rank_is_computed_on_the_universe():
    core._trend_book.clear()
    results = [{"symbol": f"T{i}", "trend": {"momentum": float(i), "trend_ok": True}} for i in range(100)]
    core.apply_trend_rank(results)
    assert results[-1]["trend_score"] == 100 and results[85]["trend_score"] > 70
    assert results[10]["trend_score"] <= 60
    core._trend_book.clear()


def test_score_outside_trend_never_enters():
    assert core.trend_score(0.95, False) < CIOStrategistAgent().buy_threshold


def test_pipeline_buys_a_trending_stock_without_news():
    engine = quant_core.QuantitativeTradingCore(news_provider=lambda s: {"status": "NO_NEWS", "impact_score": 0.0, "news_score": 50.0})
    payload = quant_core.build_scout_payload("AAA", quant_core.dummy_ohlcv(1, 300), account_balance=EQUITY, scout_id="1",
                                             scout_meta={"trend_score": 85.0, "atr_pct": 2.0}, is_crypto=False)
    weak = quant_core.build_scout_payload("BBB", quant_core.dummy_ohlcv(2, 300), account_balance=EQUITY, scout_id="2",
                                          scout_meta={"trend_score": 55.0, "atr_pct": 2.0, "rvol": 5.0, "score": 80}, is_crypto=False)
    try:
        asyncio.run(engine.run_swarm_cycle([payload, weak]))
        assert engine.rationale_for("AAA")["agent_05_cio"]["decision"] == "BUY"
        assert engine.rationale_for("BBB") is None
    finally:
        engine.shutdown()


def test_six_positions_no_longer_block_new_buys():
    held = [holding(f"H{i}") for i in range(6)]
    final = core.validate_desk_decision(buy("NEW"), [pitch("NEW")], held, account(48000), core.get_config(), CHANNELS)
    assert final["action"] == "BUY" and final["buy_amount"] > 0


def test_ai_cannot_choose_the_size():
    d = {**buy("NEW"), "allocation_pct": 50, "dynamic_stop_loss_pct": -0.5}
    final = core.validate_desk_decision(d, [pitch("NEW")], [], account(), core.get_config(), CHANNELS)
    assert final["allocation_pct"] <= pa.MAX_POSITION_PCT and final["dynamic_stop_loss_pct"] == -5.0


def test_exhausted_risk_budget_holds():
    held = [holding(f"H{i}", risk=1500) for i in range(5)]
    final = core.validate_desk_decision(buy("NEW"), [pitch("NEW")], held, account(40000), core.get_config(), CHANNELS)
    assert final["action"] == "HOLD" and "budget" in final["reason"]


def test_super_conviction_rotates_only_degraded_theses():
    held = [holding(f"H{i}", risk=1500) for i in range(5)]
    assert core.validate_desk_decision(buy("NEW"), [pitch("NEW", ensemble=95)], held, account(40000), core.get_config(), CHANNELS)["action"] == "HOLD"
    held[2]["degraded"] = True
    final = core.validate_desk_decision(buy("NEW"), [pitch("NEW", ensemble=95)], held, account(40000), core.get_config(), CHANNELS)
    assert final["action"] == "ROTATE" and final["sell_symbol"] == "H2"


def test_panic_regime_blocks_and_crypto_needs_btc_trend():
    panic = {"macro": {"vix": 35.0, "trend_up": {"stock": False, "crypto": True}}}
    assert core.validate_desk_decision(buy("NEW"), [pitch("NEW")], [], account(), core.get_config(), panic)["action"] == "HOLD"
    no_btc = {"macro": {"vix": 15.0, "trend_up": {"stock": True, "crypto": False}}}
    assert "BTC" in core.validate_desk_decision(buy("BTC-USD"), [pitch("BTC-USD")], [], account(), core.get_config(), no_btc)["reason"] \
        or core.crypto_night_blocked()


def test_guardian_trend_break_exit():
    g = PortfolioGuardianAgent().evaluate_position(100, 101, 102, -5.0, 2.0, False, signals={"trend_break": "sotto EMA50"})
    assert g["action"] == "TREND_BREAK" and "TREND_BREAK" in app.GUARDIAN_EXITS


def test_small_vix_rise_is_not_a_news_shock():
    calm = PortfolioGuardianAgent().evaluate_position(100, 101, 102, -5.0, 2.0, False, signals={"vix": 19.0, "vix_at_entry": 15.0})
    stress = PortfolioGuardianAgent().evaluate_position(100, 101, 102, -5.0, 2.0, False, signals={"vix": 26.0, "vix_at_entry": 15.0})
    assert calm["action"] == "HOLD" and stress["action"] == "NEWS_SHOCK"


def test_trend_features_ignore_illiquid_and_todays_bar():
    idx = pd.date_range(end=core.now_local().date(), periods=200, freq="D", tz="UTC")
    close = pd.Series([50 + i * 0.2 for i in range(200)], index=idx)
    liquid = pd.DataFrame({"Close": close, "Volume": 5_000_000.0})
    assert core.trend_features("AAA", liquid)["trend_ok"]
    assert core.trend_features("AAA", liquid.assign(Volume=1000.0)) is None
    assert len(core.completed_daily_close(liquid)) == 199


@pytest.fixture
def desk(monkeypatch):
    """Ciclo del CIO con conto al 33% investito, 4 posizioni e l'IA in HOLD: lo stato reale del conto."""
    positions = [{"symbol": s, "yf_symbol": s, "is_crypto": False, "qty": 10.0, "market_value": 8000.0, "current_price": 800.0,
                  "unrealized_pl": 100.0, "unrealized_plpc": 1.0, "avg_entry_price": 790.0, "side": "LONG"} for s in ("HSIC", "MET", "OWL", "REGN")]
    inbox = [{**pitch(s, ensemble=e), "rvol": 1.5, "expires_epoch": core.time.time() + 600, "sector": "x", "mtf": {}, "anomalies": [],
              "vwap_dist_pct": 0.1, "beta": 1, "corr": 0.5} for s, e in (("AAA", 90), ("BBB", 85), ("CCC", 80), ("DDD", 75), ("EEE", 72))]
    bought = []
    base_cfg = core.get_config
    monkeypatch.setattr(core, "get_config", lambda: {**base_cfg(), "core_spy_pct": 0.0})   # bot senza core SPY
    monkeypatch.setattr(app, "fetch_open_positions", lambda: positions)
    monkeypatch.setattr(app, "get_account_summary", lambda: {"portfolio": EQUITY, "cash": 68000.0, "buying_power": 300000.0,
                                                             "non_marginable_buying_power": 68000.0, "last_equity": EQUITY})
    monkeypatch.setattr(app, "execute_buy", lambda sym, amount, *a, **k: bought.append((sym, amount)) or object())
    monkeypatch.setattr(core, "cio_inbox", lambda: inbox)
    monkeypatch.setattr(core, "ask_desk_cio", lambda *a, **k: ({"action": "HOLD", "buy_symbol": "", "sell_symbol": "", "reason": "ia"}, "groq"))
    monkeypatch.setattr(core, "latest_channels", lambda: CHANNELS)
    monkeypatch.setattr(core, "get_pending_order_symbols", lambda log=print: set())
    monkeypatch.setattr(core, "is_market_open", lambda log=print: True)
    monkeypatch.setattr(core, "sync_ledger", lambda log=print: {"trades": [], "open": {}})
    monkeypatch.setattr(core, "market_analyst", lambda *a, **k: {})
    monkeypatch.setattr(core, "refresh_held_evaluations", lambda *a, **k: None)
    monkeypatch.setattr(core, "drawdown_controller", lambda *a, **k: {"blocked": False, "drawdown_pct": 0.0})
    monkeypatch.setattr(core, "volatility_agent", lambda *a, **k: ({}, {p["symbol"]: -5.0 for p in positions}, {}))
    monkeypatch.setattr(core, "thesis_degraded", lambda s: (False, "intatta"))
    monkeypatch.setattr(core, "record_cio_outcome", lambda *a, **k: None)
    return bought


def test_cycle_reinvests_idle_cash_even_with_ai_on_hold(desk):
    assert app.run_trading_cycle(trigger="test")
    assert len(desk) == core.MAX_BUYS_PER_CYCLE
    assert desk[0][0] == "AAA" and sum(a for _, a in desk) > 30000


def test_liquidity_wakes_the_cio():
    app.cio_wake.clear()
    app.request_cio("liquidità liberata da X")
    assert app.cio_wake.is_set() and "liquidità" in app.cio_trigger["reason"]
    app.cio_wake.clear()
    app.cio_trigger.update(reason="", urgent=False)


def test_one_close_below_ema100_does_not_flip_the_regime():
    # 02/11/2026: SPY 752.10 sotto la EMA100 755.09 per una sola chiusura -> l'esposizione non deve crollare al 33%
    assert pa.trend_up_confirmed([769.36, 755.72, 752.10], [755.14, 755.15, 755.09]) is True
    assert pa.trend_up_confirmed([754.0, 752.0, 750.0], [755.0, 755.0, 755.0]) is False
    assert pa.trend_up_confirmed([750.0, 760.0, 750.0], [755.0, 755.0, 755.0]) is True
    assert pa.trend_up_confirmed([750.0], [755.0]) is True   # storia insufficiente: nessun taglio


# ---------------------------------------------------------------- Core SPY + satellite
from agents import core_allocation as ca


def test_core_rebalances_only_outside_the_band():
    assert ca.rebalance(EQUITY, 0.0, 80, True) == {**ca.rebalance(EQUITY, 0.0, 80, True), "side": "BUY", "amount": 76000.0}
    assert ca.rebalance(EQUITY, 75000.0, 80, True) is None                      # scarto 1% < banda 3%
    down = ca.rebalance(EQUITY, 76000.0, 80, False)                             # SPY sotto trend: 80% x 33.25%
    assert down["side"] == "SELL" and down["amount"] == 76000.0 - 26600.0
    assert ca.rebalance(EQUITY, 0.0, 0, True) is None


def test_satellite_account_hides_the_core_cash():
    acc = {"portfolio": EQUITY, "cash": 90000.0, "buying_power": 90000.0, "non_marginable_buying_power": 90000.0, "last_equity": EQUITY}
    sat = ca.satellite_account(acc, 80, 10000.0)       # core da 80k con 10k investiti: 70k di liquidità riservata
    assert sat["portfolio"] == 20000.0 and sat["non_marginable_buying_power"] == 20000.0
    assert ca.satellite_account(acc, 0, 0.0) is acc


def test_bot_never_buys_the_core_symbol(monkeypatch):
    cfg = {**core.get_config(), "core_spy_pct": 80.0}
    final = core.validate_desk_decision(buy("SPY"), [pitch("SPY")], [], account(), cfg, CHANNELS)
    assert final["action"] == "HOLD" and "core" in final["reason"]


@pytest.fixture
def with_core(monkeypatch, desk):
    base = core.get_config
    monkeypatch.setattr(core, "get_config", lambda: {**base(), "core_spy_pct": 80.0, "auto_execute_trades": True})
    orders = []
    monkeypatch.setattr(core, "submit_core_order", lambda side, amount: orders.append((side, amount)) or object())
    return desk, orders


def test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(with_core):
    bought, orders = with_core
    assert app.run_trading_cycle(trigger="test")
    assert orders == [("BUY", 68000.0)]    # obiettivo 76k, limitato alla liquidità vera (68k)
    assert bought == []                     # 32k di posizioni del bot superano già la quota satellite (20k)


def test_core_position_is_invisible_to_guardian_and_radar(monkeypatch):
    base = core.get_config
    monkeypatch.setattr(core, "get_config", lambda: {**base(), "core_spy_pct": 80.0})
    spy = {"symbol": "SPY", "market_value": 76000.0}
    monkeypatch.setattr(app, "fetch_open_positions", lambda: [spy, {"symbol": "NVDA", "market_value": 5000.0}])
    assert [p["symbol"] for p in app.fetch_bot_positions()] == ["NVDA"]
    monkeypatch.setattr(core, "get_config", lambda: {**base(), "core_spy_pct": 0.0})
    assert len(app.fetch_bot_positions()) == 2   # core disattivato: SPY torna un titolo qualsiasi


def test_guardian_moves_stop_to_breakeven_after_one_r():
    g = PortfolioGuardianAgent()
    # stop -6% (1R = 6%): il titolo è salito a +6.5% e ora è a -0.5% -> esce a breakeven, non aspetta il -6%
    out = g.evaluate_position(entry=100.0, price=99.5, peak=106.5, stop_pct=-6.0, atr_pct=2.0, is_crypto=False)
    assert out["hit"] and out["action"] == "BREAKEVEN_STOP" and out["breakeven"]
    # picco sotto 1R: lo stop resta quello iniziale e la posizione resta aperta
    out = g.evaluate_position(entry=100.0, price=99.5, peak=105.0, stop_pct=-6.0, atr_pct=2.0, is_crypto=False)
    assert not out["hit"] and out["effective_stop_pct"] == -6.0
