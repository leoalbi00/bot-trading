import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class InstitutionalRiskAgent:
    """
    AGENTE #3: Institutional Risk & Neutrality Manager (Millennium Engine)
    Gestione del rischio avanzata:
    - Dynamic ATR Stop-Loss & Target
    - Volatility Parity & Position Sizing
    - Expected Shortfall (CVaR 99%)
    - Beta vs Benchmark & Portfolio Neutrality
    - Circuit Breaker / Drawdown Hard Cutoff
    """
    def __init__(self, max_daily_drawdown_pct: float = 0.03, max_risk_per_trade_pct: float = 0.01):
        self.agent_id = "AGENT_03_RISK_MANAGER"
        self.max_daily_drawdown_pct = max_daily_drawdown_pct  # Es. 3% max drawdown giornaliero
        self.max_risk_per_trade_pct = max_risk_per_trade_pct  # Es. 1% rischio max per trade

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calcola l'Average True Range (ATR) per la volatilità attuale."""
        if len(df) < period + 1 or not {'high', 'low', 'close'}.issubset(df.columns):
            return 0.0
        
        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        return float(np.nan_to_num(atr))

    def calculate_cvar(self, returns: pd.Series, confidence: float = 0.99) -> float:
        """
        Calcola la Conditional Value at Risk (CVaR / Expected Shortfall) al livello di confidenza specificato.
        """
        if len(returns) < 20:
            return 0.05  # Stima conservativa del 5% in assenza di dati
        
        var_threshold = np.quantile(returns.dropna(), 1.0 - confidence)
        cvar_returns = returns[returns <= var_threshold]
        
        if len(cvar_returns) == 0:
            return float(abs(var_threshold))
        return float(abs(cvar_returns.mean()))

    def calculate_beta(self, asset_returns: pd.Series, benchmark_returns: pd.Series) -> float:
        """
        Calcola il Beta dell'asset rispetto al Benchmark di riferimento (es. BTC o S&P 500).
        """
        combined = pd.concat([asset_returns, benchmark_returns], axis=1).dropna()
        if len(combined) < 15:
            return 1.0
        
        cov_matrix = np.cov(combined.iloc[:, 0], combined.iloc[:, 1])
        var_bench = cov_matrix[1, 1]
        
        if var_bench == 0:
            return 1.0
        
        return float(cov_matrix[0, 1] / var_bench)

    def calculate_position_sizing(
        self, 
        account_balance: float, 
        current_price: float, 
        atr: float, 
        atr_multiplier: float = 2.0
    ) -> Dict[str, float]:
        """
        Calcola la dimensione ottimale della posizione basata sulla gestione del rischio ATR.
        """
        if current_price <= 0 or atr <= 0 or account_balance <= 0:
            return {"position_units": 0.0, "position_value": 0.0, "stop_loss_price": 0.0, "take_profit_price": 0.0}

        risk_amount = account_balance * self.max_risk_per_trade_pct
        stop_distance = atr * atr_multiplier
        
        stop_loss_price = max(0.0, current_price - stop_distance)
        take_profit_price = current_price + (stop_distance * 2.0)  # Risk-Reward 1:2
        
        position_units = risk_amount / stop_distance if stop_distance > 0 else 0.0
        position_value = position_units * current_price
        
        # Limite massimo di leva implicita: no posizioni superiori al 35% del capitale totale per singolo trade
        max_allowed_value = account_balance * 0.35
        if position_value > max_allowed_value:
            position_value = max_allowed_value
            position_units = position_value / current_price

        return {
            "position_units": float(round(position_units, 4)),
            "position_value": float(round(position_value, 2)),
            "stop_loss_price": float(round(stop_loss_price, 4)),
            "take_profit_price": float(round(take_profit_price, 4)),
            "risk_amount_usd": float(round(risk_amount, 2))
        }

    def analyze(
        self, 
        df: pd.DataFrame, 
        account_balance: float, 
        current_daily_drawdown_pct: float = 0.0,
        benchmark_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Pipeline Esecutiva completa dell'Agente #3.
        """
        if df.empty or len(df) < 15 or account_balance <= 0:
            return {
                "agent_id": self.agent_id,
                "risk_approved": False,
                "reason": "INSUFFICIENT_DATA_OR_ZERO_BALANCE",
                "risk_score": 0.0
            }

        # 1. Controllo Circuit Breaker (Hard Drawdown Cutoff)
        if current_daily_drawdown_pct >= self.max_daily_drawdown_pct:
            return {
                "agent_id": self.agent_id,
                "risk_approved": False,
                "reason": f"CIRCUIT_BREAKER_TRIGGERED (Daily DD: {current_daily_drawdown_pct*100:.2f}%)",
                "risk_score": 0.0
            }

        current_price = df['close'].iloc[-1]
        returns = df['close'].pct_change().dropna()
        
        # 2. Calcolo Metriche di Rischio
        atr = self.calculate_atr(df)
        cvar_99 = self.calculate_cvar(returns)
        
        beta = 1.0
        if benchmark_df is not None and not benchmark_df.empty and 'close' in benchmark_df.columns:
            bench_returns = benchmark_df['close'].pct_change().dropna()
            beta = self.calculate_beta(returns, bench_returns)

        # 3. Calcolo Sizing e Livelli di Stop/Target
        sizing_info = self.calculate_position_sizing(account_balance, current_price, atr)

        # 4. Calcolo Punteggio di Rischio (Risk Score 0 - 100)
        risk_score = 100.0
        
        # Penalizzazioni per rischio di coda e volatilità estreme
        if cvar_99 > 0.08:  # Rischio di crollo oltre l'8%
            risk_score -= 30.0
        if abs(beta) > 1.8:  # Volatilità eccessiva rispetto al mercato
            risk_score -= 20.0

        risk_score = float(np.clip(risk_score, 0.0, 100.0))
        risk_approved = risk_score >= 50.0 and sizing_info["position_units"] > 0

        return {
            "agent_id": self.agent_id,
            "risk_approved": risk_approved,
            "risk_score": round(risk_score, 2),
            "metrics": {
                "atr": round(atr, 4),
                "cvar_99_tail_risk": round(cvar_99, 4),
                "benchmark_beta": round(beta, 2),
                "current_daily_drawdown_pct": round(current_daily_drawdown_pct, 4)
            },
            "position_parameters": sizing_info
        }

# Alias usato dall'orchestratore quant_core.py
RiskManagerAgent = InstitutionalRiskAgent
