"""Day-trading intraday su SPY: momentum con "area di rumore" (Zarattini, Aziz, Barbon 2024, "Beat the Market").

Regole dello studio, senza leva:
- area di rumore del minuto t = media degli ultimi 14 giorni di |prezzo al minuto t / apertura - 1|;
- banda superiore = max(apertura, chiusura di ieri) x (1 + rumore), inferiore = min(apertura, chiusura di ieri) x (1 - rumore);
- controllo ogni 30 minuti (10:00 ... 15:30 di New York): sopra la banda si compra, sotto si va short;
- stop al controllo successivo: long sotto max(banda superiore, VWAP), short sopra min(banda inferiore, VWAP);
- tutto chiuso prima della campanella: nessun rischio overnight;
- taglia = quota del capitale x min(1, 2% / volatilità giornaliera di SPY a 14 giorni) (volatility targeting dello studio).

Backtest (backtest/noise_area.py, barre da 1 minuto 2019-01 → 2025-07, costi 0,0045 $/azione, quota 80%):
- sviluppo 2019-2022: 7,8%/anno, Sharpe 1,37, MaxDD -5,3%; verifica 2023-2025: 3,6%/anno, Sharpe 0,81, MaxDD -3,3%;
- 2022 +13,7% con SPY -18,2%; correlazione giornaliera con SPY -0,04; rende di più con VIX 20-28 (13%/anno).
Non batte SPY negli anni di rialzo forte: il suo compito è guadagnare quando il mercato scende o oscilla.

Modulo senza I/O: lo usano sia il bot (app.py) sia il backtest, così le regole verificate sono le stesse eseguite.
"""
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

SYMBOL = "SPY"
ORDER_PREFIX = "dt-"             # client_order_id degli ordini del day-trading: esclusi dal registro dello swing
MAX_PCT = 80.0                   # quota massima del capitale per il day-trading
LOOKBACK_DAYS = 14
CHECK_STEP_MIN = 30              # controlli alle 10:00, 10:30, ... 15:30
SESSION_MINUTES = 390            # 09:30-16:00
VOL_TARGET = 0.02                # volatilità giornaliera obiettivo (studio: 2%)
VOL_DAYS = 14
FLAT_BEFORE_CLOSE_MIN = 5        # bot: posizione chiusa 5 minuti prima della chiusura (anche nelle giornate corte)
CHECK_GRACE_MIN = 10             # un controllo saltato (riavvio) vale ancora per 10 minuti, poi si aspetta il successivo
ET = "America/New_York"


def check_minutes(step: int = CHECK_STEP_MIN):
    """Minuti dall'apertura dei controlli: 30, 60, ... 360 (10:00 ... 15:30)."""
    return list(range(step, SESSION_MINUTES, step))


