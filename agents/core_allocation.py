"""Core + satellite: una quota fissa del capitale su SPY con il filtro di regime, il resto al bot.

Backtest (11/2026, backtest/core_satellite.py): core 80% / bot 20% contro il solo bot
- sviluppo 01/2024-06/2025: 15.7% vs 4.3% annuo, Sharpe 1.28 vs 0.38, MaxDD -10.0% vs -12.1%;
- verifica 07/2025-10/2026: 14.7% vs 11.7% annuo, Sharpe 1.14 vs 0.74, MaxDD -5.0% vs -13.9%.
In entrambi i periodi il solo core SPY ha reso più di ogni combinazione: il bot non ha ancora un vantaggio dimostrato.

Il bot non vede la posizione del core: niente stop del Guardian, niente conteggio nel rischio, niente vendite.
Modulo senza I/O: il bot gli passa i dati e invia gli ordini.
"""
from typing import Any, Dict, List, Optional, Tuple

CORE_SYMBOL = "SPY"
CORE_ORDER_PREFIX = "core-"      # client_order_id degli ordini del core: esclusi dal registro operazioni del bot
CORE_EXPOSURE_UP = 95.0          # % della quota core investita con SPY in trend (come MAX_GROSS_PCT)
CORE_EXPOSURE_DOWN = 33.25       # % con SPY sotto trend confermato (95 x 0.35, come il regime del Portfolio Allocator)
REBALANCE_BAND_PCT = 3.0         # si ribilancia solo se lo scarto supera il 3% del capitale totale
MIN_ORDER_USD = 10.0


def is_core(symbol: str) -> bool:
    return str(symbol or "").upper().replace("/", "") == CORE_SYMBOL


def split_positions(positions: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """(posizione del core o None, posizioni del bot)."""
    core = next((p for p in positions if is_core(p.get("symbol"))), None)
    return core, [p for p in positions if not is_core(p.get("symbol"))]


def target_value(equity: float, core_pct: float, trend_up: bool) -> float:
    """Controvalore obiettivo di SPY: quota core x esposizione del regime."""
    if equity <= 0 or core_pct <= 0:
        return 0.0
    return equity * core_pct / 100 * (CORE_EXPOSURE_UP if trend_up else CORE_EXPOSURE_DOWN) / 100


def rebalance(equity: float, core_value: float, core_pct: float, trend_up: bool) -> Optional[Dict[str, Any]]:
    """Ordine di ribilanciamento {"side", "amount", "target", "reason"} oppure None se lo scarto è nella banda."""
    target = target_value(equity, core_pct, trend_up)
    gap = target - core_value
    if equity <= 0 or abs(gap) < max(equity * REBALANCE_BAND_PCT / 100, MIN_ORDER_USD):
        return None
    regime = "SPY in trend" if trend_up else "SPY sotto trend (3 chiusure sotto la EMA100)"
    return {"side": "BUY" if gap > 0 else "SELL", "amount": round(abs(gap), 2), "target": round(target, 2),
            "reason": f"core {core_pct:.0f}% del capitale, {regime}: obiettivo ${target:,.0f}, attuale ${core_value:,.0f}"}


def satellite_account(account: Dict[str, Any], core_pct: float, core_value: float) -> Dict[str, Any]:
    """Conto visto dal bot: capitale = quota satellite, buying power senza la liquidità riservata al core.

    Il core riserva sempre la sua quota piena (anche quando con SPY sotto trend è investito solo in parte):
    la liquidità non usata dal core non passa al bot, come nel backtest con due conti separati.
    """
    if core_pct <= 0:
        return account
    out = dict(account)
    equity = float(account.get("portfolio", account.get("equity", 0)) or 0)
    reserved_cash = max(0.0, equity * core_pct / 100 - core_value)
    out["portfolio"] = max(0.0, equity * (100 - core_pct) / 100)
    for key in ("buying_power", "non_marginable_buying_power", "cash"):
        if key in out:
            out[key] = max(0.0, float(out.get(key) or 0) - reserved_cash)
    if "last_equity" in out:
        out["last_equity"] = float(out.get("last_equity") or 0) * (100 - core_pct) / 100
    return out
