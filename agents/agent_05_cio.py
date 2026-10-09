import numpy as np
from typing import Dict, Any, Optional

# Fusion Engine
ENSEMBLE_WEIGHTS = {"quant": 0.50, "news": 0.35, "ofi": 0.15}
ENTRY_THRESHOLD = 72.0             # Ensemble Score minimo d'ingresso: sotto si scarta (niente overtrading)
SUPER_CONVICTION_THRESHOLD = 90.0  # classe SUPER_CONVICTION: sizing fino al 50% autorizzato dall'Agente #3

INTRADAY_MOMENTUM, SWING_CATALYST = "INTRADAY_MOMENTUM", "SWING_CATALYST"
STANDARD, SUPER_CONVICTION = "STANDARD", "SUPER_CONVICTION"


def ofi_to_score(ofi: Optional[float]) -> float:
    """OFI -1..+1 dell'Agente #2 -> Microstructure_OFI 0-100 (50 = book bilanciato)."""
    if ofi is None or not np.isfinite(ofi):
        return 50.0
    return float((np.clip(ofi, -1.0, 1.0) + 1.0) * 50.0)


def build_buy_thesis(symbol: str, price: Optional[float], quant_score: float, news_impact: float,
                     thesis_summary: str, ofi: Optional[float]) -> str:
    """Scheda di ingresso: "Acquistato [TICKER] a $[PREZZO]: Quant Score [X], News Impact [Y] ('[TESI]'), OFI [Z]."."""
    price_txt = f"${price:,.4f}".rstrip("0").rstrip(".") if price else "$N/D"
    ofi_txt = f"{ofi:+.2f}" if ofi is not None else "N/D"
    return (f"Acquistato {symbol} a {price_txt}: Quant Score {quant_score:.1f}, News Impact {news_impact:+.2f} "
            f"('{thesis_summary or 'nessuna tesi informativa'}'), OFI {ofi_txt}.")