def session_frames(bars: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Matrici giorno x minuto (0 = 09:30) di chiusure e VWAP cumulato, più l'apertura di ogni giorno.

    bars: colonne open, high, low, close, volume; indice orario (con fuso o già in ora di New York).
    Le barre mancanti prendono l'ultimo prezzo noto; vanno bene anche barre da 5 minuti.
    """
    df = bars.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(ET).tz_localize(None)
    df.index = idx
    minute = np.asarray((idx.hour - 9) * 60 + idx.minute - 30)
    keep = (minute >= 0) & (minute < SESSION_MINUTES)
    df, minute = df[keep], minute[keep]
    df = df.assign(minute=minute, day=df.index.normalize())
    cols = range(SESSION_MINUTES)
    close = df.pivot_table(index="day", columns="minute", values="close").reindex(columns=cols).ffill(axis=1)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df = df.assign(pv=typical * df["volume"])
    pv = df.pivot_table(index="day", columns="minute", values="pv", aggfunc="sum").reindex(columns=cols).fillna(0).cumsum(axis=1)
    vv = df.pivot_table(index="day", columns="minute", values="volume", aggfunc="sum").reindex(columns=cols).fillna(0).cumsum(axis=1)
    vwap = (pv / vv.replace(0, np.nan)).ffill(axis=1)
    open_ = df.groupby("day")["open"].first()
    return {"close": close, "vwap": vwap, "open": open_.reindex(close.index)}


def noise_bands(frames: Dict[str, pd.DataFrame], lookback: int = LOOKBACK_DAYS) -> Dict[str, pd.DataFrame]:
    """Bande dell'area di rumore e volatilità di SPY, calcolate solo sui giorni precedenti (nessun lookahead)."""
    close, open_ = frames["close"], frames["open"]
    day_close = close[SESSION_MINUTES - 1]
    prev_close = day_close.shift(1)
    move = (close.div(open_, axis=0) - 1).abs()
    sigma = move.rolling(lookback).mean().shift(1)
    hi_ref, lo_ref = np.maximum(open_, prev_close), np.minimum(open_, prev_close)
    upper = sigma.mul(hi_ref, axis=0).add(hi_ref, axis=0)
    lower = (-sigma.mul(lo_ref, axis=0)).add(lo_ref, axis=0)
    vol = day_close.pct_change().rolling(VOL_DAYS).std().shift(1)
    return {"upper": upper, "lower": lower, "sigma": sigma, "prev_close": prev_close, "vol": vol}


def decide(position: int, price: float, upper: float, lower: float, vwap: Optional[float],
           allow_short: bool = True) -> Tuple[bool, int]:
    """(uscire dalla posizione attuale, nuovo ingresso 1/-1/0) a un controllo.

    position: 1 long, -1 short, 0 flat. Dopo un'uscita si può rientrare subito, anche dal lato opposto.
    """
    if any(v is None or not np.isfinite(v) for v in (price, upper, lower)):
        return False, 0
    vw = vwap if vwap is not None and np.isfinite(vwap) else None
    exit_now = (position == 1 and price < (max(upper, vw) if vw else upper)) or \
               (position == -1 and price > (min(lower, vw) if vw else lower))
    if position and not exit_now:
        return False, 0
    enter = 1 if price > upper else (-1 if allow_short and price < lower else 0)
    if exit_now and enter == position:
        return False, 0              # uscita e rientro dallo stesso lato allo stesso prezzo: si tiene, senza pagare i costi
    return exit_now, enter


def exposure_fraction(pct: float, vol: Optional[float], target: float = VOL_TARGET) -> float:
    """Quota del capitale da usare: pct% ridotto quando SPY è più volatile del 2% al giorno."""
    frac = max(0.0, min(pct, MAX_PCT)) / 100
    if vol is not None and np.isfinite(vol) and vol > 0:
        frac *= min(1.0, target / vol)
    return frac


def shares_for(equity: float, frac: float, price: float, cash_cap: Optional[float] = None) -> int:
    """Azioni intere (lo short non ammette frazioni): capitale x quota, mai oltre la liquidità disponibile."""
    if price <= 0 or equity <= 0:
        return 0
    budget = equity * frac
    if cash_cap is not None:
        budget = min(budget, max(0.0, cash_cap))
    return int(budget // price)


def check_due(minute_now: int, done: set, step: int = CHECK_STEP_MIN, grace: int = CHECK_GRACE_MIN) -> Optional[int]:
    """Controllo da eseguire ora (minuto dall'apertura) oppure None.

    Il controllo del minuto t usa la barra t, chiusa al minuto t+1; dopo `grace` minuti un controllo perso non si recupera.
    """
    due = [t for t in check_minutes(step) if t + 1 <= minute_now <= t + grace and t not in done]
    return due[-1] if due else None


def snapshot_at(frames: Dict[str, pd.DataFrame], bands: Dict[str, pd.DataFrame], day, minute: int) -> Dict[str, float]:
    """Prezzo, bande, VWAP e volatilità del giorno `day` al minuto `minute`."""
    def at(frame):
        try:
            value = frame.loc[day, minute]
        except KeyError:
            return float("nan")
        return float(value)
    vol = bands["vol"].get(day, float("nan"))
    return {"price": at(frames["close"]), "upper": at(bands["upper"]), "lower": at(bands["lower"]),
            "vwap": at(frames["vwap"]), "vol": float(vol) if vol is not None else float("nan"),
            "sigma": at(bands["sigma"])}
