import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class CIOStrategistAgent:
    """
    AGENTE #5: Chief Investment Officer (CIO) Strategist & Adaptive Execution Desk
    - Ensemble Scoring & Dynamic Weighting Matrix
    - Hard Veto Enforcement (Risk & Macro)
    - Optimal Execution Routing (TWAP / VWAP / Market Aggressive / Limit Queue)
    - Conviction-Based Final Sizing Allocation
    """
    def __init__(
        self, 
        buy_threshold: float = 68.0, 
        sell_threshold: float = 32.0,
        min_conviction_multiplier: float = 0.5
    ):
        self.agent_id = "AGENT_05_CIO_STRATEGIST"
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.min_conviction_multiplier = min_conviction_multiplier

    def get_dynamic_weights(self, is_high_volatility: bool = False) -> Dict[str, float]:
        """
        Determina i pesi dell'Ensemble in base al regime di volatilità del mercato.
        """
        if is_high_volatility:
            # In alta volatilità, domina la gestione del rischio e la macro
            return {
                "quant": 0.20,
                "microstructure": 0.20,
                "risk": 0.35,
                "macro": 0.25
            }
        else:
            # In regime normale, domina l'alpha matematico e l'order flow
            return {
                "quant": 0.35,
                "microstructure": 0.25,
                "risk": 0.20,
                "macro": 0.20
            }

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
        agent_04_macro_res: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Pipeline Esecutiva e di Sintesi Finale dell'Agente #5.
        """
        # 1. Controllo Veto Hard (Risk Manager & Macro Agent)
        risk_approved = agent_03_risk_res.get("risk_approved", False)
        macro_approved = agent_04_macro_res.get("macro_approved", False)

        if not risk_approved:
            return {
                "agent_id": self.agent_id,
                "final_decision": "NO_TRADE",
                "reason": f"VETO_TRIGGERED_BY_RISK_MANAGER: {agent_03_risk_res.get('reason', 'RISK_REJECTED')}",
                "cio_ensemble_score": 0.0,
                "execution_plan": None
            }

        if not macro_approved:
            return {
                "agent_id": self.agent_id,
                "final_decision": "NO_TRADE",
                "reason": f"VETO_TRIGGERED_BY_MACRO_AGENT: {agent_04_macro_res.get('reason', 'MACRO_BLACKOUT')}",
                "cio_ensemble_score": 0.0,
                "execution_plan": None
            }

        # 2. Estrazione Punteggi Singoli Agenti
        score_quant = agent_01_quant_res.get("quant_score", 50.0)
        score_micro = agent_02_micro_res.get("microstructure_score", 50.0)
        score_risk = agent_03_risk_res.get("risk_score", 50.0)
        score_macro = agent_04_macro_res.get("macro_score", 50.0)

        # 3. Determinazione Regime ed Ensemble Score
        is_high_vol = agent_03_risk_res.get("metrics", {}).get("cvar_99_tail_risk", 0.0) > 0.06
        weights = self.get_dynamic_weights(is_high_volatility=is_high_vol)

        cio_score = (
            (score_quant * weights["quant"]) +
            (score_micro * weights["microstructure"]) +
            (score_risk * weights["risk"]) +
            (score_macro * weights["macro"])
        )
        cio_score = float(np.clip(cio_score, 0.0, 100.0))

        # 4. Determinazione Direzione e Convinzione del Trade
        if cio_score >= self.buy_threshold:
            decision = "BUY"
            conviction_factor = (cio_score - self.buy_threshold) / (100.0 - self.buy_threshold)
        elif cio_score <= self.sell_threshold:
            decision = "SELL"
            conviction_factor = (self.sell_threshold - cio_score) / self.sell_threshold
        else:
            decision = "HOLD"
            conviction_factor = 0.0

        if decision == "HOLD":
            return {
                "agent_id": self.agent_id,
                "final_decision": "HOLD",
                "reason": f"NEUTRAL_ENSEMBLE_SCORE ({round(cio_score, 2)})",
                "cio_ensemble_score": round(cio_score, 2),
                "execution_plan": None
            }

        # 5. Modulazione della Taglia del Posizionamento
        base_position_params = agent_03_risk_res.get("position_parameters", {})
        base_units = base_position_params.get("position_units", 0.0)
        
        # Scaling in base alla convinzione (minimo min_conviction_multiplier del sizing base)
        scaling_multiplier = self.min_conviction_multiplier + (1.0 - self.min_conviction_multiplier) * conviction_factor
        final_units = float(round(base_units * scaling_multiplier, 4))

        # 6. Definizione del Routing di Esecuzione
        micro_metrics = agent_02_micro_res.get("metrics", {})
        execution_routing = self.determine_execution_router(micro_metrics)

        return {
            "agent_id": self.agent_id,
            "final_decision": decision,
            "reason": f"HIGH_CONVICTION_{decision}_SIGNAL (Ensemble Score: {round(cio_score, 2)})",
            "cio_ensemble_score": round(cio_score, 2),
            "conviction_factor": round(conviction_factor, 2),
            "weights_used": weights,
            "final_trade_parameters": {
                "side": decision,
                "position_units": final_units,
                "stop_loss_price": base_position_params.get("stop_loss_price", 0.0),
                "take_profit_price": base_position_params.get("take_profit_price", 0.0),
                "risk_usd": base_position_params.get("risk_amount_usd", 0.0)
            },
            "execution_plan": execution_routing
        }