class CIOStrategistAgent:
    """
    AGENTE #5: Chief Investment Officer (CIO) - Fusion Engine
    - Ensemble_Score = Quant_Score x 0.50 + Groq_News_Score x 0.35 + Microstructure_OFI x 0.15
    - Soglia d'ingresso: Ensemble >= 72, tutto il resto viene scartato
    - Classe: SUPER_CONVICTION (Ensemble >= 90) o STANDARD
    - Orizzonte: SWING_CATALYST (catalizzatore strutturale ad alto impatto) o INTRADAY_MOMENTUM
    - Hard Veto (Risk, Macro/News, Guardian), limiti di portafoglio per i trade non SUPER_CONVICTION
    - Scheda di ingresso (buy_thesis) e routing di esecuzione
    """
    def __init__(
        self,
        buy_threshold: float = ENTRY_THRESHOLD,
        sell_threshold: float = 30.0,
        super_conviction_threshold: float = SUPER_CONVICTION_THRESHOLD,
        min_conviction_multiplier: float = 0.5,
    ):
        self.agent_id = "AGENT_05_CIO_STRATEGIST"
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.super_conviction_threshold = super_conviction_threshold
        self.min_conviction_multiplier = min_conviction_multiplier
        self.weights = dict(ENSEMBLE_WEIGHTS)

    def ensemble_score(self, quant: float, news: float, ofi_score: float) -> float:
        score = quant * self.weights["quant"] + news * self.weights["news"] + ofi_score * self.weights["ofi"]
        return float(np.clip(score, 0.0, 100.0))

    def best_case_score(self, quant: float, ofi_score: float) -> float:
        """Ensemble massimo raggiungibile con la notizia migliore possibile (News Score 100)."""
        return self.ensemble_score(quant, 100.0, ofi_score)

    def trade_class(self, score: float) -> str:
        return SUPER_CONVICTION if score >= self.super_conviction_threshold else STANDARD

    @staticmethod
    def horizon(swing_catalyst: bool) -> str:
        return SWING_CATALYST if swing_catalyst else INTRADAY_MOMENTUM

    def determine_execution_router(self, micro_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Seleziona l'algoritmo di esecuzione ottimale per minimizzare lo slippage e l'impatto sul book.
        """
        if not micro_metrics:
            return {"execution_style": "LIMIT_ORDER", "reason": "DEFAULT_SAFE_PASSIVE"}

        liquidity_void = micro_metrics.get("liquidity_void_detected", False)
        vpin = micro_metrics.get("vpin_toxicity", 0.5)
        iceberg = micro_metrics.get("iceberg_order", {}).get("iceberg_detected", False)
        rvol = micro_metrics.get("rvol", 1.0)

        if liquidity_void or rvol > 3.0:
            return {
                "execution_style": "TWAP_SLICED",
                "reason": "HIGH_VOLATILITY_OR_LIQUIDITY_VOID",
                "slice_chunks": 5,
                "time_window_seconds": 300
            }
        elif iceberg:
            return {
                "execution_style": "PASSIVE_LIMIT_QUEUE_JOIN",
                "reason": "ICEBERG_WALL_DETECTED_JOIN_QUEUE",
                "offset_ticks": 1
            }
        elif vpin < 0.65:
            return {
                "execution_style": "AGGRESSIVE_MARKET_SWEEP",
                "reason": "LOW_TOXICITY_HIGH_EXECUTION_SPEED"
            }
        else:
            return {
                "execution_style": "STANDARD_LIMIT_ORDER",
                "reason": "BALANCED_ORDER_BOOK"
            }

    def synthesize(
        self,
        agent_01_quant_res: Dict[str, Any],
        agent_02_micro_res: Dict[str, Any],
        agent_03_risk_res: Dict[str, Any],
        agent_04_macro_res: Dict[str, Any],
        agent_06_guardian_res: Optional[Dict[str, Any]] = None,
        symbol: str = "",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Pipeline Esecutiva e di Sintesi Finale dell'Agente #5.
        """
        # 1. Componenti del Fusion Engine (calcolati anche in caso di veto: l'analisi resta visibile)
        score_quant = float(agent_01_quant_res.get("quant_score", 50.0))
        micro_metrics = agent_02_micro_res.get("metrics", {}) or {}
        ofi = micro_metrics.get("order_flow_imbalance")
        score_ofi = ofi_to_score(ofi)
        score_news = float(agent_04_macro_res.get("news_score", 50.0))
        news = agent_04_macro_res.get("news") or {}
        news_impact = float(news.get("impact_score") or 0.0)

        cio_score = self.ensemble_score(score_quant, score_news, score_ofi)
        trade_class = self.trade_class(cio_score)
        horizon = self.horizon(bool(agent_04_macro_res.get("swing_catalyst")))
        agent_scores = {
            "quant": score_quant, "news": score_news, "ofi": round(score_ofi, 2),
            "microstructure": agent_02_micro_res.get("microstructure_score", 50.0),
            "risk": agent_03_risk_res.get("risk_score", 50.0), "macro": agent_04_macro_res.get("macro_score", 50.0),
        }
        common = {
            "agent_id": self.agent_id,
            "cio_ensemble_score": round(cio_score, 2),
            "agent_scores": agent_scores,
            "weights_used": dict(self.weights),
            "trade_class": trade_class,
            "horizon": horizon,
            "news_impact": news_impact,
            "ofi": ofi,
        }

        # 2. Controllo Veto Hard (Risk Manager, Macro/News di Groq, Guardian)
        vetoes = []
        if not agent_03_risk_res.get("risk_approved", False):
            vetoes.append(("VETO RISK", agent_03_risk_res.get("reason", "RISK_REJECTED")))
        if not agent_04_macro_res.get("macro_approved", False):
            vetoes.append(("VETO MACRO", agent_04_macro_res.get("reason", "MACRO_BLACKOUT")))
        if agent_06_guardian_res is not None and not agent_06_guardian_res.get("guardian_approved", True):
            vetoes.append(("VETO GUARDIAN", agent_06_guardian_res.get("reason", "PORTFOLIO_LIMIT")))

        # 3. Limiti di portafoglio (Agente #3): un trade STANDARD non entra se il portafoglio è pieno;
        #    un SUPER_CONVICTION sì, con rotazione delle sole tesi degradate o taglia ridotta alla cassa
        net = agent_03_risk_res.get("safety_net") or {}
        needs_rotation = bool(net.get("slots_full") or (net and net.get("exposure_room_pct", 100.0) <= 0.5))
        if needs_rotation and cio_score >= self.buy_threshold and trade_class != SUPER_CONVICTION and agent_06_guardian_res is not None:
            why = (f"{net.get('positions')}/{net.get('max_positions')} posizioni" if net.get("slots_full")
                   else f"esposizione {net.get('exposure_pct')}% al limite {net.get('max_exposure_pct')}%")
            vetoes.append(("VETO RISK", f"Safety Net: {why} (solo un SUPER_CONVICTION può ruotare capitale)"))

        if vetoes:
            return {
                **common,
                "final_decision": "NO_TRADE",
                "veto": " + ".join(dict.fromkeys(label for label, _ in vetoes)),
                "reason": " | ".join(f"{label}: {why}" for label, why in vetoes),
                "execution_plan": None
            }

        # 4. Soglia d'ingresso: Ensemble >= 72
        if cio_score >= self.buy_threshold:
            decision = "BUY"
            conviction_factor = (cio_score - self.buy_threshold) / (100.0 - self.buy_threshold)
        elif cio_score <= self.sell_threshold:
            decision = "SELL"
            conviction_factor = (self.sell_threshold - cio_score) / self.sell_threshold
        else:
            return {
                **common,
                "final_decision": "HOLD",
                "reason": f"ENSEMBLE {round(cio_score, 2)} < {self.buy_threshold:.0f}: scartato (no overtrading)",
                "execution_plan": None
            }

        # 5. Sizing: base dell'Agente #3, scalata per convinzione; SUPER_CONVICTION fino al tetto autorizzato
        base_position_params = agent_03_risk_res.get("position_parameters", {})
        base_units = base_position_params.get("position_units", 0.0)
        scaling_multiplier = self.min_conviction_multiplier + (1.0 - self.min_conviction_multiplier) * conviction_factor
        final_units = float(round(base_units * scaling_multiplier, 4))
        max_alloc = (base_position_params.get("super_conviction_max_allocation_pct")
                     if trade_class == SUPER_CONVICTION else base_position_params.get("max_allocation_pct"))

        buy_thesis = build_buy_thesis(symbol or "?", price, score_quant, news_impact, news.get("thesis_summary") or "", ofi) \
            if decision == "BUY" else None

        return {
            **common,
            "final_decision": decision,
            "reason": (f"{trade_class} {horizon} {decision} (Ensemble {round(cio_score, 2)} = Q {score_quant:.1f}x0.50 + "
                       f"News {score_news:.1f}x0.35 + OFI {score_ofi:.1f}x0.15)"),
            "conviction_factor": round(conviction_factor, 2),
            "needs_rotation": needs_rotation and decision == "BUY",
            "buy_thesis": buy_thesis,
            "final_trade_parameters": {
                "side": decision,
                "position_units": final_units,
                "max_allocation_pct": max_alloc,
                "stop_loss_price": base_position_params.get("stop_loss_price", 0.0),
                "stop_loss_pct": base_position_params.get("stop_loss_pct"),
                "take_profit_price": base_position_params.get("take_profit_price", 0.0),
                "risk_usd": base_position_params.get("risk_amount_usd", 0.0)
            },
            "execution_plan": self.determine_execution_router(micro_metrics)
        }
