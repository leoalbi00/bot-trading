from datetime import datetime
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# Risk Safety Net (non negoziabile)
MAX_EXPOSURE_PCT = 50.0            # esposizione totale massima del portafoglio, % del capitale (50%: un
                                   # SUPER_CONVICTION può usare tutta la taglia autorizzata)
MAX_POSITIONS = 4                  # posizioni aperte contemporaneamente
HARD_STOP_MIN_PCT = 1.5            # hard stop loss tra 1.5% ...
HARD_STOP_MAX_PCT = 2.5            # ... e 2.5% dal prezzo d'ingresso
HARD_STOP_ATR_MULT = 1.5           # 1.5 x ATR, riportato nella fascia 1.5-2.5%
STANDARD_MAX_ALLOCATION_PCT = 25.0  # taglia massima di un trade standard
SUPER_CONVICTION_MAX_ALLOCATION_PCT = 50.0  # taglia massima autorizzata per un trade SUPER_CONVICTION
CRYPTO_NIGHT_TZ = ZoneInfo("Europe/Rome")   # CET/CEST
CRYPTO_NIGHT_START_HOUR = 22       # nessuna NUOVA apertura crypto dalle 22:00 ...
CRYPTO_NIGHT_END_HOUR = 8          # ... alle 08:00


def hard_stop_pct(atr_pct: Optional[float]) -> float:
    """Hard stop in % (negativo): 1.5 x ATR% riportato tra -1.5% e -2.5%; senza ATR il più largo consentito."""
    if not atr_pct or atr_pct <= 0 or not np.isfinite(atr_pct):
        return -HARD_STOP_MAX_PCT
    return -round(float(np.clip(HARD_STOP_ATR_MULT * atr_pct, HARD_STOP_MIN_PCT, HARD_STOP_MAX_PCT)), 2)


def clamp_stop_pct(stop_pct: Optional[float]) -> float:
    """Qualsiasi stop (anche salvato su ordini precedenti) riportato nella fascia non negoziabile -1.5% / -2.5%."""
    if stop_pct is None:
        return -HARD_STOP_MAX_PCT
    return -round(float(np.clip(abs(stop_pct), HARD_STOP_MIN_PCT, HARD_STOP_MAX_PCT)), 2)


def crypto_night_blocked(now: Optional[datetime] = None) -> bool:
    """True tra le 22:00 e le 08:00 (ora italiana): nessuna nuova apertura su crypto."""
    local = (now or datetime.now(CRYPTO_NIGHT_TZ)).astimezone(CRYPTO_NIGHT_TZ)
    return local.hour >= CRYPTO_NIGHT_START_HOUR or local.hour < CRYPTO_NIGHT_END_HOUR


