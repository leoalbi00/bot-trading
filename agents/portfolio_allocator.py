"""Portfolio Allocator: budget di rischio dinamico al posto dei limiti fissi (posizioni, esposizione, bande di allocazione).

La capacità del portafoglio non è un numero di posizioni ma un budget di rischio ("heat"): la perdita aperta se tutti
gli stop scattassero insieme. Budget e taglie dipendono da dati letti a ogni ciclo:
- regime di mercato: SPY rispetto alla EMA100 e VIX;
- drawdown del conto dal massimo storico;
- volatilità del titolo: distanza dello stop = 3 x ATR%, quindi titoli più volatili ricevono meno capitale;
- forza relativa del titolo nell'universo (rank del momentum).

Parametri validati su dati orari reali (sviluppo 01/2024-06/2025, verifica mai vista 07/2025-10/2026): vedi
backtest/portfolio_sim.py. Modulo senza I/O: lo usano sia il bot sia il backtest, così il codice provato è quello eseguito.
"""
from typing import Any, Dict, Optional

RISK_PER_TRADE_PCT = 0.75      # rischio base allo stop, % del capitale
MAX_HEAT_PCT = 8.0             # rischio aperto massimo con regime favorevole, % del capitale
MAX_GROSS_PCT = 95.0           # esposizione massima con regime favorevole (mai margine)
CASH_FLOOR_PCT = 3.0           # liquidità minima sempre disponibile
MAX_POSITION_PCT = 15.0        # taglia massima di una posizione
MAX_CRYPTO_PCT = 20.0          # esposizione crypto massima
MAX_POSITIONS = 15             # limite operativo: la capacità reale la decide la heat
MIN_POSITION_PCT = 1.0         # sotto questa taglia il trade non vale i costi

STOP_ATR_MULT = 3.0            # stop = 3 x ATR% giornaliero nella fascia sotto
STOP_MIN_PCT = 1.5
STOP_MAX_PCT = 9.0
TARGET_R = 3.0                 # Target 1 (vende il 50%) a 3R
BREAKEVEN_TRIGGER_R = 1.0      # stop a breakeven + commissioni appena il picco arriva a +1R, anche prima del Target 1.
                               # Senza: il 30% delle perdite era stato a +1R e il 52-57% a +3% (backtest 11/2026).
                               # Effetto su barre orarie: da neutro (11.8% -> 11.4% annuo, PF 1.06 -> 1.19, caso peggiore
                               # dentro la barra) a +7 punti (2.5% -> 9.5%, caso migliore) nella verifica 07/2025-10/2026.
TRAIL_ATR_MULT = 3.0           # Chandelier Exit del runner
TREND_EXIT_EMA50_RATIO = 0.97  # uscita se il prezzo chiude sotto il 97% della EMA50 giornaliera
MIN_RANK = 0.70                # solo il 30% più forte dell'universo
MIN_DOLLAR_VOLUME = 50_000_000 # controvalore medio giornaliero minimo: l'universo validato è di titoli molto liquidi
MIN_PRICE = 5.0
REGIME_CONFIRM_DAYS = 3        # il regime azionario passa a "sotto trend" solo dopo 3 chiusure consecutive sotto la EMA100:
                               # una sola chiusura sotto di pochi decimi tagliava l'esposizione da 95% a 33% (02/11/2026).
                               # SPY 1995-2024: cambi di regime da 11.6 a 5.8 l'anno, Sharpe 0.69 -> 0.76; 2-5 giorni tutti meglio di 1.


def trend_up_confirmed(closes, emas, confirm_days: int = REGIME_CONFIRM_DAYS) -> bool:
    """False solo se le ultime `confirm_days` chiusure completate sono tutte sotto la loro EMA (sequenze allineate)."""
    pairs = list(zip(closes, emas))[-confirm_days:]
    if len(pairs) < confirm_days:
        return True
    return not all(float(c) < float(e) for c, e in pairs)


