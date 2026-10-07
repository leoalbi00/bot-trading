"""Rilevatori delle 6 categorie di Scout.

Ogni rilevatore riceve le candele 1h CHIUSE (colonne minuscole open/high/low/close/volume)
e, se disponibile, lo snapshot L2 del book ({"bids": [[prezzo, size]], "asks": [...]}).
Restituisce {"triggered": bool, "side": "LONG"|"SHORT"|"NONE", "strength": 0-1, "detail": str}.
Solo calcoli numpy/pandas: nessuna chiamata di rete.
"""
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

CATEGORIES = ("Breakout", "Volatility", "Orderbook", "Volume", "Whale Tracking", "Mean Reversion")

BREAKOUT_LOOKBACK = 20
VOL_SPIKE_ATR_RATIO = 1.5      # ATR(14) / ATR(100)
VOL_SPIKE_SIGMA = 2.5          # rendimento dell'ultima candela oltre 2.5 deviazioni standard
BOOK_IMBALANCE = 0.30          # |OFI| sui primi 10 livelli
RVOL_SPIKE = 2.0
WHALE_VOLUME_Z = 3.0           # candela con volume oltre 3 deviazioni standard
WHALE_WALL_RATIO = 5.0         # livello del book 5 volte più grande della media dei livelli
MEAN_REV_Z = 2.0
MEAN_REV_HURST = 0.45


def _signal(triggered: bool, side: str = "NONE", strength: float = 0.0, detail: str = "") -> Dict[str, Any]:
    return {"triggered": bool(triggered), "side": side if triggered else "NONE",
            "strength": float(np.clip(strength, 0.0, 1.0)) if triggered else 0.0, "detail": detail}


def _atr(df: pd.DataFrame, window: int) -> float:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(window).mean().iloc[-1])


def hurst_exponent(close: np.ndarray, max_lag: int = 20) -> float:
    """Esponente di Hurst con lo stesso metodo dell'Agente #1 (deviazione delle differenze per lag)."""
    if len(close) < max_lag + 2:
        return 0.5
    lags = np.arange(2, max_lag)
    tau = np.array([np.sqrt(np.std(close[lag:] - close[:-lag])) for lag in lags])
    if np.any(tau <= 0):
        return 0.5
    return float(np.clip(np.polyfit(np.log(lags), np.log(tau), 1)[0] * 2.0, 0.0, 1.0))


