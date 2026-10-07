"""AGENTE #6: Portfolio Guardian (sentinella h24 delle posizioni aperte).

Due funzioni:
1. pre_trade_check (Stage 3): un nuovo ingresso è ammesso solo se il portafoglio lo consente
   (ticker non già in portafoglio o con ordini pendenti, esposizione e numero di posizioni sotto i limiti).
2. evaluate_position (monitoraggio continuo): calcola lo stop effettivo di ogni posizione e le uscite:
   - Trailing ATR Stop dinamico: attivo quando il picco supera l'ingresso di trail_pct = mult x ATR%;
   - Breakeven: con un guadagno di picco >= 1.5R (R = distanza dello stop iniziale) lo stop sale al
     prezzo d'ingresso (+ commissioni stimate);
   - Alpha Decay: chiusura se lo score dell'Agente #5 (CIO) scende sotto 45/100;
   - Time-Stop: chiusura dopo N candele 1h se la posizione resta piatta (|PnL| < 0.5R).
Le uscite discrezionali (Alpha Decay, Time-Stop) rispettano un tempo minimo in posizione e,
per le azioni, l'apertura del mercato (a mercato chiuso i dati sono fermi).
"""
from typing import Any, Dict, Optional


class PortfolioGuardianAgent:
    def __init__(
        self,
        breakeven_r: float = 1.5,
        alpha_decay_score: float = 45.0,
        time_stop_bars: int = 48,
        time_stop_flat_r: float = 0.5,
        min_hold_min: float = 60.0,
        max_positions: int = 8,
        max_exposure_pct: float = 100.0,
        fee_buffer_crypto_pct: float = 0.30,
        atr_mult_stock: float = 1.5,
        atr_mult_crypto: float = 2.0,
    ):
        self.agent_id = "AGENT_06_PORTFOLIO_GUARDIAN"
        self.breakeven_r = breakeven_r
        self.alpha_decay_score = alpha_decay_score
        self.time_stop_bars = time_stop_bars
        self.time_stop_flat_r = time_stop_flat_r
        self.min_hold_min = min_hold_min
        self.max_positions = max_positions
        self.max_exposure_pct = max_exposure_pct
        self.fee_buffer_crypto_pct = fee_buffer_crypto_pct
        self.atr_mult_stock = atr_mult_stock
        self.atr_mult_crypto = atr_mult_crypto

    # ------------------------------------------------------------------ Stage 3: ingresso
    def pre_trade_check(self, symbol_key: str, portfolio: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """portfolio: {"held": set di chiavi, "pending": set, "exposure_pct": float, "positions": int, "max_exposure_pct": float}"""
        portfolio = portfolio or {}
        held, pending = set(portfolio.get("held") or ()), set(portfolio.get("pending") or ())
        exposure = float(portfolio.get("exposure_pct") or 0.0)
        limit = float(portfolio.get("max_exposure_pct") or self.max_exposure_pct)
        n_pos = int(portfolio.get("positions") or len(held))
        problems = []
        if symbol_key in held:
            problems.append("già in portafoglio")
        if symbol_key in pending:
            problems.append("ordine già pendente")
        if exposure >= limit * 0.98:
            problems.append(f"esposizione {exposure:.0f}% al limite {limit:.0f}%")
        if n_pos >= self.max_positions:
            problems.append(f"{n_pos} posizioni aperte (massimo {self.max_positions})")
        return {
            "agent_id": self.agent_id,
            "guardian_approved": not problems,
            "reason": "; ".join(problems) or f"OK (esposizione {exposure:.0f}%/{limit:.0f}%, {n_pos}/{self.max_positions} posizioni)",
        }

    # ------------------------------------------------------------------ monitoraggio h24
    def evaluate_position(
        self,
        entry: float,
        price: float,
        peak: float,
        stop_pct: float,
        atr_pct: Optional[float],
        is_crypto: bool,
        held_min: Optional[float],
        cio_score: Optional[float] = None,
        market_open: bool = True,
    ) -> Dict[str, Any]:
        """Stop effettivo e uscite della posizione. Percentuali rispetto al prezzo d'ingresso."""
        if entry <= 0 or price <= 0:
            return {"agent_id": self.agent_id, "action": "HOLD", "hit": False, "effective_stop_pct": stop_pct,
                    "reason": "prezzi non disponibili", "active": False, "breakeven": False}
        pnl = (price / entry - 1) * 100
        peak = max(peak or 0.0, price, entry)
        peak_gain = (peak / entry - 1) * 100
        r = abs(stop_pct) or 1.0

        effective, source = stop_pct, "stop iniziale"
        breakeven = peak_gain >= self.breakeven_r * r
        if breakeven:
            be = self.fee_buffer_crypto_pct if is_crypto else 0.0
            if be > effective:
                effective, source = be, f"breakeven (picco +{peak_gain:.2f}% ≥ {self.breakeven_r}R = {self.breakeven_r * r:.2f}%)"

        trail_pct, trailing_active, trigger = None, False, None
        if atr_pct:
            trail_pct = (self.atr_mult_crypto if is_crypto else self.atr_mult_stock) * atr_pct
            trailing_active = peak_gain >= trail_pct
            trigger = peak * (1 - trail_pct / 100)
            trail_stop = (trigger / entry - 1) * 100
            if trailing_active and trail_stop > effective:
                effective, source = trail_stop, f"trailing ATR {trail_pct:.1f}% dal picco ${peak:,.4f}"

        out = {"agent_id": self.agent_id, "pnl_pct": round(pnl, 2), "peak_gain_pct": round(peak_gain, 2),
               "r_pct": round(r, 2), "effective_stop_pct": round(effective, 2), "stop_source": source,
               "breakeven": breakeven, "active": trailing_active, "trigger": trigger,
               "action": "HOLD", "hit": False, "reason": f"stop effettivo {effective:+.2f}% ({source})"}

        # Uscite su stop rialzato (breakeven / trailing): sempre attive, anche a mercato chiuso
        if effective > stop_pct and pnl <= effective:
            action = "TRAILING_STOP" if source.startswith("trailing") else "BREAKEVEN_STOP"
            out.update(action=action, hit=True,
                       reason=f"PnL {pnl:+.2f}% ≤ stop effettivo {effective:+.2f}% ({source})")
            return out

        discretionary_ok = (held_min is None or held_min >= self.min_hold_min) and (market_open or is_crypto)
        if not discretionary_ok:
            return out
        if cio_score is not None and cio_score < self.alpha_decay_score:
            out.update(action="ALPHA_DECAY", hit=True,
                       reason=f"score CIO {cio_score:.1f} < {self.alpha_decay_score:.0f}: l'alpha si è esaurito")
            return out
        bars = (held_min / 60.0) if held_min is not None else None
        if bars is not None and bars >= self.time_stop_bars and abs(pnl) < self.time_stop_flat_r * r:
            out.update(action="TIME_STOP", hit=True,
                       reason=f"{bars:.0f} candele 1h in posizione con PnL {pnl:+.2f}% (< {self.time_stop_flat_r}R): capitale liberato")
        return out