class InstitutionalRiskAgent:
    """
    AGENTE #3: Comitato Rischi (Risk Safety Net)
    - Hard Stop Loss non negoziabile: 1.5 x ATR nella fascia 1.5%-2.5%, target 1 a 2R
    - Esposizione totale massima 50% del capitale, massimo 4 posizioni simultanee
    - Blocco crypto overnight (22:00-08:00 CET): nessuna nuova apertura
    - Sizing a rischio fisso, taglia massima 25% (50% solo per SUPER_CONVICTION, autorizzata qui)
    - Expected Shortfall (CVaR 99%), Beta vs Benchmark, Circuit Breaker sul drawdown giornaliero
    Portafoglio pieno o senza margine di esposizione non è un veto qui: lo decide il CIO, perché un trade
    SUPER_CONVICTION può ancora entrare (rotazione delle sole tesi degradate o taglia ridotta).
    """
    def __init__(self, max_daily_drawdown_pct: float = 0.03, max_risk_per_trade_pct: float = 0.01,
                 max_exposure_pct: float = MAX_EXPOSURE_PCT, max_positions: int = MAX_POSITIONS):
        self.agent_id = "AGENT_03_RISK_MANAGER"
        self.max_daily_drawdown_pct = max_daily_drawdown_pct  # Es. 3% max drawdown giornaliero
        self.max_risk_per_trade_pct = max_risk_per_trade_pct  # Es. 1% rischio max per trade
        self.max_exposure_pct = max_exposure_pct
        self.max_positions = max_positions

    @staticmethod
    def authorized_allocation_pct(super_conviction: bool) -> float:
        """Taglia massima autorizzata dal Comitato Rischi (% del capitale)."""
        return SUPER_CONVICTION_MAX_ALLOCATION_PCT if super_conviction else STANDARD_MAX_ALLOCATION_PCT

    def safety_net(self, is_crypto: bool = False, portfolio: Optional[Dict[str, Any]] = None,
                   now: Optional[datetime] = None) -> Dict[str, Any]:
        """Limiti di portafoglio. portfolio: {"exposure_pct": float, "positions": int}."""
        portfolio = portfolio or {}
        exposure = float(portfolio.get("exposure_pct") or 0.0)
        n_pos = int(portfolio.get("positions") or 0)
        return {
            "crypto_night_block": bool(is_crypto and crypto_night_blocked(now)),
            "exposure_pct": round(exposure, 2),
            "exposure_room_pct": round(max(0.0, self.max_exposure_pct - exposure), 2),
            "max_exposure_pct": self.max_exposure_pct,
            "positions": n_pos,
            "max_positions": self.max_positions,
            "slots_full": n_pos >= self.max_positions,
        }

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
        atr_multiplier: float = HARD_STOP_ATR_MULT,
        max_allocation_pct: float = STANDARD_MAX_ALLOCATION_PCT,
    ) -> Dict[str, float]:
        """
        Sizing a rischio fisso con Hard Stop: distanza dello stop = 1.5 x ATR riportata tra 1.5% e 2.5% del prezzo,
        primo target (scaling out) a 2R. Taglia massima max_allocation_pct del capitale.
        """
        if current_price <= 0 or atr <= 0 or account_balance <= 0:
            return {"position_units": 0.0, "position_value": 0.0, "stop_loss_price": 0.0, "take_profit_price": 0.0}

        risk_amount = account_balance * self.max_risk_per_trade_pct
        stop_pct = float(np.clip(atr_multiplier * atr / current_price * 100, HARD_STOP_MIN_PCT, HARD_STOP_MAX_PCT))
        stop_distance = current_price * stop_pct / 100

        stop_loss_price = max(0.0, current_price - stop_distance)
        take_profit_price = current_price + (stop_distance * 2.0)  # Target 1 (scaling out) a 2R

        position_units = risk_amount / stop_distance if stop_distance > 0 else 0.0
        position_value = position_units * current_price

        max_allowed_value = account_balance * max_allocation_pct / 100
        if position_value > max_allowed_value:
            position_value = max_allowed_value
            position_units = position_value / current_price

        return {
            "position_units": float(round(position_units, 4)),
            "position_value": float(round(position_value, 2)),
            "stop_loss_price": float(round(stop_loss_price, 4)),
            "stop_loss_pct": -round(stop_pct, 2),
            "take_profit_price": float(round(take_profit_price, 4)),
            "risk_amount_usd": float(round(risk_amount, 2)),
            "max_allocation_pct": max_allocation_pct,
            "super_conviction_max_allocation_pct": SUPER_CONVICTION_MAX_ALLOCATION_PCT,
        }

    def analyze(
        self, 
        df: pd.DataFrame, 
        account_balance: float, 
        current_daily_drawdown_pct: float = 0.0,
        benchmark_df: Optional[pd.DataFrame] = None,
        is_crypto: bool = False,
        portfolio: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Pipeline Esecutiva completa dell'Agente #3.
        portfolio: {"exposure_pct", "positions"} per i limiti di esposizione (50%) e posizioni (4).
        """
        net = self.safety_net(is_crypto, portfolio, now)
        if df.empty or len(df) < 15 or account_balance <= 0:
            return {
                "agent_id": self.agent_id,
                "risk_approved": False,
                "reason": "INSUFFICIENT_DATA_OR_ZERO_BALANCE",
                "risk_score": 0.0,
                "safety_net": net
            }

        # 0. Blocco crypto overnight (22:00-08:00 CET): nessuna nuova apertura
        if net["crypto_night_block"]:
            return {
                "agent_id": self.agent_id,
                "risk_approved": False,
                "reason": f"CRYPTO_OVERNIGHT_BLOCK (nessuna nuova apertura crypto tra le {CRYPTO_NIGHT_START_HOUR}:00 "
                          f"e le {CRYPTO_NIGHT_END_HOUR:02d}:00 CET)",
                "risk_score": 0.0,
                "safety_net": net
            }

        # 1. Controllo Circuit Breaker (Hard Drawdown Cutoff)
        if current_daily_drawdown_pct >= self.max_daily_drawdown_pct:
            return {
                "agent_id": self.agent_id,
                "risk_approved": False,
                "reason": f"CIRCUIT_BREAKER_TRIGGERED (Daily DD: {current_daily_drawdown_pct*100:.2f}%)",
                "risk_score": 0.0,
                "safety_net": net
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
        if sizing_info["position_units"] <= 0:
            reason = f"POSITION_SIZE_ZERO (ATR {atr:.6f})"
        elif not risk_approved:
            reason = f"RISK_SCORE_TOO_LOW ({risk_score:.0f} < 50: CVaR99 {cvar_99:.2%}, beta {beta:.2f})"
        else:
            reason = (f"OK (risk score {risk_score:.0f}, CVaR99 {cvar_99:.2%}, hard stop {sizing_info['stop_loss_pct']:.2f}%, "
                      f"esposizione {net['exposure_pct']:.0f}%/{net['max_exposure_pct']:.0f}%, "
                      f"{net['positions']}/{net['max_positions']} posizioni)")

        return {
            "agent_id": self.agent_id,
            "risk_approved": risk_approved,
            "reason": reason,
            "risk_score": round(risk_score, 2),
            "metrics": {
                "atr": round(atr, 4),
                "cvar_99_tail_risk": round(cvar_99, 4),
                "benchmark_beta": round(beta, 2),
                "current_daily_drawdown_pct": round(current_daily_drawdown_pct, 4)
            },
            "position_parameters": sizing_info,
            "safety_net": net
        }

# Alias usato dall'orchestratore quant_core.py
RiskManagerAgent = InstitutionalRiskAgent
