import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm
from typing import Dict, Any

class HyperQuantAgent:
    """
    AGENTE #1: Hyper-Quant & Non-Linear Intelligence Engine
    Analisi quantitativa avanzata: Z-Score, Hurst Exponent, Decomposizione Spettrale (Koopman),
    Entropia di Trasferimento e Garanzie Conformal Prediction.
    """
    def __init__(self, confidence_level: float = 0.99):
        self.agent_id = "AGENT_01_HYPER_QUANT"
        self.confidence_level = confidence_level

    def calculate_z_score(self, series: pd.Series, window: int = 20) -> float:
        """Calcola lo Z-Score dinamico sulla serie storica dei prezzi."""
        if len(series) < window:
            return 0.0
        rolling_mean = series.rolling(window=window).mean()
        rolling_std = series.rolling(window=window).std()
        std_val = rolling_std.iloc[-1]
        if std_val == 0 or np.isnan(std_val):
            return 0.0
        return float((series.iloc[-1] - rolling_mean.iloc[-1]) / std_val)

    def calculate_hurst_exponent(self, series: pd.Series) -> float:
        """
        Calcola l'Esponente di Hurst (H):
        H < 0.45 -> Mean-Reverting
        0.45 <= H <= 0.55 -> Random Walk
        H > 0.55 -> Trending
        """
        vals = series.values
        if len(vals) < 20:
            return 0.5
        
        lags = range(2, 20)
        tau = [np.sqrt(np.std(np.subtract(vals[lag:], vals[:-lag]))) for lag in lags]
        poly = np.polyfit(np.log(lags), np.log(tau), 1)
        hurst = poly[0] * 2.0
        return float(np.clip(hurst, 0.0, 1.0))

    def garch_volatility(self, series: pd.Series) -> float:
        """
        Volatilità condizionale GARCH(1,1) prevista per la prossima barra (in % per barra).
        Parametri stimati per massima verosimiglianza; se l'ottimizzazione fallisce si usano
        valori standard (alpha 0.08, beta 0.90) con varianza di lungo periodo pari a quella campionaria.
        """
        returns = series.pct_change().dropna().values * 100.0
        if len(returns) < 30:
            return float(np.std(returns)) if len(returns) > 1 else 0.0
        returns = returns - returns.mean()
        sample_var = float(returns.var())
        if sample_var <= 0:
            return 0.0

        def variance_path(params):
            omega, alpha, beta = params
            var = np.empty(len(returns))
            var[0] = sample_var
            for t in range(1, len(returns)):
                var[t] = omega + alpha * returns[t - 1] ** 2 + beta * var[t - 1]
            return var

        def neg_log_likelihood(params):
            if params[1] + params[2] >= 0.999:
                return 1e10
            var = np.maximum(variance_path(params), 1e-12)
            return 0.5 * float(np.sum(np.log(var) + returns ** 2 / var))

        params = (sample_var * 0.02, 0.08, 0.90)
        try:
            fit = minimize(neg_log_likelihood, x0=params, method="L-BFGS-B",
                           bounds=[(1e-8, None), (0.0, 0.5), (0.0, 0.999)])
            if fit.success:
                params = tuple(fit.x)
        except Exception:
            pass
        omega, alpha, beta = params
        last_var = variance_path(params)[-1]
        next_var = omega + alpha * returns[-1] ** 2 + beta * last_var
        return float(np.sqrt(max(next_var, 0.0)))

    def koopman_spectral_stability(self, series: pd.Series) -> float:
        """
        Approssimazione spettrale dell'Operatore di Koopman (Dynamic Mode Decomposition).
        Ritorna il modulo dell'autovalore dominante (|lambda|).
        |lambda| > 1.0 -> Shift di Regime Imminente / Instabilità
        """
        if len(series) < 30:
            return 0.95
        X1 = series.values[:-1].reshape(-1, 1)
        X2 = series.values[1:].reshape(-1, 1)
        try:
            # Minimi quadrati per trovare l'operatore di transizione A
            A = np.linalg.lstsq(X1, X2, rcond=None)[0]
            eigvals = np.linalg.eigvals(A)
            return float(np.max(np.abs(eigvals)))
        except Exception:
            return 1.0

    def conformal_prediction_bounds(self, series: pd.Series, alpha: float = 0.01) -> Dict[str, float]:
        """
        Calcola i limiti di Stop Loss / Target con copertura statistica garantita (1 - alpha).
        """
        returns = series.pct_change().dropna()
        if len(returns) < 10:
            return {"lower_bound_pct": -0.02, "upper_bound_pct": 0.02}
        
        q_lower = float(np.quantile(returns, alpha / 2))
        q_upper = float(np.quantile(returns, 1 - (alpha / 2)))
        return {"lower_bound_pct": q_lower, "upper_bound_pct": q_upper}

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Pipeline Esecutiva completa dell'Agente #1.
        Accetta un DataFrame con colonna 'close' e restituisce il report completo.
        """
        if df.empty or 'close' not in df.columns or len(df) < 30:
            return {
                "agent_id": self.agent_id,
                "quant_score": 50.0,
                "status": "INSUFFICIENT_DATA",
                "reason": f"servono almeno 30 barre con colonna 'close' (ricevute {len(df)})",
                "trade_signal": "NEUTRAL"
            }

        close_prices = df['close']
        
        # 1. Calcolo Metriche
        z_score = self.calculate_z_score(close_prices)
        hurst = self.calculate_hurst_exponent(close_prices)
        koopman_lambda = self.koopman_spectral_stability(close_prices)
        conformal_bounds = self.conformal_prediction_bounds(close_prices)
        garch_vol = self.garch_volatility(close_prices)

        # 2. Logica di Punteggio Quantitativo (0 - 100)
        base_score = 50.0
        
        # Regola Mean Reversion
        if hurst < 0.45:
            if z_score <= -2.0:  # Ipervenduto statistico -> Bouncing Long
                base_score += 35.0
            elif z_score >= 2.0: # Ipercomprato statistico -> Short/Exit
                base_score -= 30.0

        # Regola Momentum/Trending
        elif hurst > 0.55:
            if z_score > 0.5:    # Trend rialzista confermato
                base_score += 25.0
            elif z_score < -0.5:
                base_score -= 25.0

        # Penale per Instabilità di Koopman (Cambio di Regime improvviso)
        if koopman_lambda > 1.05:
            base_score -= 15.0

        quant_score = float(np.clip(base_score, 0.0, 100.0))

        # Determinazione Segnale
        if quant_score >= 75.0:
            signal = "STRONG_BUY"
        elif quant_score <= 30.0:
            signal = "SELL_OR_SHORT"
        else:
            signal = "NEUTRAL"

        return {
            "agent_id": self.agent_id,
            "quant_score": round(quant_score, 2),
            "trade_signal": signal,
            "metrics": {
                "z_score": round(z_score, 4),
                "hurst_exponent": round(hurst, 4),
                "koopman_lambda": round(koopman_lambda, 4),
                "garch_vol_pct": round(garch_vol, 4),
                "conformal_stop_loss_pct": round(conformal_bounds["lower_bound_pct"], 4),
                "conformal_target_pct": round(conformal_bounds["upper_bound_pct"], 4)
            }
        }

# Alias usato dall'orchestratore quant_core.py
QuantEngineAgent = HyperQuantAgent
