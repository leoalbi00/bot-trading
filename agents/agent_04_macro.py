import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional

class MacroSentimentAgent:
    """
    AGENTE #4: Institutional Macro, Sentiment & Event Intelligence (Bridgewater Engine V2.0)
    Analisi avanzata del contesto globale:
    - VIX & Cross-Asset Stress Matrix (Yield Curve 10Y-2Y, DXY)
    - Economic Surprise Index (Consensus vs Actual Delta)
    - Central Bank Hawkish/Dovish NLP Scoring
    - CFTC Commitment of Traders (COT) Institutional Flow
    - Event Blackout Window & Contrarian Sentiment Detector
    """
    def __init__(
        self, 
        vix_high_threshold: float = 28.0, 
        vix_moderate_threshold: float = 20.0,
        hawkish_keywords: Optional[List[str]] = None,
        dovish_keywords: Optional[List[str]] = None
    ):
        self.agent_id = "AGENT_04_MACRO_SENTIMENT"
        self.vix_high_threshold = vix_high_threshold
        self.vix_moderate_threshold = vix_moderate_threshold
        
        self.hawkish_keywords = hawkish_keywords or [
            "inflation", "rate hike", "tightening", "hawkish", "upside risk", "overheating", "restrictive"
        ]
        self.dovish_keywords = dovish_keywords or [
            "cut", "easing", "dovish", "slowdown", "recession risk", "accommodative", "cool down"
        ]

    def calculate_economic_surprise(self, actual: float, consensus: float, std_dev: float = 1.0) -> float:
        """
        Calcola l'Economic Surprise Index (Z-score dello scostamento rispetto al consenso).
        """
        if std_dev <= 0:
            std_dev = 1.0
        surprise_z = (actual - consensus) / std_dev
        return float(np.clip(surprise_z, -3.0, 3.0))

    def parse_central_bank_speech(self, speech_text: str) -> float:
        """
        Analisi semantica del testo di un discorso o comunicato stampa della Banca Centrale.
        Restituisce un valore tra -1.0 (Molto Dovish) e +1.0 (Molto Hawkish).
        """
        if not speech_text:
            return 0.0
            
        text_lower = speech_text.lower()
        hawk_count = sum(text_lower.count(word) for word in self.hawkish_keywords)
        dove_count = sum(text_lower.count(word) for word in self.dovish_keywords)
        
        total = hawk_count + dove_count
        if total == 0:
            return 0.0
            
        polarity = (hawk_count - dove_count) / total
        return float(np.clip(polarity, -1.0, 1.0))

    def evaluate_cross_asset_stress(
        self, 
        vix: float, 
        us10y_yield: float = 4.0, 
        us02y_yield: float = 4.1, 
        dxy_change_pct: float = 0.0
    ) -> Dict[str, Any]:
        """
        Valuta lo stress finanziario globale monitorando VIX, Inversione della Curva (10Y-2Y) e DXY.
        """
        yield_curve_spread = us10y_yield - us02y_yield  # Se < 0 -> Curva Invertita (Segnale Recessione)
        
        stress_level = "LOW"
        size_multiplier = 1.0
        
        if vix >= self.vix_high_threshold:
            stress_level = "EXTREME_PANIC"
            size_multiplier = 0.0  # Veto
        elif vix >= self.vix_moderate_threshold or yield_curve_spread < -0.5:
            stress_level = "HIGH_STRESS"
            size_multiplier = 0.4
        elif yield_curve_spread < 0 or dxy_change_pct > 0.015:
            stress_level = "MODERATE_HEADWIND"
            size_multiplier = 0.75

        return {
            "stress_level": stress_level,
            "size_multiplier": size_multiplier,
            "yield_curve_spread": round(yield_curve_spread, 3),
            "vix": vix
        }

    def evaluate_cot_positioning(self, institutional_net_contracts: int, historical_max: int = 100000) -> float:
        """
        Analizza le posizioni nette dei grandi fondi (CFTC COT Report).
        Restituisce uno score tra -1.0 (Forte posizionamento Short) e +1.0 (Forte posizionamento Long).
        """
        if historical_max <= 0:
            return 0.0
        score = institutional_net_contracts / float(historical_max)
        return float(np.clip(score, -1.0, 1.0))

    def calculate_contrarian_sentiment_signal(self, fear_greed_index: float) -> Dict[str, Any]:
        """
        Rileva estremi irrazionali nel sentiment retail per generare segnali Contrarian.
        """
        if fear_greed_index >= 88.0:
            return {"signal": "CONTRARIAN_BEARISH_WARNING", "bias": -0.3, "reason": "EXTREME_RETAIL_FOMO"}
        elif fear_greed_index <= 12.0:
            return {"signal": "CONTRARIAN_BULLISH_WARNING", "bias": 0.3, "reason": "EXTREME_RETAIL_PANIC"}
        return {"signal": "NEUTRAL", "bias": 0.0, "reason": "BALANCED"}

    def check_event_blackout(self, upcoming_events: List[Dict[str, Any]], window_minutes: int = 30) -> Dict[str, Any]:
        """Verifica se il mercato è in prossimità di rilasci macro o trimestrali."""
        now = datetime.utcnow()
        for event in upcoming_events:
            try:
                event_time = datetime.fromisoformat(event.get("timestamp", ""))
                time_diff_minutes = (event_time - now).total_seconds() / 60.0
                if -15 <= time_diff_minutes <= window_minutes:
                    return {
                        "is_blackout": True,
                        "event_name": event.get("event_name", "HIGH_IMPACT_EVENT"),
                        "minutes_to_event": round(time_diff_minutes, 1)
                    }
            except Exception:
                continue
        return {"is_blackout": False, "event_name": "NONE", "minutes_to_event": 999.0}

    def analyze(
        self, 
        df: pd.DataFrame,
        vix_level: float = 16.5,
        fear_greed_index: float = 55.0,
        news_sentiment: float = 0.1,
        central_bank_speech: str = "",
        economic_data: Optional[Dict[str, float]] = None,
        cot_net_contracts: int = 25000,
        upcoming_events: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Pipeline Esecutiva completa dell'Agente #4.
        """
        if upcoming_events is None:
            upcoming_events = []
            
        # 1. Event Blackout Filter
        blackout_info = self.check_event_blackout(upcoming_events)
        if blackout_info["is_blackout"]:
            return {
                "agent_id": self.agent_id,
                "macro_approved": False,
                "macro_score": 0.0,
                "trade_signal": "EVENT_BLACKOUT_VETO",
                "reason": f"BLACKOUT: {blackout_info['event_name']} in {blackout_info['minutes_to_event']}m"
            }

        # 2. Stress Cross-Asset
        stress_info = self.evaluate_cross_asset_stress(vix_level)
        if stress_info["size_multiplier"] == 0.0:
            return {
                "agent_id": self.agent_id,
                "macro_approved": False,
                "macro_score": 10.0,
                "trade_signal": "CROSS_ASSET_PANIC_VETO",
                "reason": f"EXTREME_STRESS ({stress_info['stress_level']})"
            }

        # 3. Sentiment & NLP Central Bank
        cb_hawkishness = self.parse_central_bank_speech(central_bank_speech)
        cot_score = self.evaluate_cot_positioning(cot_net_contracts)
        contrarian_info = self.calculate_contrarian_sentiment_signal(fear_greed_index)

        # 4. Economic Surprise Index
        surprise_score = 0.0
        if economic_data and 'actual' in economic_data and 'consensus' in economic_data:
            surprise_score = self.calculate_economic_surprise(
                economic_data['actual'], economic_data['consensus']
            )

        # 5. Calcolo Score Macro Composito
        # Sentiment base (0-100)
        base_sentiment = (news_sentiment + 1.0) * 50.0
        
        # Aggiusta in base ai fattori macro
        macro_score = (0.35 * base_sentiment) + (0.25 * fear_greed_index) + (0.2 * (cot_score + 1.0) * 50.0)
        
        # Impatto di inflazione / tassi (Hawkish riduce propensione al rischio per asset growth/crypto)
        macro_score -= cb_hawkishness * 15.0
        macro_score += surprise_score * 5.0
        macro_score += contrarian_info["bias"] * 20.0  # Inserisce il correttivo Contrarian

        macro_score = float(np.clip(macro_score * stress_info["size_multiplier"], 0.0, 100.0))

        if macro_score >= 70.0:
            signal = "BULLISH_MACRO_TAILWIND"
        elif macro_score <= 35.0:
            signal = "BEARISH_MACRO_HEADWIND"
        else:
            signal = "NEUTRAL_MACRO"

        return {
            "agent_id": self.agent_id,
            "macro_approved": True,
            "macro_score": round(macro_score, 2),
            "trade_signal": signal,
            "metrics": {
                "cross_asset_stress": stress_info,
                "central_bank_hawkishness": round(cb_hawkishness, 3),
                "cot_institutional_score": round(cot_score, 3),
                "economic_surprise_z": round(surprise_score, 3),
                "contrarian_info": contrarian_info,
                "suggested_size_multiplier": stress_info["size_multiplier"]
            }
        }