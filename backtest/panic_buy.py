"""Backtest degli acquisti nel panico (agents/panic_buyer.py, lo stesso modulo eseguito dal bot).

SPY giornaliero 1993-2026 da yfinance (VOO esiste dal 2010: stesso indice). Ingresso all'apertura con il VIX della chiusura
precedente, uscita alla chiusura. Costi 0,05% per lato. Rendimenti espressi sul capitale TOTALE del conto.
Sviluppo 1993-2009, verifica 2010-2026.

Uso: python backtest/panic_buy.py
"""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents import panic_buyer as pb

COST = 0.0005
CAPITAL = 100_000.0


def simulate(df):
    """df: colonne o (apertura SPY), c (chiusura SPY), v (chiusura VIX), indice di date di borsa."""
    days = [d.date() for d in df.index]
    weekdays = pd.bdate_range(df.index[0], df.index[-1])
    holidays = [d.strftime("%Y-%m-%d") for d in weekdays if d not in set(df.index)]
    cash, shares, cost_basis = CAPITAL, 0.0, 0.0
    ep = {"tranches": 0, "first": None, "last": None}
    curve, episodes, ep_start = [CAPITAL], [], None
    vix_prev = df["v"].shift(1).values
    for i in range(1, len(df)):
        o, c, v, today = df["o"].iloc[i], df["c"].iloc[i], df["v"].iloc[i], days[i]
        equity_open = cash + shares * o
        buy = pb.entry_amount(vix_prev[i], ep, today, equity_open, cash, holidays=holidays)
        if buy["amount"] > 0:
            if ep["tranches"] == 0:
                ep_start, ep["first"] = equity_open, today
            shares += buy["amount"] * (1 - COST) / o
            cash -= buy["amount"]
            cost_basis += buy["amount"]
            ep["tranches"] += 1
            ep["last"] = today
        if shares:
            reason = pb.exit_reason(v, ep, today, c, cost_basis / shares, holidays=holidays)
            if reason:
                cash += shares * c * (1 - COST)
                episodes.append((ep["first"], today, ep["tranches"], (cash - ep_start) / ep_start, reason))
                shares, cost_basis = 0.0, 0.0
                ep = {"tranches": 0, "first": None, "last": ep["last"]}
        curve.append(cash + shares * c)
    return pd.Series(curve, index=df.index), episodes


def main():
    d = yf.download(["SPY", "^VIX"], start="1993-01-01", auto_adjust=True, progress=False)
    df = pd.DataFrame({"o": d["Open"]["SPY"], "c": d["Close"]["SPY"], "v": d["Close"]["^VIX"].ffill()}).dropna()
    for label, part in (("sviluppo 1993-2009", df[:"2009-12-31"]), ("verifica 2010-2026", df["2010-01-01":])):
        curve, eps = simulate(part)
        res = np.array([e[3] for e in eps])
        years = len(part) / 252
        dd = (curve / curve.cummax() - 1).min()
        print(f"{label}: {len(eps)} episodi, guadagno sul capitale totale {(curve.iloc[-1] / CAPITAL - 1) * 100:+.1f}% "
              f"({((curve.iloc[-1] / CAPITAL) ** (1 / years) - 1) * 100:+.2f}%/anno), in utile {(res > 0).mean() * 100:.0f}%, "
              f"media {res.mean() * 100:+.2f}%, peggiore {res.min() * 100:+.2f}%, MaxDD del conto {dd * 100:.1f}%")
        for first, last, n, r, why in sorted(eps, key=lambda e: e[3])[:3]:
            print(f"   {first} → {last}: {n} tranche, {r * 100:+.2f}% ({why})")


if __name__ == "__main__":
    main()