def regime_scale(trend_up: bool, vix: Optional[float]) -> float:
    """1 = favorevole, 0.6 = trend ma VIX alto, 0.35 = sotto trend, 0 = sotto trend con panico."""
    level = 20.0 if vix is None else float(vix)
    if trend_up:
        return 0.6 if level >= 25 else 1.0
    return 0.0 if level >= 30 else 0.35


def drawdown_scale(drawdown_pct: float) -> float:
    """Riduce il rischio se il conto perde dal massimo: dimezza oltre -5%, un quarto oltre -10%."""
    if drawdown_pct > -5:
        return 1.0
    return 0.5 if drawdown_pct > -10 else 0.25


def risk_limits(trend_up: bool, vix: Optional[float], drawdown_pct: float = 0.0) -> Dict[str, float]:
    """Limiti del momento in % del capitale."""
    regime = regime_scale(trend_up, vix)
    return {
        "regime": regime,
        "drawdown_scale": drawdown_scale(drawdown_pct),
        "risk_pct": RISK_PER_TRADE_PCT * regime * drawdown_scale(drawdown_pct),
        "heat_pct": MAX_HEAT_PCT * max(regime, 0.2),
        "gross_pct": MAX_GROSS_PCT * regime,
    }


def conviction_factor(rank: Optional[float]) -> float:
    """Da 0.6 (rank 0.70) a 1.4 (rank 1.00); senza rank taglia base."""
    if rank is None:
        return 1.0
    return 0.6 + 0.8 * max(0.0, (float(rank) - MIN_RANK) / (1.0 - MIN_RANK))


def stop_pct(atr_pct: Optional[float]) -> float:
    """Stop in % positivo: si adatta alla volatilità; senza ATR il limite largo della fascia."""
    if not atr_pct or atr_pct <= 0:
        return STOP_MAX_PCT
    return min(STOP_MAX_PCT, max(STOP_MIN_PCT, STOP_ATR_MULT * float(atr_pct)))


def open_risk_usd(market_value: float, pnl_pct: float, effective_stop_pct: float) -> float:
    """Perdita dal prezzo attuale allo stop effettivo. pnl_pct e stop sono % rispetto al prezzo d'ingresso."""
    price, stop = 1 + pnl_pct / 100, 1 + effective_stop_pct / 100
    if price <= 0:
        return 0.0
    return max(0.0, abs(market_value) * (1 - stop / price))


def size_trade(equity: float, exposure: float, funds: float, open_risk: float, positions: int, limits: Dict[str, float],
               stop: float, rank: Optional[float] = None, crypto: bool = False, crypto_exposure: float = 0.0) -> Dict[str, Any]:
    """Importo del nuovo trade. -> {"amount", "risk_pct", "allocation_pct", "reason"}; amount 0 = trade non eseguibile."""
    def no(reason):
        return {"amount": 0.0, "risk_pct": 0.0, "allocation_pct": 0.0, "reason": reason}

    if equity <= 0:
        return no("capitale non disponibile")
    if limits["regime"] <= 0:
        return no("regime di panico: nessun nuovo rischio")
    if positions >= MAX_POSITIONS:
        return no(f"{positions}/{MAX_POSITIONS} posizioni")
    risk_pct = limits["risk_pct"] * conviction_factor(rank)
    heat = open_risk / equity * 100
    if heat + risk_pct > limits["heat_pct"]:
        return no(f"budget di rischio esaurito ({heat:.2f}% + {risk_pct:.2f}% > {limits['heat_pct']:.2f}%)")
    amount = min(equity * risk_pct / stop, equity * MAX_POSITION_PCT / 100)
    amount = min(amount, equity * limits["gross_pct"] / 100 - exposure, funds - equity * CASH_FLOOR_PCT / 100)
    if crypto:
        amount = min(amount, equity * MAX_CRYPTO_PCT / 100 - crypto_exposure)
    if amount < equity * MIN_POSITION_PCT / 100:
        return no(f"margine residuo insufficiente (${max(amount, 0):,.0f})")
    return {"amount": round(amount, 2), "risk_pct": round(amount * stop / equity, 3),
            "allocation_pct": round(amount / equity * 100, 2),
            "reason": f"rischio {amount * stop / equity:.2f}% del capitale con stop {stop:.2f}%"}