def breakout(df: pd.DataFrame, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chiusura oltre il massimo (o sotto il minimo) delle 20 candele precedenti."""
    if len(df) < BREAKOUT_LOOKBACK + 15:
        return _signal(False, detail="dati insufficienti")
    prior = df.iloc[-BREAKOUT_LOOKBACK - 1:-1]
    close, hi, lo = float(df["close"].iloc[-1]), float(prior["high"].max()), float(prior["low"].min())
    atr = _atr(df, 14) or 1e-12
    if close > hi:
        return _signal(True, "LONG", (close - hi) / atr, f"chiusura {close:.4f} sopra il massimo a 20 candele {hi:.4f}")
    if close < lo:
        return _signal(True, "SHORT", (lo - close) / atr, f"chiusura {close:.4f} sotto il minimo a 20 candele {lo:.4f}")
    return _signal(False, detail=f"in range {lo:.4f}-{hi:.4f}")


def volatility(df: pd.DataFrame, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Espansione di volatilità: ATR breve contro ATR lungo, oppure candela fuori scala."""
    if len(df) < 110:
        return _signal(False, detail="dati insufficienti")
    ratio = _atr(df, 14) / (_atr(df, 100) or 1e-12)
    rets = df["close"].pct_change().dropna().values
    sigma = float(np.std(rets[-51:-1])) or 1e-12
    shock = abs(rets[-1]) / sigma
    side = "LONG" if rets[-1] > 0 else "SHORT"
    if ratio >= VOL_SPIKE_ATR_RATIO or shock >= VOL_SPIKE_SIGMA:
        return _signal(True, side, max(ratio / 3, shock / 5), f"ATR14/ATR100 {ratio:.2f}, ultima candela {shock:.1f}σ")
    return _signal(False, detail=f"ATR14/ATR100 {ratio:.2f}, ultima candela {shock:.1f}σ")


def orderbook(df: pd.DataFrame, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Squilibrio del book L2 (solo crypto: Alpaca non fornisce L2 sulle azioni)."""
    bids, asks = (book or {}).get("bids") or [], (book or {}).get("asks") or []
    bid, ask = sum(float(l[1]) for l in bids[:10]), sum(float(l[1]) for l in asks[:10])
    if bid + ask <= 0:
        return _signal(False, detail="book L2 non disponibile")
    ofi = (bid - ask) / (bid + ask)
    if abs(ofi) >= BOOK_IMBALANCE:
        return _signal(True, "LONG" if ofi > 0 else "SHORT", abs(ofi), f"OFI {ofi:+.2f} (bid {bid:.4g} / ask {ask:.4g})")
    return _signal(False, detail=f"OFI {ofi:+.2f}")


def volume(df: pd.DataFrame, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Volume relativo dell'ultima candela chiusa contro la media delle 20 precedenti."""
    if len(df) < 25:
        return _signal(False, detail="dati insufficienti")
    avg = float(df["volume"].iloc[-21:-1].mean())
    if avg <= 0:
        return _signal(False, detail="volume medio nullo")
    rvol = float(df["volume"].iloc[-1]) / avg
    side = "LONG" if df["close"].iloc[-1] >= df["open"].iloc[-1] else "SHORT"
    if rvol >= RVOL_SPIKE:
        return _signal(True, side, rvol / 5, f"RVOL {rvol:.1f}x")
    return _signal(False, detail=f"RVOL {rvol:.1f}x")


def whale_tracking(df: pd.DataFrame, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Grandi operatori: candela con volume estremo (z-score) o muro nel book L2."""
    if len(df) < 60:
        return _signal(False, detail="dati insufficienti")
    vols = df["volume"].iloc[-60:-1].astype(float)
    std = float(vols.std()) or 1e-12
    z = (float(df["volume"].iloc[-1]) - float(vols.mean())) / std
    side = "LONG" if df["close"].iloc[-1] >= df["open"].iloc[-1] else "SHORT"
    if z >= WHALE_VOLUME_Z:
        return _signal(True, side, z / 8, f"volume a {z:.1f}σ dalla media")
    for name, levels, wall_side in (("bid", (book or {}).get("bids") or [], "LONG"),
                                    ("ask", (book or {}).get("asks") or [], "SHORT")):
        sizes = [float(l[1]) for l in levels[:10]]
        if len(sizes) >= 3:
            biggest, mean = max(sizes), float(np.mean(sizes))
            if mean > 0 and biggest >= WHALE_WALL_RATIO * mean:
                return _signal(True, wall_side, biggest / mean / 15, f"muro {name} {biggest / mean:.1f}x la media dei livelli")
    return _signal(False, detail=f"volume a {z:.1f}σ")


def mean_reversion(df: pd.DataFrame, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Eccesso statistico (|Z| >= 2) in un regime anti-persistente (Hurst < 0.45)."""
    if len(df) < 60:
        return _signal(False, detail="dati insufficienti")
    close = df["close"].astype(float)
    window = close.iloc[-20:]
    std = float(window.std()) or 1e-12
    z = (float(close.iloc[-1]) - float(window.mean())) / std
    h = hurst_exponent(close.iloc[-100:].values)
    if abs(z) >= MEAN_REV_Z and h < MEAN_REV_HURST:
        return _signal(True, "LONG" if z < 0 else "SHORT", abs(z) / 4, f"Z {z:+.2f}, Hurst {h:.2f}")
    return _signal(False, detail=f"Z {z:+.2f}, Hurst {h:.2f}")


DETECTORS = {
    "Breakout": breakout,
    "Volatility": volatility,
    "Orderbook": orderbook,
    "Volume": volume,
    "Whale Tracking": whale_tracking,
    "Mean Reversion": mean_reversion,
}
