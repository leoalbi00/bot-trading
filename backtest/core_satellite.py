"""Backtest core + satellite: SPY con il filtro di regime del bot (agents/core_allocation.py) + Portfolio Allocator.

Il core segue le costanti di core_allocation (95% / 33.25% della quota, regime a 3 chiusure); i due conti sono
ribilanciati al peso obiettivo il primo giorno di ogni mese. Periodi e dati di backtest/portfolio_sim.py.
Uso: python backtest/core_satellite.py [--cache file.pkl] [--verifica]
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest import portfolio_sim as ps
from agents import core_allocation as ca
from agents import portfolio_allocator as pa

COST = 0.0005


def core_returns(spy):
    """Rendimenti giornalieri del core: SPY 95% in trend, 33% sotto trend confermato (3 chiusure sotto EMA100)."""
    ema = spy.ewm(span=100, adjust=False).mean()
    below = (spy < ema).astype(int)
    up = (below.rolling(pa.REGIME_CONFIRM_DAYS).sum() < pa.REGIME_CONFIRM_DAYS).shift(1).fillna(True)
    expo = pd.Series(np.where(up, ca.CORE_EXPOSURE_UP / 100, ca.CORE_EXPOSURE_DOWN / 100), index=spy.index)
    return expo * spy.pct_change().fillna(0) - expo.diff().abs().fillna(0) * COST


def mix(core_r, bot_r, w_core):
    """Due conti separati ribilanciati al peso obiettivo il primo giorno di ogni mese."""
    idx = core_r.index.intersection(bot_r.index)
    c, b, eq = w_core, 1 - w_core, []
    month = None
    for d in idx:
        if month is not None and d.month != month:
            tot = c + b
            moved = abs(c - tot * w_core)
            c, b = tot * w_core, tot * (1 - w_core)
            c -= moved * COST
        month = d.month
        c *= 1 + core_r[d]
        b *= 1 + bot_r[d]
        eq.append(c + b)
    return pd.Series(eq, index=idx)


def stats(eq):
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (f"CAGR {((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100:6.1f}%  Sharpe {r.mean() / r.std() * np.sqrt(252):5.2f}  "
            f"MaxDD {(eq / eq.cummax() - 1).min() * 100:6.1f}%  giorno peggiore {r.min() * 100:5.1f}%  "
            f"migliore {r.max() * 100:4.1f}%")


if __name__ == "__main__":
    market = ps.Market(ps.load_data(sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else None))
    spy = market.close["SPY"].dropna()
    core_r = core_returns(spy)
    periods = {"sviluppo": ps.PERIODS["sviluppo"]}
    if "--verifica" in sys.argv:
        periods["verifica"] = ps.PERIODS["verifica"]
    for per, (a, b) in periods.items():
        curve = ps.simulate(market, "allocatore", a, b)[0]
        curve.index = ps.daily_index(curve.index.tz_convert(ps.TZ))
        bot_r = curve.groupby(level=0).last().pct_change().dropna()
        idx = bot_r.index
        print(per, a, b)
        print(f"  {'SPY comprato e tenuto':24s}", stats((1 + spy.pct_change().reindex(idx).fillna(0)).cumprod()))
        print(f"  {'solo core SPY+regime':24s}", stats((1 + core_r.reindex(idx).fillna(0)).cumprod()))
        print(f"  {'solo bot':24s}", stats((1 + bot_r).cumprod()))
        for w in (0.5, 0.7, 0.8):
            print(f"  {f'core {w:.0%} / bot {1 - w:.0%}':24s}", stats(mix(core_r.reindex(idx).fillna(0), bot_r, w)))
