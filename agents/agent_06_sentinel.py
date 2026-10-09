"""AGENTE #6: Portfolio Guardian (sentinella h24 delle posizioni aperte, loop indipendente ogni 20 secondi).

Due funzioni:
1. pre_trade_check (Stage 3): un nuovo ingresso è ammesso solo se il ticker non è già in portafoglio
   o con ordini pendenti (esposizione 50% e 4 posizioni sono la Safety Net dell'Agente #3).
2. evaluate_position (monitoraggio continuo). NESSUN TIME-STOP: una posizione piatta, in consolidamento
   o in accumulo resta aperta finché la tesi è valida. Il tempo trascorso non chiude mai una posizione.
   - Hard Stop Loss (1.5%-2.5%, Agente #3): sempre attivo;
   - Target 1 (Scaling Out): a target_r x R (2R) si vende scale_out_pct% (50%) e lo stop del resto va a
     breakeven + commissioni;
   - Runner senza tetto ai profitti: il restante 50% è gestito SOLO dal Trailing Stop ATR (Chandelier Exit)
     che segue il picco a distanza mult x ATR%;
   - Uscite anticipate prima dello stop, e solo queste:
     1. Thesis Decay: l'Agente #4 rileva una smentita o il decadimento del catalizzatore (notizie fresche);
     2. Orderbook Reversal: l'Agente #2 registra OFI <= -0.5;
     3. News Shock / Panico Macro: VIX >= 28 o VIX salito di oltre il 20% dall'ingresso.
R = distanza dello stop iniziale. Scaling out e uscite anticipate rispettano, per le azioni, l'apertura del
mercato (a mercato chiuso i dati sono fermi); gli stop (hard, breakeven, trailing) sono sempre attivi.
"""
from typing import Any, Dict, Optional, Tuple

EXIT_LABELS = {
    "STOP_LOSS": "Hard Stop Loss", "TRAILING_STOP": "Trailing ATR Stop", "BREAKEVEN_STOP": "Stop a Breakeven",
    "THESIS_DECAY": "Thesis Decay (Agente #4)", "OFI_REVERSAL": "Orderbook Reversal (Agente #2)",
    "NEWS_SHOCK": "News Shock / Panico Macro", "ROTATION": "Rotazione verso SUPER_CONVICTION (tesi degradata)",
    "MANUAL": "Vendita manuale", "PANIC": "PANIC - chiudi tutto",
}


def _usd(value: Optional[float]) -> str:
    return f"${value:,.4f}".rstrip("0").rstrip(".") if value else "$N/D"


