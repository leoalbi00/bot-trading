"""AGENTE #6: Portfolio Guardian (sentinella h24 delle posizioni aperte).

Due funzioni:
1. pre_trade_check (Stage 3): un nuovo ingresso è ammesso solo se il portafoglio lo consente
   (ticker non già in portafoglio o con ordini pendenti, esposizione e numero di posizioni sotto i limiti).
2. evaluate_position (monitoraggio continuo): stop effettivo di ogni posizione e uscite.
   Cavalcare il trend (nessun tetto al profitto):
   - Trailing ATR Stop (Chandelier Exit): attivo quando il picco supera l'ingresso di trail_pct = mult x ATR%,
     lo stop segue il picco a distanza trail_pct; si vende solo al primo vero ritracciamento dalla vetta;
   - Scaling Out (Runner): al primo target (target_r x R) si vende scale_out_pct% della posizione e lo stop
     del resto va a breakeven: il runner corre a rischio zero con il trailing sempre attivo;
   - Breakeven: con un guadagno di picco >= 1.5R lo stop sale al prezzo d'ingresso (+ commissioni stimate).
   Uscita anticipata prima dello stop loss:
   - News/Macro Shock (Agente #4): sentiment delle notizie <= news_shock_sentiment, panico cross-asset
     (VIX estremo) o VIX salito di vix_spike_pct% dall'ingresso;
   - Inversione della microstruttura (Agente #2): OFI <= ofi_reversal con flusso HEAVY_SELL_FLOW;
   - Alpha Decay: score dell'Agente #5 (CIO) sotto 45/100;
   - Time-Stop (decadimento della spinta, Agente #1): dopo time_stop_min minuti la posizione è ancora piatta
     (|PnL| < 0.5R) e l'Agente #1 non vede più momentum (score < STRONG_BUY): uscita in pari o minimo loss.
R = distanza dello stop iniziale. Le uscite anticipate e lo scaling out rispettano, per le azioni,
l'apertura del mercato (a mercato chiuso i dati sono fermi); Alpha Decay e Time-Stop anche un tempo minimo in posizione.
"""
from typing import Any, Dict, Optional


