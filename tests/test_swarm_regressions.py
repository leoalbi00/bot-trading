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


def _long_pitch(i):
    gate = {"agent": "Technical & Liquidity", "detail": "RVOL 2.3x, MTF 3/3, RSI 1h 61, 4h 58, 1d 63, prezzo sopra il VWAP, "
                                                         "liquidità ok, spread ok, nessuna trappola RSI, ROC sotto la soglia " * 2}
    return {"symbol": f"T{i:02d}", "sector": "Healthcare", "ensemble": 70 + i, "trade_class": "STANDARD", "score": 80,
            "anomalies": ["breakout"], "mtf": {"1h": {"bullish": True, "rsi": 61}}, "rvol": 2.3, "vwap_dist_pct": 0.4,
            "beta": 1.1, "corr": 0.5, "review": {"gates": [gate] * 4}, "expires_epoch": 0,
            "package": {"buy_thesis": "Tesi lunga " * 20, "target_price": 250.0, "stop_pct": -6.5}}


def test_cio_prompt_fits_groq_free_tier_with_many_pitches():
    """Con molte schede il prompt superava gli 8.000 token al minuto di Groq (errore 413): ora resta nel budget."""
    account = {"equity": 95000.0, "exposure": 20000.0, "funds": 70000.0}
    holdings = [{"symbol": f"H{i}", "market_value": 2000, "weight_pct": 2.0, "pnl_pct": 1.0, "thesis_note": "x"} for i in range(13)]
    prompt = core.build_desk_cio_prompt([_long_pitch(i) for i in range(30)], holdings, account, {}, core.get_config())
    total = core.estimate_tokens(prompt + core.DESK_CIO_SYSTEM_PROMPT) + core.CIO_LLM_MAX_TOKENS
    assert total <= core.CIO_PROMPT_TOKEN_BUDGET < 8000
    assert "T29" in prompt and "T28" in prompt          # le schede con l'Ensemble più alto restano
    assert "T00 " not in prompt and "T10 " not in prompt  # le più deboli no
    assert sum(line.startswith("  - T") for line in prompt.splitlines()) <= core.CIO_PROMPT_MAX_PITCHES


def test_news_llm_limit_matches_measured_groq_latency():
    """Groq risponde in media in 1,0-1,3 s ma metà delle chiamate superava i 2 s: il limite delle notizie è 4 s."""
    import time
    from agents.agent_07_chop import GROQ_TIMEOUT_S, ChopWatchdog
    assert GROQ_TIMEOUT_S == 4.0
    assert ChopWatchdog().llm_timeout_s == GROQ_TIMEOUT_S
    guard = ChopWatchdog(llm_timeout_s=0.2)
    assert guard.guarded_llm_call(lambda: "ok") == "ok"
    assert guard.guarded_llm_call(lambda: time.sleep(0.5) or "tardi") is None
    assert guard.llm_stats["timeouts"] == 1
