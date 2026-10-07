import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class MicrostructureAgent:
    """
    AGENTE #2: Market Microstructure & Order Flow Specialist (Citadel / HFT Engine V2.0)
    Analisi avanzata della microstruttura:
    - Micro-Price & Multi-Level Order Flow Imbalance (OFI)
    - VPIN Toxicity & Kyle's Lambda Illiquidity
    - Iceberg / Hidden Order Detection
    - Liquidity Void & Slippage Risk Surface
    - FIFO Queue Depletion Speed
    """
    def __init__(self, vpin_threshold: float = 0.75, iceberg_sensitivity: float = 2.5):
        self.agent_id = "AGENT_02_MICROSTRUCTURE"
        self.vpin_threshold = vpin_threshold
        self.iceberg_sensitivity = iceberg_sensitivity

    def calculate_rvol(self, volume_series: pd.Series, window: int = 20) -> float:
        """Calcola il Volume Relativo (RVOL) rispetto alla media recente."""
        if len(volume_series) < window:
            return 1.0
        avg_volume = volume_series.rolling(window=window).mean().iloc[-1]
        if avg_volume == 0 or np.isnan(avg_volume):
            return 1.0
        return float(volume_series.iloc[-1] / avg_volume)

    def calculate_kyles_lambda(self, price_series: pd.Series, volume_series: pd.Series, window: int = 15) -> float:
        """
        Calcola la Lambda di Kyle (Impatto sul Prezzo per Unità di Volume / Illiquidità).
        """
        if len(price_series) < window or len(volume_series) < window:
            return 0.0
        
        delta_p = price_series.diff().dropna()
        vol = volume_series.iloc[1:]
        
        if len(delta_p) < 5 or vol.var() == 0 or np.isnan(vol.var()):
            return 0.0
        
        cov = np.cov(delta_p.tail(window), vol.tail(window))[0][1]
        var_vol = vol.tail(window).var()
        
        kyles_lambda = float(cov / var_vol) if var_vol != 0 else 0.0
        return float(np.nan_to_num(kyles_lambda))

    def calculate_vpin_approx(self, df: pd.DataFrame, num_buckets: int = 10) -> float:
        """
        Calcola la probabilità di tossicità del flusso ordini (VPIN).
        """
        if len(df) < num_buckets:
            return 0.5
        
        recent_df = df.tail(num_buckets).copy()
        high_low = recent_df['high'] - recent_df['low']
        high_low = high_low.replace(0, np.nan)
        
        buy_factor = (recent_df['close'] - recent_df['low']) / high_low
        buy_factor = buy_factor.fillna(0.5)
        
        buy_volume = recent_df['volume'] * buy_factor
        sell_volume = recent_df['volume'] * (1 - buy_factor)
        
        volume_imbalance = np.abs(buy_volume - sell_volume).sum()
        total_volume = recent_df['volume'].sum()
        
        if total_volume == 0:
            return 0.5
            
        return float(np.clip(volume_imbalance / total_volume, 0.0, 1.0))

    def detect_iceberg_orders(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Rileva ordini nascosti (Iceberg Orders):
        Anomalia dove un volume enorme viene scambiato con uno spostamento di prezzo minimo.
        """
        if len(df) < 10:
            return {"iceberg_detected": False, "side": "NONE", "intensity": 0.0}
            
        recent = df.tail(5)
        vol_mean = df['volume'].tail(20).mean()
        
        iceberg_buy = False
        iceberg_sell = False
        max_intensity = 0.0
        
        for idx, row in recent.iterrows():
            price_range = abs(row['high'] - row['low'])
            vol = row['volume']
            
            if vol_mean > 0 and price_range > 0:
                # Ratio tra Volume e Volatilità/Range della candela
                vol_to_range_ratio = (vol / vol_mean) / (price_range / row['close'])
                
                if vol_to_range_ratio > self.iceberg_sensitivity * 100:
                    max_intensity = float(vol_to_range_ratio)
                    if row['close'] >= row['open']:
                        iceberg_buy = True  # Muro istituzionale in accumulo
                    else:
                        iceberg_sell = True # Muro istituzionale in distribuzione

        if iceberg_buy:
            return {"iceberg_detected": True, "side": "BUY_ACCUMULATION", "intensity": max_intensity}
        elif iceberg_sell:
            return {"iceberg_detected": True, "side": "SELL_DISTRIBUTION", "intensity": max_intensity}
        
        return {"iceberg_detected": False, "side": "NONE", "intensity": 0.0}

    def detect_liquidity_void(self, df: pd.DataFrame) -> bool:
        """
        Rileva buchi di liquidità (Liquidity Voids): Candele a range ampio con volume insolitamente basso,
        segno che il book si è svuotato rendendo il prezzo vulnerabile a grandi oscillazioni.
        """
        if len(df) < 10:
            return False
            
        last_row = df.iloc[-1]
        avg_range = (df['high'] - df['low']).tail(10).mean()
        avg_vol = df['volume'].tail(10).mean()
        
        current_range = last_row['high'] - last_row['low']
        current_vol = last_row['volume']
        
        # Range ampio ma volume scarso -> Buchi di liquidità nel book
        if current_range > 1.8 * avg_range and current_vol < 0.7 * avg_vol:
            return True
        return False

    def calculate_queue_depletion_speed(self, df: pd.DataFrame) -> float:
        """
        Stima la velocità di svuotamento della coda del book.
        Restituisce un valore tra -1.0 (svuotamento lato Bid) e +1.0 (svuotamento lato Ask).
        """
        if len(df) < 5:
            return 0.0
            
        recent = df.tail(5)
        buy_pressures = (recent['close'] - recent['low']) / (recent['high'] - recent['low'] + 1e-6)
        vol_weights = recent['volume'] / (recent['volume'].sum() + 1e-6)
        
        speed = float(((buy_pressures - 0.5) * 2.0 * vol_weights).sum())
        return float(np.clip(speed, -1.0, 1.0))

    def calculate_order_flow_imbalance(self, df: pd.DataFrame, order_book: Optional[Dict[str, Any]] = None,
                                       depth: int = 10) -> Dict[str, Any]:
        """
        Order Flow Imbalance (OFI) tra -1.0 (pressione in vendita) e +1.0 (pressione in acquisto).
        Con uno snapshot L2 ({"bids": [[prezzo, size], ...], "asks": [...]}) usa le size dei primi
        `depth` livelli; altrimenti ricade sulla velocità di svuotamento della coda stimata dalle barre.
        """
        bids = (order_book or {}).get("bids") or []
        asks = (order_book or {}).get("asks") or []
        try:
            bid_size = sum(float(level[1]) for level in bids[:depth])
            ask_size = sum(float(level[1]) for level in asks[:depth])
        except (TypeError, ValueError, IndexError):
            bid_size = ask_size = 0.0
        if bid_size + ask_size > 0:
            return {"ofi": float((bid_size - ask_size) / (bid_size + ask_size)), "source": "L2_BOOK"}
        return {"ofi": self.calculate_queue_depletion_speed(df), "source": "OHLCV_PROXY"}

    def analyze(self, df: pd.DataFrame, order_book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Pipeline Esecutiva completa dell'Agente #2.
        order_book: snapshot L2 opzionale ({"bids": [[prezzo, size], ...], "asks": [...]}), usato per l'OFI;
        lo score resta derivato dalle barre OHLCV.
        """
        if df.empty or not {'close', 'open', 'high', 'low', 'volume'}.issubset(df.columns) or len(df) < 20:
            return {
                "agent_id": self.agent_id,
                "microstructure_score": 50.0,
                "status": "INSUFFICIENT_DATA",
                "reason": f"servono almeno 20 barre OHLCV complete (ricevute {len(df)})",
                "trade_signal": "NEUTRAL"
            }

        # 1. Calcolo Metriche
        rvol = self.calculate_rvol(df['volume'])
        kyles_lambda = self.calculate_kyles_lambda(df['close'], df['volume'])
        vpin = self.calculate_vpin_approx(df)
        iceberg_info = self.detect_iceberg_orders(df)
        has_liquidity_void = self.detect_liquidity_void(df)
        queue_speed = self.calculate_queue_depletion_speed(df)
        ofi_info = self.calculate_order_flow_imbalance(df, order_book)

        base_score = 50.0

        # 2. Logica di Scoring Microstrutturale
        # Pressione di svuotamento coda
        base_score += queue_speed * 25.0

        # Rilevamento Ordini Nascosti (Iceberg)
        if iceberg_info["iceberg_detected"]:
            if iceberg_info["side"] == "BUY_ACCUMULATION":
                base_score += 20.0
            elif iceberg_info["side"] == "SELL_DISTRIBUTION":
                base_score -= 20.0

        # RVOL e Volume Breakout
        if rvol > 2.0 and queue_speed > 0.2:
            base_score += 15.0
        elif rvol > 2.0 and queue_speed < -0.2:
            base_score -= 15.0

        # Penale per Tossicità (VPIN high) o Buchi di Liquidità
        if vpin > self.vpin_threshold:
            base_score -= 15.0  # Flusso tossico
        if has_liquidity_void:
            base_score -= 10.0  # Rischio elevato di slippage

        microstructure_score = float(np.clip(base_score, 0.0, 100.0))

        if microstructure_score >= 75.0:
            signal = "STRONG_BUY_FLOW"
        elif microstructure_score <= 30.0:
            signal = "HEAVY_SELL_FLOW"
        else:
            signal = "NEUTRAL"

        return {
            "agent_id": self.agent_id,
            "microstructure_score": round(microstructure_score, 2),
            "trade_signal": signal,
            "metrics": {
                "rvol": round(rvol, 2),
                "vpin_toxicity": round(vpin, 4),
                "queue_depletion_speed": round(queue_speed, 4),
                "order_flow_imbalance": round(ofi_info["ofi"], 4),
                "ofi_source": ofi_info["source"],
                "kyles_lambda": round(kyles_lambda, 6),
                "iceberg_order": iceberg_info,
                "liquidity_void_detected": has_liquidity_void
            }
        }
    