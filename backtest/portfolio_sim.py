"""Backtest del portafoglio su barre orarie reali (yfinance): logica precedente contro Portfolio Allocator.

Usa agents/portfolio_allocator.py, lo stesso modulo eseguito dal bot. Periodi: sviluppo 01/2024-06/2025 (parametri scelti
qui), verifica 07/2025-10/2026. Limiti da tenere presenti: universo di titoli attuali (survivorship bias), notizie non
riproducibili sullo storico, ingressi una volta al giorno, esecuzioni simulate con costi fissi.

Uso: python backtest/portfolio_sim.py [--cache file.pkl]
"""
import argparse
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents import portfolio_allocator as pa

warnings.filterwarnings("ignore")
STOCKS = """NVDA AAPL MSFT TSLA AMD GOOGL AMZN META PLTR COIN SMCI AVGO NFLX CRM ORCL ADBE QCOM INTC MU UBER SHOP
JPM BAC GS MS V MA AXP WFC C SCHW UNH LLY JNJ PFE MRK ABBV REGN VRTX ISRG TMO XOM CVX COP SLB OXY CAT DE GE BA HON LMT RTX
WMT COST HD LOW MCD NKE SBUX KO PEP PG DIS T VZ CMCSA F GM DAL UAL NEE DUK AMT PLD GLD SLV USO TLT XLE XLF SMH XBI""".split()
CRYPTO = "BTC-USD ETH-USD SOL-USD AVAX-USD LINK-USD DOGE-USD LTC-USD".split()
ALL = STOCKS + CRYPTO
TZ = "America/New_York"
PERIODS = {"sviluppo": ("2024-01-02", "2025-07-01"), "verifica": ("2025-07-01", "2026-11-01")}
COST = {True: 0.0030, False: 0.0005}   # per lato: crypto taker + spread, azioni slippage
FEE_BUFFER = {True: 0.0055, False: 0.0005}


def load_data(cache):
    if cache and os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)
    tickers = ALL + ["SPY", "QQQ", "^VIX"]
    data = {"h": yf.download(tickers, period="729d", interval="1h", group_by="ticker", auto_adjust=True, progress=False),
            "d": yf.download(tickers, period="4y", interval="1d", group_by="ticker", auto_adjust=True, progress=False)}
    if cache:
        with open(cache, "wb") as f:
            pickle.dump(data, f)
    return data


def daily_index(idx):
    idx = pd.to_datetime(idx)
    return (idx.tz_localize(None) if idx.tz is not None else idx).normalize()


class Market:
    """Prezzi orari e segnali giornalieri, sempre riferiti al giorno precedente (nessun lookahead)."""

    def __init__(self, data):
        hourly, daily = data["h"], data["d"]
        self.idx = hourly.index
        self.bars = {t: {c: hourly[t][c].values for c in ("Open", "High", "Low", "Close")} for t in ALL}
        close = pd.DataFrame({t: daily[t]["Close"] for t in ALL + ["SPY", "^VIX"]})
        close.index = daily_index(close.index)
        close = close[~close.index.duplicated()].ffill()
        atr = {}
        for t in ALL:
            x = daily[t][["Close", "High", "Low"]].dropna()
            x.index = daily_index(x.index)
            prev = x["Close"].shift(1)
            tr = pd.concat([x["High"] - x["Low"], (x["High"] - prev).abs(), (x["Low"] - prev).abs()], axis=1).max(axis=1)
            atr[t] = tr.rolling(14).mean() / x["Close"] * 100
        self.atr = pd.DataFrame(atr).reindex(close.index).ffill().shift(1)
        px = close[ALL]
        self.ema20, self.ema50, self.px = px.ewm(span=20).mean().shift(1), px.ewm(span=50).mean().shift(1), px.shift(1)
        vol = px.pct_change().rolling(63).std().shift(1) * np.sqrt(252)
        self.rank = ((px.shift(6) / px.shift(127) - 1) / vol).rank(axis=1, pct=True)
        self.trend = (self.px > self.ema20) & (self.ema20 > self.ema50)
        spy, btc = close["SPY"], close["BTC-USD"]
        self.spy_up = (spy > spy.ewm(span=100).mean()).shift(1)
        self.spy_50 = (spy > spy.ewm(span=50).mean()).shift(1)
        self.btc_up = (btc > btc.ewm(span=100).mean()).shift(1)
        self.vix = close["^VIX"].shift(1)
        self.close = close


def enter(pos, sym, price, amount, stop, target_r, trail, ts):
    crypto = sym in CRYPTO
    fill = price * (1 + COST[crypto])
    pos[sym] = {"q": amount / fill, "entry": fill, "stop": fill * (1 - stop), "target": fill * (1 + target_r * stop),
                "scaled": False, "peak": fill, "trail": trail, "last": price, "t0": ts}


def effective_stop(sym, p):
    if not p["scaled"]:
        return p["stop"]
    return max(p["stop"], p["entry"] * (1 + FEE_BUFFER[sym in CRYPTO]), p["peak"] * (1 - p["trail"]))


