"""Acquisti a tranche dell'S&P 500 nel panico (VIX >= 28), con uscita quando la paura rientra.

Il day-trading con VIX >= 28 rende circa zero (backtest/noise_area.py), mentre storicamente l'indice dopo i picchi di paura
risale: questo modulo usa quella parte del capitale tattico. Strumento VOO (S&P 500): SPY resta al day-trading, così le due
posizioni non si mescolano nello stesso simbolo su Alpaca.

Regole (fissate prima del test, non ottimizzate), backtest/panic_buy.py su SPY 1993-2026:
- VIX alla chiusura precedente >= 28: tranche del 10% del capitale all'apertura, al massimo 3, distanziate di 5 sedute;
- uscita quando il VIX torna sotto 20, dopo 60 sedute dalla prima tranche, oppure stop a -15% dal prezzo medio.
Risultati sul capitale totale: sviluppo 1993-2009 24 episodi, 75% in utile, media +0,72%, peggiore -5,80% (2008);
verifica 2010-2026 23 episodi, 91% in utile, media +1,16%, peggiore -5,43% (2020).

Modulo senza I/O: il bot gli passa i dati e invia gli ordini.
"""
import datetime as dt
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

SYMBOL = "VOO"
ORDER_PREFIX = "px-"
VIX_ENTRY = 28.0
VIX_EXIT = 20.0
TRANCHE_PCT = 10.0
MAX_TRANCHES = 3
MIN_GAP_SESSIONS = 5
MAX_HOLD_SESSIONS = 60
STOP_PCT = 15.0
MIN_ORDER_USD = 10.0


def sessions_between(start: dt.date, end: dt.date, holidays: Iterable[str] = ()) -> int:
    """Sedute di borsa da `start` (esclusa) a `end` (inclusa)."""
    if start is None or end is None or end <= start:
        return 0
    return int(np.busday_count(start + dt.timedelta(days=1), end + dt.timedelta(days=1),
                               holidays=sorted(holidays)))


def episode(orders: List[Dict[str, Any]], holding: bool) -> Dict[str, Any]:
    """Episodio in corso ricostruito dagli ordini eseguiti del modulo (sopravvive ai riavvii).

    orders: {"side": "BUY"/"SELL", "date": date, "client_order_id": str}, eseguiti, in qualsiasi ordine.
    Le tranche contano dall'ultima vendita del modulo; senza posizione l'episodio è chiuso (resta la data
    dell'ultima tranche per la distanza minima).
    """
    own = sorted((o for o in orders if str(o.get("client_order_id") or "").startswith(ORDER_PREFIX)),
                 key=lambda o: o["date"])
    last_sell = max((o["date"] for o in own if o["side"] == "SELL"), default=None)
    buys = [o["date"] for o in own if o["side"] == "BUY" and (last_sell is None or o["date"] >= last_sell)]
    last_buy = max((o["date"] for o in own if o["side"] == "BUY"), default=None)
    if not holding:
        return {"tranches": 0, "first": None, "last": last_buy}
    return {"tranches": len(buys), "first": min(buys) if buys else None, "last": last_buy}


def entry_amount(vix_prev_close: Optional[float], ep: Dict[str, Any], today: dt.date, equity: float, cash: float,
                 tranche_pct: float = TRANCHE_PCT, holidays: Iterable[str] = ()) -> Dict[str, Any]:
    """{"amount": importo della tranche o 0, "reason": spiegazione}."""
    if vix_prev_close is None or not np.isfinite(vix_prev_close):
        return {"amount": 0.0, "reason": "VIX non disponibile"}
    if vix_prev_close < VIX_ENTRY:
        return {"amount": 0.0, "reason": f"VIX {vix_prev_close:.1f} sotto {VIX_ENTRY:.0f}: nessun panico"}
    if ep["tranches"] >= MAX_TRANCHES:
        return {"amount": 0.0, "reason": f"già {MAX_TRANCHES} tranche su {SYMBOL}"}
    if ep.get("last") and sessions_between(ep["last"], today, holidays) < MIN_GAP_SESSIONS:
        return {"amount": 0.0, "reason": f"ultima tranche il {ep['last']}: servono {MIN_GAP_SESSIONS} sedute di distanza"}
    amount = min(equity * tranche_pct / 100, max(0.0, cash))
    if amount < MIN_ORDER_USD:
        return {"amount": 0.0, "reason": "liquidità insufficiente"}
    return {"amount": round(amount, 2),
            "reason": f"VIX {vix_prev_close:.1f} ≥ {VIX_ENTRY:.0f}: tranche {ep['tranches'] + 1}/{MAX_TRANCHES} "
                      f"del {tranche_pct:.0f}% del capitale su {SYMBOL}"}


def exit_reason(vix_now: Optional[float], ep: Dict[str, Any], today: dt.date, price: float, avg_entry: float,
                holidays: Iterable[str] = ()) -> Optional[str]:
    """Motivo di uscita dall'intera posizione, oppure None."""
    if avg_entry > 0 and price > 0 and price < avg_entry * (1 - STOP_PCT / 100):
        return f"stop: {SYMBOL} {price:.2f} oltre il -{STOP_PCT:.0f}% dal prezzo medio {avg_entry:.2f}"
    if vix_now is not None and np.isfinite(vix_now) and vix_now < VIX_EXIT:
        return f"paura rientrata: VIX {vix_now:.1f} sotto {VIX_EXIT:.0f}"
    if ep.get("first") and sessions_between(ep["first"], today, holidays) >= MAX_HOLD_SESSIONS:
        return f"{MAX_HOLD_SESSIONS} sedute dalla prima tranche ({ep['first']})"
    return None
