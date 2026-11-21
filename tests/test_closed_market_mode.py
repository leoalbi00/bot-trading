"""Mercato USA chiuso: modalità "preparazione" (crypto negoziabili + analisi delle azioni per l'apertura)."""
import pytest

import trading_core as core
from scouts.universe_screener import DynamicUniverseScreener

SNAP = {"stocks": [{"symbol": f"S{i}", "source": "Most actives"} for i in range(6)],
        "crypto": [{"symbol": "BTC-USD", "tradable": True}, {"symbol": "ETH-USD", "tradable": True}]}


def test_default_is_preparation_and_values_are_validated():
    assert core.DEFAULT_CONFIG["closed_market_mode"] == "preparazione"
    assert core._validate_config({"closed_market_mode": "CRYPTO"}, core.DEFAULT_CONFIG)["closed_market_mode"] == "crypto"
    with pytest.raises(ValueError):
        core._validate_config({"closed_market_mode": "europa"}, core.DEFAULT_CONFIG)


def test_render_variable_overrides_the_mode(monkeypatch):
    monkeypatch.setenv("BOT_CLOSED_MARKET_MODE", "crypto")
    assert core.get_config()["closed_market_mode"] == "crypto"


def test_closed_market_universe_includes_stocks_only_in_preparation():
    screener = DynamicUniverseScreener.__new__(DynamicUniverseScreener)
    only_crypto = screener.tickers(SNAP, market_open=False)
    prepared = screener.tickers(SNAP, market_open=False, include_stocks=True)
    assert [t for t, _, _ in only_crypto] == ["BTC-USD", "ETH-USD"]
    assert {f"S{i}" for i in range(6)} | {"BTC-USD", "ETH-USD"} == {t for t, _, _ in prepared}


def test_opening_candidates_are_remembered_and_forgotten(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "SCOUT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    core._registry_cache["data"] = None
    core.remember_opening_candidate("AAPL", 82.5)
    core.remember_opening_candidate("MSFT", 77.0)
    assert core.opening_candidates() == ["AAPL", "MSFT"]          # dal più forte
    core.forget_opening_candidate("AAPL")
    assert core.opening_candidates() == ["MSFT"]


def test_old_opening_candidates_expire(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "SCOUT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    core._registry_cache["data"] = None
    core.remember_opening_candidate("AAPL", 82.5)
    later = core.time.time() + core.OPENING_CANDIDATE_TTL_SEC + 60
    monkeypatch.setattr(core, "_now_epoch", lambda: later)
    assert core.opening_candidates() == []


def test_foreign_markets_snapshot_reports_daily_change(monkeypatch):
    """Borse estere a mercato USA chiuso: solo informazione (variazione del giorno), nessuna decisione."""
    import pandas as pd
    idx = pd.date_range("2026-11-19", periods=2, freq="D")
    frames = {"^GDAXI": pd.DataFrame({"Close": [20000.0, 20200.0]}, index=idx),
              "^N225": pd.DataFrame({"Close": [40000.0, 39600.0]}, index=idx)}
    monkeypatch.setattr(core, "_daily_frames", lambda tickers: {t: frames.get(t) for t in tickers})
    snap = {m["symbol"]: m for m in core.foreign_markets_snapshot()}
    assert snap["^GDAXI"]["change_pct"] == 1.0 and snap["^N225"]["change_pct"] == -1.0
    assert snap["^GDAXI"]["name"].startswith("Germania") and "^HSI" not in snap   # senza dati: escluso


def test_closed_market_buy_goes_to_opening_list_only_in_preparation(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "SCOUT_REGISTRY_PATH", str(tmp_path / "registry.json"))
    core._registry_cache["data"] = None
    buy = {"agent_05_cio": {"decision": "BUY", "score": 84.0}, "agent_06_guardian": {"approved": True}}
    monkeypatch.setattr(core, "quant_rationale", lambda sym, max_age_sec=120: buy)
    stock = {"symbol": "AAPL", "score": core.PIPELINE_MIN_TA_SCORE, "tradable": True}
    base = core.get_config
    monkeypatch.setattr(core, "get_config", lambda: {**base(), "closed_market_mode": "crypto"})
    core._prepare_for_opening(stock)
    assert core.opening_candidates() == []
    monkeypatch.setattr(core, "get_config", lambda: {**base(), "closed_market_mode": "preparazione"})
    core._prepare_for_opening({**stock, "score": core.PIPELINE_MIN_TA_SCORE - 1})   # tecnica troppo debole
    assert core.opening_candidates() == []
    core._prepare_for_opening(stock)
    assert core.opening_candidates() == ["AAPL"]
