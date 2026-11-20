"""Regressioni trovate nei log di Render (10-17/11/2026)."""
import trading_core as core


def _ok_gate(agent, **extra):
    return {"agent": agent, "veto": False, "reason": "ok", **extra}


def test_risk_committee_approves_when_vwap_is_unknown(monkeypatch):
    """All'apertura la prima candela ha spesso volume zero: VWAP sconosciuto (None).

    Il gate VWAP lo lascia passare, ma il pacchetto della scheda approvata formattava None con :+.2f e
    l'eccezione faceva saltare l'intero giro dello sciame ("Errore sciame: unsupported format string ...").
    """
    monkeypatch.setattr(core, "gate_technical_liquidity", lambda p: _ok_gate("Technical & Liquidity"))
    monkeypatch.setattr(core, "gate_sentiment_compliance", lambda p, fng: _ok_gate("Sentiment & Compliance"))
    monkeypatch.setattr(core, "gate_risk_atr", lambda p, ctx: _ok_gate("Risk & ATR", stop_pct=-5.0))
    monkeypatch.setattr(core, "gate_quant_ensemble", lambda p: _ok_gate("Quant Ensemble", ensemble_score=80.0))
    pitch = {"symbol": "AAPL", "score": 90, "sector": "Tech", "anomalies": ["breakout"], "mtf_aligned": 3,
             "rvol": 2.1, "vwap_dist_pct": None, "ind": {"price": 230.0}}
    result = core.risk_committee(pitch, {"stats": {}}, None)
    assert result["approved"] is True
    assert "VWAP n/d" in result["package"]["reason"]


def test_refresh_held_evaluations_passes_real_exposure(monkeypatch):
    """Le posizioni aperte venivano rivalutate con esposizione 0%: l'Agente #3 non vedeva il capitale investito."""
    seen = {}
    monkeypatch.setattr(core, "_download", lambda syms, period, interval: {s: None for s in syms})
    monkeypatch.setattr(core, "latest_channels", lambda: {})
    monkeypatch.setattr(core, "crypto_fear_greed", lambda: None)
    monkeypatch.setattr(core, "stream_scouts_to_agents", lambda *a, **kw: seen.update(kw))
    core.refresh_held_evaluations(["AAPL", "MSFT"], log=lambda m: None, exposure_usd=89777.0, positions_count=14)
    assert seen["exposure_usd"] == 89777.0
    assert seen["positions_count"] == 14


def test_cio_prompt_accepts_unknown_vwap():
    """Una scheda approvata senza VWAP arriva anche al prompt del CIO: lì lo stesso :+.2f su None faceva cadere il ciclo."""
    pitch = {"symbol": "AAPL", "sector": "Tech", "ensemble": 80, "score": 90, "anomalies": ["breakout"],
             "mtf": {"1h": None}, "rvol": 2.1, "vwap_dist_pct": None, "beta": 1.1, "corr": 0.5,
             "package": {"target_price": 250.0, "stop_pct": -5.0}, "expires_epoch": 0}
    account = {"equity": 100000.0, "exposure": 0.0, "funds": 95000.0}
    prompt = core.build_desk_cio_prompt([pitch], [], account, {}, core.get_config())
    assert "VWAP n/d" in prompt