class PortfolioGuardianAgent:
    def __init__(
        self,
        breakeven_r: float = 1.5,
        alpha_decay_score: float = 45.0,
        time_stop_min: float = 60.0,
        time_stop_flat_r: float = 0.5,
        momentum_score: float = 75.0,
        target_r: float = 2.0,
        scale_out_pct: float = 50.0,
        news_shock_sentiment: float = -0.4,
        vix_spike_pct: float = 20.0,
        vix_spike_min: float = 20.0,
        ofi_reversal: float = -0.5,
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
        self.time_stop_min = time_stop_min
        self.time_stop_flat_r = time_stop_flat_r
        self.momentum_score = momentum_score
        self.target_r = target_r
        self.scale_out_pct = scale_out_pct
        self.news_shock_sentiment = news_shock_sentiment
        self.vix_spike_pct = vix_spike_pct
        self.vix_spike_min = vix_spike_min
        self.ofi_reversal = ofi_reversal
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
        scaled_out: bool = False,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Stop effettivo e uscite della posizione. Percentuali rispetto al prezzo d'ingresso.

        scaled_out: la prima quota è già stata incassata (runner a breakeven, trailing sempre attivo).
        signals: letture fresche degli agenti per le uscite anticipate
                 {"quant_score", "news_sentiment", "headlines", "stress_level", "vix", "vix_at_entry",
                  "ofi", "micro_signal"} (valori assenti = segnale non disponibile).
        """
        if entry <= 0 or price <= 0:
            return {"agent_id": self.agent_id, "action": "HOLD", "hit": False, "effective_stop_pct": stop_pct,
                    "reason": "prezzi non disponibili", "active": False, "breakeven": False, "sell_pct": 100}
        sig = signals or {}
        pnl = (price / entry - 1) * 100
        peak = max(peak or 0.0, price, entry)
        peak_gain = (peak / entry - 1) * 100
        r = abs(stop_pct) or 1.0
        target = self.target_r * r

        effective, source = stop_pct, "stop iniziale"
        breakeven = scaled_out or peak_gain >= self.breakeven_r * r
        if breakeven:
            be = self.fee_buffer_crypto_pct if is_crypto else 0.0
            if be > effective:
                effective, source = be, ("breakeven del runner (scaling out eseguito)" if scaled_out else
                                         f"breakeven (picco +{peak_gain:.2f}% ≥ {self.breakeven_r}R = {self.breakeven_r * r:.2f}%)")

        # Chandelier Exit: dopo lo scaling out il trailing segue sempre il picco (senza ATR: distanza R)
        trail_pct = (self.atr_mult_crypto if is_crypto else self.atr_mult_stock) * atr_pct if atr_pct else (r if scaled_out else None)
        trailing_active, trigger = False, None
        if trail_pct:
            trailing_active = scaled_out or peak_gain >= trail_pct
            trigger = peak * (1 - trail_pct / 100)
            trail_stop = (trigger / entry - 1) * 100
            if trailing_active and trail_stop > effective:
                effective, source = trail_stop, f"trailing ATR {trail_pct:.1f}% dal picco ${peak:,.4f}"

        out = {"agent_id": self.agent_id, "pnl_pct": round(pnl, 2), "peak_gain_pct": round(peak_gain, 2),
               "r_pct": round(r, 2), "target_pct": round(target, 2), "effective_stop_pct": round(effective, 2),
               "stop_source": source, "breakeven": breakeven, "active": trailing_active, "trigger": trigger,
               "scaled_out": scaled_out, "action": "HOLD", "hit": False, "sell_pct": 100,
               "reason": f"stop effettivo {effective:+.2f}% ({source})"}

        def exit_(action, reason, sell_pct=100):
            out.update(action=action, hit=True, reason=reason, sell_pct=sell_pct)
            return out

        # Uscite su stop rialzato (breakeven / trailing): sempre attive, anche a mercato chiuso
        if effective > stop_pct and pnl <= effective:
            action = "TRAILING_STOP" if source.startswith("trailing") else "BREAKEVEN_STOP"
            return exit_(action, f"PnL {pnl:+.2f}% ≤ stop effettivo {effective:+.2f}% ({source})")

        if not (market_open or is_crypto):
            return out
        # Runner: al primo target si incassa una quota, il resto corre con stop a breakeven e trailing
        if not scaled_out and pnl >= target:
            return exit_("SCALE_OUT", f"PnL {pnl:+.2f}% ≥ primo target {target:.2f}% ({self.target_r:.0f}R): incasso "
                                      f"{self.scale_out_pct:.0f}%, runner a breakeven con trailing ATR", self.scale_out_pct)

        # Uscite anticipate prima dello stop loss: la tesi d'investimento è caduta
        news = sig.get("news_sentiment")
        if news is not None and (sig.get("headlines") or 0) > 0 and news <= self.news_shock_sentiment:
            return exit_("NEWS_SHOCK", f"Agente #4: notizie negative (sentiment {news:+.2f} ≤ {self.news_shock_sentiment:+.2f}), "
                                       f"liquidazione immediata a PnL {pnl:+.2f}%")
        if sig.get("stress_level") == "EXTREME_PANIC":
            return exit_("NEWS_SHOCK", f"Agente #4: panico cross-asset (VIX {sig.get('vix')}), liquidazione immediata "
                                       f"a PnL {pnl:+.2f}%")
        vix, vix0 = sig.get("vix"), sig.get("vix_at_entry")
        if vix and vix0 and vix >= self.vix_spike_min and vix >= vix0 * (1 + self.vix_spike_pct / 100):
            return exit_("NEWS_SHOCK", f"Agente #4: picco del VIX {vix0:.1f} → {vix:.1f} (+{(vix / vix0 - 1) * 100:.0f}%), "
                                       f"liquidazione immediata a PnL {pnl:+.2f}%")
        ofi = sig.get("ofi")
        if ofi is not None and ofi <= self.ofi_reversal and sig.get("micro_signal") == "HEAVY_SELL_FLOW":
            return exit_("OFI_REVERSAL", f"Agente #2: OFI {ofi:+.2f} ≤ {self.ofi_reversal:+.2f} con flusso HEAVY_SELL_FLOW "
                                         f"(venditori istituzionali): Early Cut a PnL {pnl:+.2f}%")

        if held_min is not None and held_min < self.min_hold_min:
            return out
        if cio_score is not None and cio_score < self.alpha_decay_score:
            return exit_("ALPHA_DECAY", f"score CIO {cio_score:.1f} < {self.alpha_decay_score:.0f}: l'alpha si è esaurito")
        quant = sig.get("quant_score")
        if (not scaled_out and held_min is not None and held_min >= self.time_stop_min
                and abs(pnl) < self.time_stop_flat_r * r and (quant is None or quant < self.momentum_score)):
            return exit_("TIME_STOP", f"{held_min:.0f} min in posizione con PnL {pnl:+.2f}% (< {self.time_stop_flat_r}R) e "
                                      f"Agente #1 senza momentum (score {quant if quant is not None else 'N/D'}): "
                                      "spinta esaurita, capitale liberato")
        return out