class PortfolioGuardianAgent:
    def __init__(
        self,
        target_r: float = 2.0,
        scale_out_pct: float = 50.0,
        vix_panic: float = 28.0,
        vix_spike_pct: float = 20.0,
        ofi_reversal: float = -0.5,
        fee_buffer_crypto_pct: float = 0.30,
        fee_buffer_stock_pct: float = 0.05,
        atr_mult_stock: float = 1.5,
        atr_mult_crypto: float = 2.0,
    ):
        self.agent_id = "AGENT_06_PORTFOLIO_GUARDIAN"
        self.target_r = target_r
        self.scale_out_pct = scale_out_pct
        self.vix_panic = vix_panic
        self.vix_spike_pct = vix_spike_pct
        self.ofi_reversal = ofi_reversal
        self.fee_buffer_crypto_pct = fee_buffer_crypto_pct
        self.fee_buffer_stock_pct = fee_buffer_stock_pct
        self.atr_mult_stock = atr_mult_stock
        self.atr_mult_crypto = atr_mult_crypto

    # ------------------------------------------------------------------ Stage 3: ingresso
    def pre_trade_check(self, symbol_key: str, portfolio: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """portfolio: {"held": set di chiavi, "pending": set}"""
        portfolio = portfolio or {}
        held, pending = set(portfolio.get("held") or ()), set(portfolio.get("pending") or ())
        problems = []
        if symbol_key in held:
            problems.append("già in portafoglio")
        if symbol_key in pending:
            problems.append("ordine già pendente")
        return {
            "agent_id": self.agent_id,
            "guardian_approved": not problems,
            "reason": "; ".join(problems) or "OK (nessuna posizione né ordine pendente sul ticker)",
        }

    # ------------------------------------------------------------------ monitoraggio h24
    def breakeven_pct(self, is_crypto: bool) -> float:
        """Breakeven + commissioni stimate (spread/fee crypto, fee regolamentari azioni)."""
        return self.fee_buffer_crypto_pct if is_crypto else self.fee_buffer_stock_pct

    def evaluate_position(
        self,
        entry: float,
        price: float,
        peak: float,
        stop_pct: float,
        atr_pct: Optional[float],
        is_crypto: bool,
        market_open: bool = True,
        scaled_out: bool = False,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Stop effettivo e uscite della posizione. Percentuali rispetto al prezzo d'ingresso.

        scaled_out: il Target 1 è già stato incassato (runner a breakeven, trailing ATR attivo).
        signals: letture fresche degli agenti per le uscite anticipate
                 {"thesis_decay": str|None, "ofi": float, "vix": float, "vix_at_entry": float}
                 (valori assenti = segnale non disponibile).
        """
        if entry <= 0 or price <= 0:
            return {"agent_id": self.agent_id, "action": "HOLD", "hit": False, "effective_stop_pct": stop_pct,
                    "stop_pct": stop_pct, "reason": "prezzi non disponibili", "active": False, "breakeven": False,
                    "sell_pct": 100, "pnl_pct": None, "stop_source": "stop iniziale", "trigger": None,
                    "scaled_out": scaled_out}
        sig = signals or {}
        pnl = (price / entry - 1) * 100
        peak = max(peak or 0.0, price, entry)
        peak_gain = (peak / entry - 1) * 100
        r = abs(stop_pct) or 1.0
        target = self.target_r * r

        effective, source = stop_pct, "hard stop"
        trailing_active, trigger, trail_pct = False, entry * (1 + stop_pct / 100), None
        if scaled_out:
            be = self.breakeven_pct(is_crypto)
            if be > effective:
                effective, source = be, "breakeven + commissioni del runner (Target 1 incassato)"
                trigger = entry * (1 + be / 100)
            # Chandelier Exit sul runner: segue il picco senza alcun tetto superiore (senza ATR: distanza R)
            trail_pct = (self.atr_mult_crypto if is_crypto else self.atr_mult_stock) * atr_pct if atr_pct else r
            trailing_active = True
            trail_trigger = peak * (1 - trail_pct / 100)
            trail_stop = (trail_trigger / entry - 1) * 100
            if trail_stop > effective:
                effective, source, trigger = trail_stop, f"trailing ATR {trail_pct:.2f}% dal picco {_usd(peak)}", trail_trigger

        out = {"agent_id": self.agent_id, "pnl_pct": round(pnl, 2), "peak_gain_pct": round(peak_gain, 2),
               "r_pct": round(r, 2), "target_pct": round(target, 2), "effective_stop_pct": round(effective, 2),
               "stop_pct": stop_pct, "stop_source": source, "breakeven": scaled_out, "active": trailing_active,
               "trail_pct": round(trail_pct, 2) if trail_pct else None, "trigger": trigger, "peak": peak,
               "scaled_out": scaled_out, "action": "HOLD", "hit": False, "sell_pct": 100,
               "reason": f"stop effettivo {effective:+.2f}% ({source})"}

        def exit_(action, reason, sell_pct=100):
            out.update(action=action, hit=True, reason=reason, sell_pct=sell_pct)
            return out

        # Stop: sempre attivi, anche a mercato chiuso
        if pnl <= effective:
            if effective <= stop_pct:
                return exit_("STOP_LOSS", f"PnL {pnl:+.2f}% ≤ hard stop {stop_pct:+.2f}%")
            action = "TRAILING_STOP" if source.startswith("trailing") else "BREAKEVEN_STOP"
            return exit_(action, f"PnL {pnl:+.2f}% ≤ stop effettivo {effective:+.2f}% ({source})")

        if not (market_open or is_crypto):
            return out
        # Target 1: si incassa metà posizione, il resto corre a breakeven con il trailing ATR
        if not scaled_out and pnl >= target:
            return exit_("SCALE_OUT", f"PnL {pnl:+.2f}% ≥ Target 1 {target:.2f}% ({self.target_r:.0f}R): incasso "
                                      f"{self.scale_out_pct:.0f}%, runner a breakeven con Trailing ATR Stop", self.scale_out_pct)

        # Uscite anticipate: solo se la tesi è concretamente caduta
        if sig.get("thesis_decay"):
            return exit_("THESIS_DECAY", f"Agente #4: {sig['thesis_decay']}, uscita anticipata a PnL {pnl:+.2f}%")
        ofi = sig.get("ofi")
        if ofi is not None and ofi <= self.ofi_reversal:
            return exit_("OFI_REVERSAL", f"Agente #2: inversione violenta del book (OFI {ofi:+.2f} ≤ {self.ofi_reversal:+.2f}), "
                                         f"uscita anticipata a PnL {pnl:+.2f}%")
        vix, vix0 = sig.get("vix"), sig.get("vix_at_entry")
        if vix is not None and vix >= self.vix_panic:
            return exit_("NEWS_SHOCK", f"Panico macro: VIX {vix:.1f} ≥ {self.vix_panic:.0f}, liquidazione a PnL {pnl:+.2f}%")
        if vix and vix0 and vix > vix0 * (1 + self.vix_spike_pct / 100):
            return exit_("NEWS_SHOCK", f"News Shock: VIX {vix0:.1f} → {vix:.1f} (+{(vix / vix0 - 1) * 100:.0f}% dall'ingresso), "
                                       f"liquidazione a PnL {pnl:+.2f}%")
        return out

    # ------------------------------------------------------------------ spiegabilità
    @staticmethod
    def trajectory_status(path: Optional[Dict[str, Any]], entry: float, price: float,
                          elapsed_min: Optional[float]) -> Tuple[str, Optional[float]]:
        """Posizione del prezzo rispetto alla Curva di Traiettoria Attesa dell'Agente #1 (solo informativa).

        Restituisce (giudizio, prezzo atteso ora). Non genera mai un'uscita: niente time-stop.
        """
        if not path or not entry or elapsed_min is None:
            return "traiettoria N/D", None
        bars = max(elapsed_min / float(path.get("bar_minutes") or 60), 0.0)
        drift = float(path.get("drift_pct_per_bar") or 0) / 100
        sigma = float(path.get("vol_pct_per_bar") or 0) / 100
        expected = entry * (1 + drift) ** bars
        band = sigma * max(bars, 1.0) ** 0.5
        if price > expected * (1 + band):
            return "sopra la traiettoria attesa", expected
        if price < expected * (1 - band):
            return "sotto la traiettoria attesa (entro lo stop)", expected
        return "traiettoria solida", expected

    def hold_rationale(self, g: Dict[str, Any], signals: Optional[Dict[str, Any]] = None,
                       trajectory: str = "traiettoria N/D", thesis: Optional[str] = None) -> str:
        """Scheda dinamica (ogni 20 s): perché la posizione resta aperta, in una riga."""
        sig = signals or {}
        pnl = g.get("pnl_pct")
        if pnl is None:
            return "Prezzi non disponibili: posizione mantenuta con hard stop attivo"
        state = "In guadagno" if pnl > 0.05 else "In perdita" if pnl < -0.05 else "In pari"
        ofi = sig.get("ofi")
        ofi_txt = ("OFI N/D" if ofi is None else f"OFI positivo ({ofi:+.2f})" if ofi > 0.05
                   else f"OFI negativo ({ofi:+.2f}, soglia {self.ofi_reversal:+.1f})" if ofi < -0.05 else f"OFI neutro ({ofi:+.2f})")
        parts = [f"{state} {pnl:+.2f}%", trajectory, ofi_txt]
        if thesis:
            parts.append(f"tesi intatta ('{thesis}')")
        if g.get("scaled_out"):
            parts.append(f"runner: stop {g['effective_stop_pct']:+.2f}% ({g.get('stop_source')})")
        else:
            parts.append(f"Target 1 a {g.get('target_pct', 0):+.2f}%, hard stop {g.get('stop_pct', 0):+.2f}%")
        return ", ".join(parts)

    @staticmethod
    def exit_reason(action: str, price: Optional[float], sell_pct: float = 100, scale_out: Optional[Dict[str, Any]] = None,
                    stop_price: Optional[float] = None, detail: str = "") -> str:
        """Scheda di uscita: es. "Chiuso 50% su Target 2R, restante 50% su Trailing ATR Stop a $XXX"."""
        label = EXIT_LABELS.get(action, action.replace("_", " ").title())
        level = stop_price if action in ("TRAILING_STOP", "BREAKEVEN_STOP", "STOP_LOSS") and stop_price else price
        if action == "SCALE_OUT":
            return (f"Chiuso {sell_pct:.0f}% su Target 2R a {_usd(price)}, restante {100 - sell_pct:.0f}% in corsa "
                    "con Trailing ATR Stop (stop a breakeven + commissioni)")
        if scale_out:
            pct = float(scale_out.get("pct") or 50)
            return (f"Chiuso {pct:.0f}% su Target 2R a {_usd(scale_out.get('price'))}, restante {100 - pct:.0f}% su "
                    f"{label} a {_usd(level)}" + (f" ({detail})" if detail and action not in ("TRAILING_STOP",) else ""))
        return f"Chiuso {sell_pct:.0f}% su {label} a {_usd(level)}" + (f": {detail}" if detail else "")
