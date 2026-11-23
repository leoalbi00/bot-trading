"""Backtest del day-trading su SPY (agents/day_trader.py, lo stesso modulo eseguito dal bot).

Dati: barre da 1 minuto di SPY 2019-01 → 2025-07 (fonte Polygon), pubblicate nel repository
github.com/Ascensao/Intraday-momentum-strategy (file spy_intra_data.csv, Git LFS). VIX giornaliero da yfinance.
Costi: commissione 0,0035 $/azione + slippage 0,001 $/azione per lato. Nessuna leva.
Sviluppo 2019-2022 (scelta delle regole), verifica 2023-2025 (mai usata per scegliere).

Uso: python backtest/noise_area.py spy_intra_data.csv [--pct 80] [--no-short] [--vix vix.csv]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents import day_trader as dtr

COST_PER_SHARE = 0.0035 + 0.001


def load_minutes(path):
    m = pd.read_csv(path, parse_dates=["caldt"]).set_index("caldt")
    return m[["open", "high", "low", "close", "volume"]]


def simulate(frames, bands, pct=80.0, allow_short=True, capital=100_000.0):
    """Rendimento giornaliero (frazione del capitale di inizio giornata) per ogni giorno con dati sufficienti."""
    close, vwap = frames["close"].values, frames["vwap"].values
    upper, lower = bands["upper"].values, bands["lower"].values
    checks = dtr.check_minutes()
    equity, out = capital, {}
    for i, day in enumerate(frames["close"].index):
        if np.isnan(upper[i, checks[0]]) or np.isnan(bands["prev_close"].iloc[i]):
            continue
        frac = dtr.exposure_fraction(pct, bands["vol"].iloc[i])
        pos, entry, shares, pnl, start = 0, 0.0, 0, 0.0, equity
        for t in checks:
            px = close[i, t]
            exit_now, enter = dtr.decide(pos, px, upper[i, t], lower[i, t], vwap[i, t], allow_short)
            if exit_now:
                pnl += pos * shares * (px - entry) - shares * COST_PER_SHARE
                pos = 0
            if enter and pos == 0:
                shares = dtr.shares_for(start, frac, px)
                pos, entry = enter, px
                pnl -= shares * COST_PER_SHARE
        if pos:
            px = close[i, dtr.SESSION_MINUTES - 1]
            pnl += pos * shares * (px - entry) - shares * COST_PER_SHARE
        equity += pnl
        out[day] = pnl / start
    return pd.Series(out)


def stats(x):
    years = len(x) / 252
    cagr = (1 + x).prod() ** (1 / years) - 1 if years else 0.0
    curve = (1 + x).cumprod()
    sharpe = x.mean() / x.std() * np.sqrt(252) if x.std() else 0.0
    return (f"{cagr * 100:6.1f}%/anno  Sharpe {sharpe:5.2f}  MaxDD {(curve / curve.cummax() - 1).min() * 100:6.1f}%  "
            f"giorni con posizione {(x != 0).mean() * 100:3.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes")
    ap.add_argument("--pct", type=float, default=dtr.MAX_PCT)
    ap.add_argument("--no-short", action="store_true")
    ap.add_argument("--vix", help="CSV con data e chiusura del VIX (altrimenti yfinance)")
    a = ap.parse_args()
    frames = dtr.session_frames(load_minutes(a.minutes))
    bands = dtr.noise_bands(frames)
    r = simulate(frames, bands, a.pct, not a.no_short)
    spy = frames["close"][dtr.SESSION_MINUTES - 1].pct_change().reindex(r.index).fillna(0)
    print(f"Day-trading SPY {a.pct:.0f}% del capitale{' solo long' if a.no_short else ''}, {r.index[0].date()} → {r.index[-1].date()}")
    for label, mask in (("sviluppo 2019-2022", r.index < "2023-01-01"), ("verifica 2023-2025", r.index >= "2023-01-01"),
                        ("tutto il periodo", r.index == r.index)):
        print(f"{label:20} day-trading {stats(r[mask])}\n{'':20} SPY         {stats(spy[mask])}")
    for y in sorted(set(r.index.year)):
        ry, sy = r[r.index.year == y], spy[spy.index.year == y]
        print(f"{y}: day-trading {((1 + ry).prod() - 1) * 100:+6.1f}%   SPY {((1 + sy).prod() - 1) * 100:+6.1f}%")
    if a.vix:
        vix = pd.read_csv(a.vix, index_col=0, parse_dates=True).iloc[:, 0]
    else:
        import yfinance as yf
        vix = yf.download("^VIX", start=str(r.index[0].date()), progress=False, auto_adjust=True)["Close"].squeeze()
    vix.index = pd.DatetimeIndex(vix.index).tz_localize(None).normalize()
    vix_prev = vix.shift(1).reindex(r.index).ffill()
    for lo, hi in ((0, 20), (20, 28), (28, 999)):
        mask = (vix_prev >= lo) & (vix_prev < hi)
        print(f"VIX {lo}-{hi}: day-trading {stats(r[mask])} | SPY {stats(spy[mask])}")
    print(f"Correlazione giornaliera con SPY: {r.corr(spy):.2f}")


if __name__ == "__main__":
    main()