def simulate(market, mode, start, end, signals=None):
    """mode "attuale": 4 posizioni, 50%, allocazione fissa, stop 1.2-3.5% su signals; "allocatore": Portfolio Allocator."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    days = pd.DatetimeIndex(market.idx.tz_convert(TZ)).normalize().tz_localize(None)
    hours = market.idx.tz_convert(TZ).hour
    equity = peak = cash = 100000.0
    pos, curve, invested, closed = {}, [], [], []
    for i, ts in enumerate(market.idx):
        day = days[i]
        if day < start or day >= end or day not in market.px.index:
            continue
        for sym in list(pos):
            p, bar = pos[sym], market.bars[sym]
            o, h, l, c = bar["Open"][i], bar["High"][i], bar["Low"][i], bar["Close"][i]
            if np.isnan(c):
                continue
            p["last"], p["peak"] = c, max(p["peak"], h)
            cost = COST[sym in CRYPTO]
            stop = effective_stop(sym, p)
            if l <= stop:
                fill = min(o, stop) * (1 - cost)
                cash += p["q"] * fill
                closed.append((fill / p["entry"] - 1) * 100)
                del pos[sym]
            elif not p["scaled"] and h >= p["target"]:
                cash += p["q"] * 0.5 * max(o, p["target"]) * (1 - cost)
                p["q"] *= 0.5
                p["scaled"] = True
        value = sum(p["q"] * p["last"] for p in pos.values())
        equity, peak = cash + value, max(peak, cash + value)
        curve.append((ts, equity))
        invested.append(value / equity)
        if hours[i] != 10:
            continue
        if mode == "attuale":
            cash = entries_current(market, pos, cash, equity, signals.get(day, ()), i, day, ts)
        else:
            cash = exits_trend(market, pos, cash, i, day, closed)   # come il ciclo del CIO: prima le vendite, poi gli acquisti
            cash = entries_allocator(market, pos, cash, equity, peak, i, day, ts)
    return pd.Series(dict(curve)), closed, float(np.mean(invested))


def entries_current(market, pos, cash, equity, candidates, i, day, ts):
    for sym in candidates:
        price = market.bars[sym]["Open"][i]
        atr = market.atr.at[day, sym]
        if len(pos) >= 4 or sym in pos or np.isnan(price) or np.isnan(atr):
            continue
        stop = float(np.clip(1.5 * atr, 1.2, 3.5)) / 100
        crypto = sym in CRYPTO
        up = market.btc_up.get(day, False) if crypto else market.spy_50.get(day, False)
        amount = min(equity * 0.115 * (1 if up else 0.5), equity * 0.5 - sum(p["q"] * p["last"] for p in pos.values()), cash)
        if amount >= equity * 0.04:
            enter(pos, sym, price, amount, stop, 2.0, (2.0 if crypto else 1.5) * atr / 100, ts)
            cash -= amount
    return cash


def entries_allocator(market, pos, cash, equity, peak, i, day, ts):
    vix = market.vix.get(day)
    limits = pa.risk_limits(bool(market.spy_up.get(day, False)), None if pd.isna(vix) else vix, (equity / peak - 1) * 100)
    rank = market.rank.loc[day]
    for sym in rank[market.trend.loc[day] & (rank >= pa.MIN_RANK)].sort_values(ascending=False).index:
        crypto = sym in CRYPTO
        price, atr = market.bars[sym]["Open"][i], market.atr.at[day, sym]
        if sym in pos or (crypto and not market.btc_up.get(day, False)) or np.isnan(price) or np.isnan(atr):
            continue
        stop = pa.stop_pct(atr)
        open_risk = sum(max(0.0, p["q"] * (p["last"] - effective_stop(k, p))) for k, p in pos.items())
        sized = pa.size_trade(equity, sum(p["q"] * p["last"] for p in pos.values()), cash, open_risk, len(pos), limits, stop,
                              rank=rank[sym], crypto=crypto,
                              crypto_exposure=sum(p["q"] * p["last"] for k, p in pos.items() if k in CRYPTO))
        if sized["amount"]:
            enter(pos, sym, price, sized["amount"], stop / 100, pa.TARGET_R, pa.TRAIL_ATR_MULT * atr / 100, ts)
            cash -= sized["amount"]
        elif "budget" in sized["reason"]:
            break
    return cash


def exits_trend(market, pos, cash, i, day, closed):
    for sym in list(pos):
        price = market.bars[sym]["Open"][i]
        if not np.isnan(price) and market.px.at[day, sym] < market.ema50.at[day, sym] * pa.TREND_EXIT_EMA50_RATIO:
            fill = price * (1 - COST[sym in CRYPTO])
            cash += pos[sym]["q"] * fill
            closed.append((fill / pos[sym]["entry"] - 1) * 100)
            del pos[sym]
    return cash


def stats(curve, closed, invested):
    daily = curve.resample("1D").last().dropna()
    ret = daily.pct_change().dropna()
    years = (daily.index[-1] - daily.index[0]).days / 365.25
    cagr = (daily.iloc[-1] / daily.iloc[0]) ** (1 / years) - 1
    trades = np.array(closed) if closed else np.array([0.0])
    wins, losses = trades[trades > 0].sum(), -trades[trades <= 0].sum()
    return {"CAGR%": round(cagr * 100, 1), "Sharpe": round(ret.mean() / ret.std() * np.sqrt(252), 2),
            "MaxDD%": round(float((daily / daily.cummax() - 1).min()) * 100, 1), "Investito%": round(invested * 100),
            "Trade": len(closed), "PF": round(wins / losses, 2) if losses else None}


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--cache", default=None)
    args.add_argument("--signals", default=None, help="pickle {giorno: [ticker]} con i segnali Q>=70 per la logica attuale")
    opts = args.parse_args()
    market = Market(load_data(opts.cache))
    signals = pd.read_pickle(opts.signals) if opts.signals else None
    for name, (start, end) in PERIODS.items():
        spy = market.close["SPY"].loc[start:end]
        print(name, "SPY CAGR%", round(((spy.iloc[-1] / spy.iloc[0]) ** (365.25 / (spy.index[-1] - spy.index[0]).days) - 1) * 100, 1))
        if signals is not None:
            print("  attuale   ", stats(*simulate(market, "attuale", start, end, signals)))
        print("  allocatore", stats(*simulate(market, "allocatore", start, end)))
