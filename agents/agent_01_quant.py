import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.stats import norm
from typing import Dict, Any

class HyperQuantAgent:
    """
    AGENTE #1: Hyper-Quant & Non-Linear Intelligence Engine
    Analisi quantitativa avanzata: Z-Score, Hurst Exponent, GARCH(1,1), Decomposizione Spettrale (Koopman),
    Garanzie Conformal Prediction e Curva di Traiettoria Attesa (Expected Price Path) sulla volatilità reale.
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

    def garch_volatility(self, series: pd.Series, max_obs: int = 750) -> float:
        """
        Volatilità condizionale GARCH(1,1) prevista per la prossima barra (in % per barra).
        Parametri stimati per massima verosimiglianza sulle ultime `max_obs` osservazioni
        (ricorsione della varianza vettorizzata con lfilter); se l'ottimizzazione fallisce si usano
        valori standard (alpha 0.08, beta 0.90) con varianza di lungo periodo pari a quella campionaria.
        """
        returns = series.pct_change().dropna().values[-max_obs:] * 100.0
        if len(returns) < 30:
            return float(np.std(returns)) if len(returns) > 1 else 0.0
        returns = returns - returns.mean()
        sample_var = float(returns.var())
        if sample_var <= 0:
            return 0.0
        shocks = np.concatenate(([0.0], returns[:-1] ** 2))

        def variance_path(params):
            # var[t] = omega + alpha * r[t-1]^2 + beta * var[t-1], con var[0] = varianza campionaria
            omega, alpha, beta = params
            drive = omega + alpha * shocks
            drive[0] = sample_var
            return lfilter([1.0], [1.0, -beta], drive)

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

    def expected_price_path(self, close: pd.Series, garch_vol_pct: float, hurst: float, z_score: float,
                            horizon_bars: int = 24, drift_window: int = 20) -> Dict[str, Any]:
        """
        Curva di Traiettoria Attesa (Expected Price Path) sulle prossime `horizon_bars` barre.
        Drift per barra: media dei rendimenti recenti, mantenuta in regime trending (H > 0.55), attenuata
        in random walk e invertita verso la media in regime mean-reverting (H < 0.45, proporzionale allo Z-Score).
        Banda: ±1σ GARCH x sqrt(barre), cioè la volatilità reale prevista e non un'ampiezza fissa.
        `point_at(bars)` di guardian usa gli stessi parametri: expected = last x (1 + drift)^bars.
        """
        rets = close.pct_change().dropna().values[-drift_window:]
        last = float(close.iloc[-1])
        sigma = max(float(garch_vol_pct) / 100.0, 1e-6)
        drift = float(np.mean(rets)) if len(rets) else 0.0
        if hurst > 0.55:
            regime = "TRENDING"
        elif hurst < 0.45:
            regime = "MEAN_REVERTING"
            drift = -float(np.clip(z_score, -3.0, 3.0)) * sigma * 0.25
        else:
            regime = "RANDOM_WALK"
            drift *= 0.5
        # Il drift non può superare mezzo sigma per barra: evita traiettorie esplosive da poche barre anomale
        drift = float(np.clip(drift, -0.5 * sigma, 0.5 * sigma))
        steps = np.arange(1, horizon_bars + 1)
        expected = last * (1.0 + drift) ** steps
        band = sigma * np.sqrt(steps)
        return {
            "anchor_price": round(last, 6),
            "drift_pct_per_bar": round(drift * 100, 5),
            "vol_pct_per_bar": round(sigma * 100, 5),
            "horizon_bars": horizon_bars,
            "regime": regime,
            "expected_end_price": round(float(expected[-1]), 6),
            "upper_end_price": round(float(expected[-1] * (1 + band[-1])), 6),
            "lower_end_price": round(float(expected[-1] * (1 - band[-1])), 6),
        }

    def fast_screen(self, close: pd.Series, window: int = 120) -> Dict[str, Any]:
        """
        STAGE 1 (Fast-Quant): solo Hurst, Z-Score e Volatility Spike sulle ultime `window` chiusure.
        Pensato per stare sotto i 5 ms: niente GARCH, Koopman o quantili.
        interesting = il prezzo si sta comportando in modo non casuale (eccesso statistico,
        shock di volatilità o regime chiaramente trending / mean-reverting).
        """
        tail = close.iloc[-window:].astype(float)
        if len(tail) < 30:
            return {"hurst": 0.5, "z_score": 0.0, "vol_spike": 0.0, "interesting": False}
        z = self.calculate_z_score(tail)
        h = self.calculate_hurst_exponent(tail)
        rets = np.diff(tail.values) / tail.values[:-1]
        sigma = float(np.std(rets[-51:-1])) or 1e-12
        spike = float(abs(rets[-1]) / sigma)
        interesting = abs(z) >= 1.5 or spike >= 2.0 or h <= 0.35 or h >= 0.65
        return {"hurst": round(h, 4), "z_score": round(z, 4), "vol_spike": round(spike, 2), "interesting": interesting}

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
        path = self.expected_price_path(close_prices, garch_vol, hurst, z_score)

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
            },
            "expected_path": path
        }

# Alias usato dall'orchestratore quant_core.py
QuantEngineAgent = HyperQuantAgent
