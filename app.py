import os
import time
import hmac
import threading
import datetime
import itertools
from collections import deque
from functools import wraps
import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import trading_core as core
from trading_core import alpaca_client

KEEP_ALIVE_INTERVAL = 600  # secondi tra un self-ping e l'altro

# Protezione login: dopo MAX_LOGIN_ATTEMPTS errori l'IP viene bloccato per LOGIN_LOCKOUT secondi
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT = 300
DATA_CACHE_TTL = 2  # secondi: la dashboard interroga ogni secondo, Alpaca al massimo ogni 2 secondi

# Lock per impedire scansioni multiple simultanee
scan_lock = threading.Lock()
# Lock per lo stato condiviso tra thread (log e analisi IA)
state_lock = threading.Lock()
# Evento per risvegliare il loop quando il bot viene riattivato
wake_event = threading.Event()

_log_ids = itertools.count(1)

bot_state = {
    "active": True,
    "last_scan": "In attesa del primo scan...",
    "status": "Inizializzato",
    "logs": deque(maxlen=300),  # ordine cronologico: il più recente è in fondo
    "cio": {},           # mandato esecutivo del CIO
    "performance": {},   # Post-Trade Auditor: win rate, PnL, permanenza media
    "ledger_open": {},   # per posizione: data di apertura, stop, allocazione e convinzione (da Alpaca)
    "latest_ai_analysis": {
        "symbol": "INIZIALIZZO...",
        "rsi": "--",
        "sentiment": "Premi SCAN ORA per avviare",
        "ai_verdict": "IN ATTESA",
        "reasoning": "Il bot sta attendendo il primo ciclo di scansione dei mercati."
    }
}

def log_message(msg):
    now = core.now_local()
    entry = f"[{now.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    with state_lock:
        bot_state["logs"].append({"id": next(_log_ids), "ts": now.timestamp(), "text": entry})

def set_ai_analysis(**analysis):
    with state_lock:
        bot_state["latest_ai_analysis"] = analysis

def short_text(text, limit=80):
    return text[:limit] + "..." if len(text) > limit else text

_cache = {}
_cache_lock = threading.Lock()

def cached(key, fn):
    """Cache breve per i dati Alpaca richiesti dalla dashboard ogni 3 secondi."""
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < DATA_CACHE_TTL:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value

def get_account_summary():
    if not alpaca_client:
        return {"cash": 0, "portfolio": 0, "buying_power": 0, "non_marginable_buying_power": 0}
    try:
        acc = alpaca_client.get_account()
        return {
            "cash": float(acc.cash),
            "portfolio": float(acc.portfolio_value),
            "buying_power": float(acc.buying_power),
            "non_marginable_buying_power": float(acc.non_marginable_buying_power or 0),
            "last_equity": float(acc.last_equity or 0)
        }
    except Exception as e:
        log_message(f"Errore lettura account: {e}")
        return {"cash": 0, "portfolio": 0, "buying_power": 0, "non_marginable_buying_power": 0}

def get_open_positions():
    if not alpaca_client:
        return []
    try:
        positions = alpaca_client.get_all_positions()
        res = []
        for p in positions:
            crypto = "crypto" in str(getattr(p, "asset_class", "")).lower()
            res.append({
                "symbol": p.symbol,
                "yf_symbol": core.to_yf_symbol(p.symbol, crypto=crypto),
                "is_crypto": crypto,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,
                "avg_entry_price": float(p.avg_entry_price or 0),
                "side": str(getattr(getattr(p, "side", None), "value", getattr(p, "side", "long"))).upper()
            })
        return res
    except Exception as e:
        log_message(f"Errore recupero posizioni: {e}")
        return []

def has_valid_token():
    provided = request.headers.get("X-API-Key", "")
    return hmac.compare_digest(provided.encode(), core.get_api_token().encode())

def is_logged_in():
    return session.get("auth") is True

def require_token(fn):
    """Protegge gli endpoint di controllo con header X-API-Key = BOT_API_TOKEN (env o config.json).

    Il token è visibile solo nella dashboard dopo il login, quindi fa anche da protezione CSRF.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not has_valid_token():
            return jsonify({"status": "error", "message": "Non autorizzato: chiave API mancante o errata"}), 401
        return fn(*args, **kwargs)
    return wrapper

def require_login(fn):
    """Accesso in lettura: sessione della dashboard oppure header X-API-Key valido."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not (is_logged_in() or has_valid_token()):
            return jsonify({"status": "error", "message": "Sessione scaduta: effettua di nuovo il login"}), 401
        return fn(*args, **kwargs)
    return wrapper

_failed_logins = {}
_failed_lock = threading.Lock()

def login_blocked_for(ip):
    """Secondi di blocco rimanenti per questo IP (0 se può riprovare)."""
    with _failed_lock:
        count, first = _failed_logins.get(ip, (0, 0.0))
        if count >= MAX_LOGIN_ATTEMPTS:
            remaining = LOGIN_LOCKOUT - (time.time() - first)
            if remaining > 0:
                return int(remaining) + 1
            _failed_logins.pop(ip, None)
        return 0

def register_failed_login(ip):
    with _failed_lock:
        count, first = _failed_logins.get(ip, (0, time.time()))
        if time.time() - first > LOGIN_LOCKOUT:
            count, first = 0, time.time()
        _failed_logins[ip] = (count + 1, first)

def should_abort():
    if not bot_state["active"]:
        log_message("⏸️ Bot messo in pausa: interrompo il ciclo corrente.")
        return True
    return False

def journal_operation(status, pos=None):
    """Tipo di operazione per il registro: STOP LOSS / TAKE PROFIT dai trigger difensivi, altrimenti SELL."""
    if status == "STOP_LOSS":
        return "STOP LOSS"
    if status == "TAKE_PROFIT":
        return "TAKE PROFIT"
    if status == "BREAKEVEN_STOP":
        return "STOP LOSS"
    if status == "TRAILING_STOP":
        return "TAKE PROFIT" if pos and pos["unrealized_pl"] > 0 else "STOP LOSS"
    return "SELL"

def record_sell(pos, operation, order, pct=100, reason="", source="auto"):
    """Registra una vendita inviata: quantità, prezzo corrente e PnL realizzato stimato sul prezzo medio."""
    qty = pos["qty"] * min(pct, 100) / 100
    pnl = (pos["current_price"] - pos["avg_entry_price"]) * qty if pos.get("avg_entry_price") else None
    core.record_execution(pos["yf_symbol"], operation, "SELL", price=pos["current_price"], quantity=qty, realized_pnl=pnl,
                          rationale={"exit_reason": reason, "agents_at_exit": core.quant_rationale(pos["yf_symbol"])},
                          order_id=getattr(order, "id", None), source=source, note=reason, log=log_message)

def execute_sell(pos, label, reason, auto_trade, pending, market_open, pct=100, operation="SELL"):
    """Vendita totale o parziale di una posizione (o segnalazione in modalità Advisor). Restituisce l'ordine o None."""
    sym, qty = pos["symbol"], pos["qty"]
    part = "" if pct >= 100 else f" ({pct:.0f}%)"
    if not auto_trade:
        log_message(f"🧭 [Advisor] Suggerita VENDITA{part} ({label}) di {sym}: ordine non inviato.")
        return None
    if not alpaca_client:
        return None
    try:
        order = core.close_position_pct(sym, pct)
        pending.add(core.normalize_symbol(sym))
        note = "" if market_open or pos["is_crypto"] else " (mercato chiuso: eseguito all'apertura)"
        log_message(f"🚨 [Execution Desk] VENDITA{part} ({label}) INVIATA: {sym} (ID: {order.id}){note}")
        core.agent_say("Execution Desk", f"SELL{part} {sym} ({label}) inviato ad Alpaca", "veto")
        record_sell(pos, operation, order, pct=pct, reason=f"{label}: {reason}")
        return order
    except Exception as e:
        log_message(f"Errore Vendita {sym}: {e}")
        return None

def execute_buy(sym, amount, auto_trade, pending, label="ACQUISTO", stop_pct=None, allocation_pct=None, conviction=None,
                operation="BUY", rationale=None, price=None):
    """Acquisto a importo (notional) con stop ATR, allocazione e convinzione salvati nell'ordine."""
    if not auto_trade:
        log_message(f"🧭 [Advisor] Suggerito {label} di ${amount:,.2f} di {sym}: ordine non inviato.")
        return None
    if not alpaca_client:
        return None
    try:
        order = core.submit_notional_buy(sym, amount, stop_pct=stop_pct, allocation_pct=allocation_pct, conviction=conviction)
        pending.add(core.normalize_symbol(sym))
        log_message(f"✅ [Execution Desk] {label} INVIATO: ${amount:,.2f} di {sym} (stop {stop_pct}%, ID: {order.id})")
        core.agent_say("Execution Desk", f"BUY {sym} ${amount:,.2f} inviato ad Alpaca (stop {stop_pct}%)", "ok")
        core.record_execution(sym, operation, "BUY", price=price, quantity=amount / price if price else None, notional=amount,
                              rationale=rationale, order_id=order.id, note=label, log=log_message)
        return order
    except Exception as e:
        log_message(f"Errore Ordine Acquisto {sym}: {e}")
        return None

def rotate_capital(pos, sell_pct, target, amount, cfg, auto_trade, pending, stop_pct=None, allocation_pct=None, conviction=None,
                   rationale=None, price=None):
    """Rotazione asimmetrica: vende il sell_pct% di pos e reinveste su target entro il limite di esposizione."""
    if not auto_trade:
        log_message(f"🧭 [Advisor] Rotazione suggerita: vendi {sell_pct:.0f}% di {pos['symbol']} → ${amount:,.2f} di {target}.")
        return
    order = execute_sell(pos, "ROTAZIONE", f"Capitale riallocato su {target}", auto_trade, pending, True, pct=sell_pct,
                         operation="ASSET SWAP")
    if not order:
        return
    filled = core.wait_for_fill(order.id, timeout=30, log=log_message)
    if not filled:
        log_message(f"🔄 Vendita di {pos['symbol']} non ancora eseguita: l'acquisto di {target} è rimandato.")
        return
    exposure_after = sum(abs(p["market_value"]) for p in get_open_positions())
    funds, _ = core.buy_budget(get_account_summary(), exposure_after, cfg, crypto=core.is_crypto(target), pct=100)
    final_amount = min(amount, funds)
    if final_amount < core.MIN_ORDER_USD:
        log_message(f"🔄 Nessun reinvestimento in {target}: fondi entro il limite di esposizione ${funds:,.2f}.")
        return
    execute_buy(target, final_amount, auto_trade, pending, label=f"ACQUISTO DA ROTAZIONE {allocation_pct}%",
                stop_pct=stop_pct, allocation_pct=allocation_pct, conviction=conviction,
                operation="ASSET SWAP", rationale=rationale, price=price)

def describe_decision(d):
    if d["action"] == "ROTATE":
        return f"ROTATE {d.get('sell_pct') or 100:.0f}% {d['sell_symbol']} → {d['buy_symbol']}"
    if d["action"] == "BUY":
        return f"BUY {d['buy_symbol']}"
    if d["action"] == "SELL":
        return f"SELL {d.get('sell_pct') or 100:.0f}% {d['sell_symbol']}"
    return "HOLD"

def run_trading_cycle(manual=False, boot=False, trigger="programmato"):
    """Tier 4-5: difesa del portafoglio, decisione del CIO sulle schede APPROVED_BY_RISK ed esecuzione.

    Con boot=True (primo ciclo dopo avvio/deploy) non esegue acquisti né rotazioni.
    """
    if not scan_lock.acquire(blocking=False):
        log_message("⚠️ Ciclo del CIO già in corso.")
        return

    try:
        bot_state["status"] = "Scansione & Valutazione in corso..."
        bot_state["last_scan"] = core.now_local().strftime("%Y-%m-%d %H:%M:%S")
        log_message(f"=== CICLO CIO · Tier 4-5 ({'manuale' if manual else trigger}) ===")
        if boot:
            log_message("🌅 Ciclo di avvio: solo vendite difensive, nessun acquisto dopo il deploy.")

        cfg = core.get_config()
        auto_trade = cfg["auto_execute_trades"]
        if not auto_trade:
            log_message("🧭 Modalità Advisor: le decisioni vengono solo registrate, nessun ordine inviato.")
        pending = core.get_pending_order_symbols(log=log_message)
        orders_allowed = pending is not None
        if not orders_allowed:
            log_message("⚠️ Stato ordini pendenti sconosciuto: nessun ordine in questo ciclo.")
            pending = set()
        market_open = core.is_market_open(log=log_message)
        positions = get_open_positions()
        acc = get_account_summary()
        state = core.load_state()

        # Post-Trade Auditor: storico e posizioni ricostruiti da Alpaca
        ledger = core.sync_ledger(log=log_message) or {"trades": core.read_json_file(core.TRADE_HISTORY_PATH, []), "open": {}}
        perf = core.performance_stats(ledger["trades"])
        with state_lock:
            bot_state["ledger_open"] = {k: {kk: (vv.isoformat() if hasattr(vv, "isoformat") else vv) for kk, vv in v.items()}
                                        for k, v in ledger["open"].items()}
            bot_state["performance"] = perf

        # Difesa del portafoglio: stop ATR, trailing, trend ribassista, stallo (consentita anche con drawdown)
        held_yf = [p["yf_symbol"] for p in positions]
        analysis = core.market_analyst(held_yf, log=log_message) if positions else {}
        drawdown = core.drawdown_controller(acc, state, log=log_message)
        if positions:
            core.refresh_held_evaluations(held_yf, log=log_message)   # score CIO aggiornato per l'Alpha Decay
        vol, stops, trailing = (core.volatility_agent(held_yf, positions, cfg, log=log_message, ledger=ledger,
                                                      market_open=market_open) if positions else ({}, {}, {}))
        # Stop effettivo dell'Agente #6 (breakeven / trailing): il radar lo controlla h24 ogni ~20 secondi
        with state_lock:
            for key, g in trailing.items():
                bot_state["ledger_open"].setdefault(key, {})["effective_stop_pct"] = g.get("effective_stop_pct")
        risk = core.risk_manager(positions, analysis, acc, cfg, log=log_message, stops=stops, trailing=trailing, ledger=ledger,
                                 market_open=market_open)
        sold = set()
        for r in risk["positions"]:
            if r["status"] not in ("STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP", "BREAKEVEN_STOP", "ALPHA_DECAY",
                                   "TIME_STOP", "RIBASSISTA", "STALLO"):
                continue
            pos = r["pos"]
            key = core.normalize_symbol(pos["symbol"])
            if not orders_allowed or key in pending:
                log_message(f"💼 [CIO] {pos['symbol']}: vendita ({r['status']}) rimandata, ordine già pendente.")
                continue
            log_message(f"💼 [CIO] SELL difensivo {pos['symbol']} ({r['status']}): {r['reason']}")
            if execute_sell(pos, r["status"].replace("_", " "), r["reason"], auto_trade, pending, market_open,
                            operation=journal_operation(r["status"], pos)) or not auto_trade:
                sold.add(key)
        core.save_state(state)

        # Tier 4: CIO sulle sole schede approvate dal Comitato Rischi
        channels = core.latest_channels()
        held_keys = {core.normalize_symbol(p["yf_symbol"]) for p in positions}
        inbox = [p for p in core.cio_inbox() if core.normalize_symbol(p["symbol"]) not in held_keys | pending]
        core.agent_say("CIO", f"Ciclo ({'manuale' if manual else trigger}): {len(inbox)} schede APPROVED_BY_RISK da valutare")
        log_message("📥 [CIO] Schede APPROVED_BY_RISK: " + (", ".join(
            f"{p['symbol']} (score {p['score']}, scade tra {max(0, int((p['expires_epoch'] - time.time()) / 60))} min)"
            for p in inbox) if inbox else "nessuna"))
        exposure = risk["exposure"]
        funds_stock, _ = core.buy_budget(acc, exposure, cfg, crypto=False, pct=100)
        funds_crypto, _ = core.buy_budget(acc, exposure, cfg, crypto=True, pct=100)
        account_ctx = {"equity": risk["equity"], "exposure": exposure, "funds": funds_stock, "funds_crypto": funds_crypto}
        holdings = [{"symbol": r["pos"]["symbol"], "yf_symbol": r["pos"]["yf_symbol"], "market_value": r["pos"]["market_value"],
                     "weight_pct": r["pos"]["market_value"] / risk["equity"] * 100 if risk["equity"] else 0,
                     "pnl_pct": r["pos"]["unrealized_plpc"], "score": r["score"], "status": r["status"]}
                    for r in risk["positions"] if core.normalize_symbol(r["pos"]["symbol"]) not in sold]

        if inbox:
            decision, source = core.ask_desk_cio(core.build_desk_cio_prompt(inbox, holdings, account_ctx, channels, cfg), log=log_message)
            if not decision:
                log_message("🧮 Nessuna IA disponibile: decide il CIO quantitativo di riserva.")
                decision, source = core.quant_desk_cio(inbox, holdings, account_ctx), "Quant"
            log_message(f"💼 [CIO] Mandato proposto ({source}): {describe_decision(decision)}, convinzione "
                        f"{decision.get('conviction_score')}, allocazione {decision.get('allocation_pct')}% — "
                        f"{core.summarize_reason(decision['reason'], 240)}")
        else:
            decision, source = {"action": "HOLD", "buy_symbol": "", "sell_symbol": "",
                                "reason": "Nessuna scheda approvata dal Comitato Rischi da valutare."}, "—"

        final = core.validate_desk_decision(decision, inbox, holdings, account_ctx, cfg, channels, sold_keys=sold | pending)
        if describe_decision(final) != describe_decision(decision) or final.get("notes"):
            log_message(f"💼 [CIO] Mandato esecutivo: {describe_decision(final)}"
                        + (f" — {'; '.join(final.get('notes', []))}" if final.get("notes") else "")
                        + (f" — {final['reason']}" if final["action"] == "HOLD" and decision["action"] != "HOLD" else ""))

        core.agent_say("CIO", f"Mandato: {describe_decision(final)}"
                       + (f" · convinzione {final.get('conviction_score')} · allocazione {final.get('allocation_pct')}%"
                          if final["action"] in ("BUY", "ROTATE") else "")
                       + f" — {core.summarize_reason(final['reason'] or decision['reason'], 140)}",
                       "ok" if final["action"] in ("BUY", "ROTATE") else "info")

        # Tier 5: Execution Desk
        if drawdown["blocked"] and final["action"] in ("BUY", "ROTATE"):
            log_message(f"🚫 [Drawdown] {describe_decision(final)} annullato: acquisti bloccati "
                        f"(perdita giornaliera {drawdown['drawdown_pct']:+.2f}%).")
            final = {"action": "HOLD", "buy_symbol": "", "sell_symbol": "", "notes": [],
                     "reason": f"Acquisti bloccati dal Drawdown Controller ({drawdown['drawdown_pct']:+.2f}%)"}
        suspended = boot and final["action"] in ("BUY", "ROTATE")
        executed = False
        entry_rationale, entry_price = None, None
        if final["action"] in ("BUY", "ROTATE"):
            pitch = next((p for p in inbox if core.normalize_symbol(p["symbol"]) == core.normalize_symbol(final["buy_symbol"])), {})
            package = pitch.get("package") or {}
            entry_price = package.get("entry_price")
            entry_rationale = {
                "agents": core.quant_rationale(final["buy_symbol"]),
                "desk_cio": {"source": source, "conviction": final.get("conviction_score"),
                             "allocation_pct": final.get("allocation_pct"), "reason": final["reason"] or decision["reason"]},
                "risk_package": package,
            }
        if suspended:
            log_message(f"🌅 [Avvio] {describe_decision(final)} non eseguito: acquisti sospesi nel ciclo di avvio.")
        elif orders_allowed and final["action"] == "BUY":
            executed = bool(execute_buy(final["buy_symbol"], final["buy_amount"], auto_trade, pending,
                                        label=f"ACQUISTO CIO {final['allocation_pct']}%",
                                        stop_pct=final["dynamic_stop_loss_pct"], allocation_pct=final["allocation_pct"],
                                        conviction=final["conviction_score"], rationale=entry_rationale, price=entry_price))
        elif orders_allowed and final["action"] in ("ROTATE", "SELL"):
            pos = next(p for p in positions if core.normalize_symbol(p["yf_symbol"]) == core.normalize_symbol(final["sell_symbol"]))
            if final["action"] == "SELL":
                execute_sell(pos, "DECISIONE CIO", final["reason"], auto_trade, pending, market_open, pct=final["sell_pct"])
            else:
                rotate_capital(pos, final["sell_pct"], final["buy_symbol"], final["buy_amount"], cfg, auto_trade, pending,
                               stop_pct=final["dynamic_stop_loss_pct"], allocation_pct=final["allocation_pct"],
                               conviction=final["conviction_score"], rationale=entry_rationale, price=entry_price)
                executed = auto_trade
        if inbox:
            core.record_cio_outcome(final.get("buy_symbol") or None, executed, describe_decision(final))
        if suspended:
            # La scheda resta APPROVED_BY_RISK: il CIO la rivaluta appena finito il ciclo di avvio, prima che scada
            request_cio(f"scheda {final['buy_symbol']} sospesa nel ciclo di avvio")

        macro = (channels.get("macro") or {})
        with state_lock:
            bot_state["cio"] = {
                "action": final["action"], "buy_symbol": final.get("buy_symbol", ""), "sell_symbol": final.get("sell_symbol", ""),
                "sell_pct": final.get("sell_pct"), "conviction": final.get("conviction_score"),
                "allocation_pct": final.get("allocation_pct"), "amount": final.get("buy_amount"),
                "stop_pct": final.get("dynamic_stop_loss_pct"), "notes": final.get("notes", []),
                "source": source, "reason": final["reason"] or decision["reason"], "proposal": describe_decision(decision),
                "suspended": suspended, "scout_approved": final["action"] in ("BUY", "ROTATE"),
                "timestamp": core.now_local().strftime("%H:%M:%S"), "trigger": "manuale" if manual else trigger,
                "macro": macro.get("regime") or {}, "vix": macro.get("vix"),
            }
        set_ai_analysis(symbol=final.get("buy_symbol") or final.get("sell_symbol") or "PORTAFOGLIO", rsi="--",
                        sentiment=f"Esposizione ${exposure:,.0f} / capitale ${risk['equity']:,.0f}",
                        ai_verdict=f"{describe_decision(final)} ({source})", reasoning=final["reason"] or decision["reason"])

        bot_state["status"] = "Attivo (In attesa ciclo)" if bot_state["active"] else "In pausa"
        log_message("=== CICLO CIO COMPLETATO ===")

    finally:
        if bot_state["status"].startswith("Scansione"):
            bot_state["status"] = "In pausa" if not bot_state["active"] else "Attivo (In attesa ciclo)"
        scan_lock.release()

# Risveglio event-driven del CIO (schede approvate o stop toccato)
cio_wake = threading.Event()
cio_trigger = {"reason": "", "urgent": False}
_trigger_lock = threading.Lock()

def request_cio(reason, urgent=False):
    with _trigger_lock:
        if not cio_wake.is_set() or urgent:
            cio_trigger.update(reason=reason, urgent=urgent or cio_trigger.get("urgent", False))
        cio_wake.set()

def background_loop():
    """CIO: ciclo programmato ogni scan_interval_min, oppure subito su richiesta (schede approvate, stop).

    Il risveglio da nuove schede rispetta un intervallo minimo (CIO_MIN_GAP_SEC); gli stop sono urgenti.
    """
    time.sleep(core.STARTUP_GRACE_SECONDS)
    try:
        core.startup_system_sync(log=log_message)
    except Exception as e:
        log_message(f"🔄 [Sync] Errore sincronizzazione di avvio: {e}")
    last_run = 0.0
    boot = True  # il primo ciclo dopo l'avvio non apre posizioni
    while True:
        if wake_event.is_set():  # bot riattivato dalla dashboard
            wake_event.clear()
            last_run = 0.0
        now = time.time()
        interval = core.get_config()["scan_interval_min"] * 60
        trigger = None
        if bot_state["active"]:
            if now - last_run >= interval:
                trigger = "programmato"
            elif cio_wake.is_set() and (cio_trigger["urgent"] or now - last_run >= core.CIO_MIN_GAP_SEC):
                trigger = cio_trigger["reason"] or "evento"
        if trigger:
            with _trigger_lock:
                cio_wake.clear()
                cio_trigger.update(reason="", urgent=False)
            last_run = now
            try:
                run_trading_cycle(boot=boot, trigger=trigger)
                boot = False
            except Exception as e:
                log_message(f"Errore ciclo CIO: {e}")
        # Attesa: se c'è un evento in coda ma non è ancora passato l'intervallo minimo, pausa breve
        if cio_wake.is_set():
            time.sleep(5)
        else:
            cio_wake.wait(15)

def radar_loop():
    """Tier 1-3: sciame di micro-scout + Chief of Staff + Comitato Rischi, un paniere alla volta in rotazione.

    Non invia ordini. Controlla anche gli stop delle posizioni e, se toccati, sveglia subito il CIO.
    """
    time.sleep(core.STARTUP_GRACE_SECONDS + 20)  # dopo la sincronizzazione di avvio
    while True:
        started = time.time()
        if bot_state["active"]:
            try:
                positions = get_open_positions()
                held = {core.normalize_symbol(p["yf_symbol"]) for p in positions}
                pending = core.get_pending_order_symbols(log=lambda m: None) or set()
                core.run_scout_swarm(held_keys=held, pending=pending, log=log_message, rotate=True,
                                     exposure_usd=sum(abs(p["market_value"]) for p in positions), positions_count=len(positions),
                                     on_approved=lambda: request_cio("schede approvate dal Comitato Rischi"))
                # Mercato USA chiuso: pulse silenzioso dei panieri azionari (si autolimita a 1 volta ogni 15 min)
                core.run_closed_market_pulse(log=log_message)
                # Controllo rapido degli stop (stop del CIO salvato nell'ordine, altrimenti quello di riserva)
                stops = bot_state.get("ledger_open", {})
                fallback = core.get_config()["stop_loss_pct"]
                for p in positions:
                    info = stops.get(core.normalize_symbol(p["symbol"])) or {}
                    stop = info.get("stop_pct") or fallback
                    # Agente #6: stop rialzato a breakeven o dal trailing ATR (calcolato nell'ultimo ciclo del CIO)
                    if info.get("effective_stop_pct") is not None:
                        stop = max(stop, info["effective_stop_pct"])
                    if p["unrealized_plpc"] <= stop and core.normalize_symbol(p["symbol"]) not in pending:
                        log_message(f"🛑 [Radar] {p['symbol']} a {p['unrealized_plpc']:.2f}% ha toccato lo stop {stop:+.2f}%: sveglio il CIO.")
                        request_cio(f"stop toccato su {p['symbol']}", urgent=True)
            except Exception as e:
                log_message(f"📡 Errore sciame: {e}")
        # Scansione continua: un paniere ogni RADAR_INTERVAL_SEC / numero di panieri (~20s)
        tick = core.RADAR_INTERVAL_SEC / len(core.DESK_BASKETS)
        time.sleep(max(5, tick - (time.time() - started)))

def chop_loop():
    """Agente #7 (CHOP Watchdog): auto-healing e audit dello sciame ogni 30 secondi."""
    time.sleep(core.STARTUP_GRACE_SECONDS + 30)
    while True:
        try:
            line = core.chop_audit(log=log_message)
            if line:
                core.agent_say("CHOP", line.replace("🐝 [CHOP SWARM AUDIT] ", ""), "muted")
        except Exception as e:
            log_message(f"🐝 [CHOP] Errore audit: {e}")
        time.sleep(5)

def keep_alive_url():
    base = os.getenv("RENDER_EXTERNAL_URL")
    if base:
        return base.rstrip("/") + "/ping"
    return f"http://127.0.0.1:{os.getenv('PORT', '5000')}/ping"

def keep_alive_loop():
    """Anti-Sleep: self-ping periodico per evitare lo spegnimento per inattività (es. Render free)."""
    while True:
        time.sleep(KEEP_ALIVE_INTERVAL)
        if not core.get_config()["keep_alive_enabled"]:
            continue
        url = keep_alive_url()
        try:
            r = requests.get(url, timeout=5)
            if r.ok:
                log_message("[Keep-Alive] Self-ping completato")
            else:
                log_message(f"[Keep-Alive] Self-ping fallito: HTTP {r.status_code} ({url})")
        except Exception as e:
            log_message(f"[Keep-Alive] Errore self-ping verso {url}: {e}")

app = Flask(__name__)
# Render (e simili) stanno dietro un proxy: serve per IP reale e schema https
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(
    SECRET_KEY=core.get_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.getenv("RENDER_EXTERNAL_URL")),
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=7),
)
core.get_dashboard_password()  # genera (e stampa nei log) la password al primo avvio se non configurata

# NB: lo stato è in memoria nel processo. Avviare con UN solo worker
# (vedi Procfile), altrimenti ogni worker eseguirebbe il proprio loop di trading.
_threads_lock = threading.Lock()
_threads_pid = None

def start_background_threads():
    """Avvia i thread di trading e Keep-Alive una sola volta per processo.

    Con gunicorn --preload l'app viene importata nel master prima del fork e i thread
    avviati lì non esistono nel worker che serve la dashboard: per questo sotto gunicorn
    vengono avviati nel worker (gunicorn.conf.py o, in alternativa, alla prima richiesta).
    """
    global _threads_pid
    with _threads_lock:
        if _threads_pid == os.getpid():
            return
        _threads_pid = os.getpid()
    threading.Thread(target=background_loop, daemon=True).start()
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    threading.Thread(target=radar_loop, daemon=True).start()
    threading.Thread(target=chop_loop, daemon=True).start()
    log_message(f"🧵 Thread di trading, radar Esploratore e Keep-Alive avviati (PID {os.getpid()})")
    cfg = core.get_config()
    mode = "Auto-Trading attivo" if cfg["auto_execute_trades"] else "Advisor (nessun ordine)"
    locked = core.env_overrides()
    source = (f"fissata da {core.ENV_OVERRIDES['auto_execute_trades']}" if "auto_execute_trades" in locked
              else "default/config.json (BOT_AUTO_EXECUTE non impostata)")
    log_message(f"⚙️ Modalità di avvio: {mode} — {source}")
    if locked:
        log_message(f"⚙️ Impostazioni fissate da variabili d'ambiente: "
                    f"{', '.join(f'{core.ENV_OVERRIDES[k]}={v}' for k, v in locked.items())}")
    log_message(f"⚙️ Configurazione (priorità crescente): {' → '.join(core.config_sources())}")
    log_message(f"⏳ Grace period di {core.STARTUP_GRACE_SECONDS}s, poi sincronizzazione con Alpaca e ciclo di avvio.")

@app.before_request
def ensure_background_threads():
    start_background_threads()

# gunicorn imposta SERVER_SOFTWARE prima di importare l'app (anche con --preload)
if "gunicorn" not in os.getenv("SERVER_SOFTWARE", ""):
    start_background_threads()

@app.route("/login", methods=["GET", "POST"])
def login():
    if is_logged_in():
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        blocked = login_blocked_for(ip)
        if blocked:
            error = f"Troppi tentativi errati. Riprova tra {blocked} secondi."
        elif hmac.compare_digest(request.form.get("password", "").encode(), core.get_dashboard_password().encode()):
            with _failed_lock:
                _failed_logins.pop(ip, None)
            session.clear()
            session.permanent = True
            session["auth"] = True
            log_message(f"🔐 Login dashboard riuscito da {ip}")
            return redirect(url_for("index"))
        else:
            register_failed_login(ip)
            log_message(f"🔐 Tentativo di login fallito da {ip}")
            error = "Password errata."
    return render_template("login.html", error=error), (401 if error else 200)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    if not is_logged_in():
        return redirect(url_for("login"))
    # Il token è inserito solo nella pagina riservata, dopo il login
    return render_template("index.html", api_token=core.get_api_token())

@app.route("/ping")
def ping():
    return jsonify({"status": "alive", "timestamp": core.now_local().isoformat()}), 200

def account_with_pnl():
    acc = dict(get_account_summary())
    acc.update(core.pnl_summary(acc.get("portfolio", 0) or 0, acc.get("last_equity", 0) or 0))
    positions = cached("positions", get_open_positions)
    acc["exposure"] = round(sum(abs(p["market_value"]) for p in positions), 2)
    return acc

def positions_with_allocation():
    """Posizioni con allocazione decisa dal CIO, convinzione e stop (letti dagli ordini Alpaca)."""
    out = []
    for p in cached("positions", get_open_positions):
        info = bot_state.get("ledger_open", {}).get(core.normalize_symbol(p["symbol"]), {})
        out.append({**p, "allocation_pct": info.get("allocation_pct"), "conviction": info.get("conviction"),
                    "stop_pct": info.get("stop_pct"), "opened_at": info.get("opened_at")})
    return out

@app.route("/api/data")
@require_login
def api_data():
    if is_logged_in():
        core.mark_user_seen()   # dashboard aperta: le operazioni eseguite ora non sono "offline"
    # Risposta incrementale: il client indica l'ultimo id di log e di dialogo già ricevuti
    since_log = request.args.get("since_log", default=0, type=int)
    since_dialogue = request.args.get("since_dialogue", default=0, type=int)
    with state_lock:
        bot = {
            "active": bot_state["active"],
            "last_scan": bot_state["last_scan"],
            "status": bot_state["status"],
            "logs": [l for l in bot_state["logs"] if l["id"] > since_log],
            "latest_ai_analysis": dict(bot_state["latest_ai_analysis"]),
            "cio": dict(bot_state["cio"]),
            "performance": dict(bot_state["performance"]),
        }
    return jsonify({
        "account": cached("account_pnl", account_with_pnl),
        "positions": positions_with_allocation(),
        "bot": bot,
        "radar": core.radar_snapshot(),
        "agent_dialogue": core.dialogue_since(since_dialogue),
        # id più recenti disponibili: se sono inferiori a quelli del client il server è stato riavviato
        "log_head": bot_state["logs"][-1]["id"] if bot_state["logs"] else 0,
        "dialogue_head": core.dialogue_head(),
        "sources": {
            "yfinance": "Yahoo Finance API (News & Historical)",
            "alpaca": "Alpaca Paper Trading v2 API",
            "ai": "Groq (CIO) / Gemini di riserva + motore quantitativo",
            "ta": "Indicatori Tecnici RSI(14) e SMA"
        }
    })

def _cancel_open_orders(alpaca_symbol):
    """Annulla gli ordini aperti di un solo simbolo (altrimenti le quote restano bloccate)."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    key = core.normalize_symbol(alpaca_symbol)
    for o in alpaca_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN)):
        if core.normalize_symbol(o.symbol) == key:
            alpaca_client.cancel_order_by_id(o.id)

def _find_position(symbol):
    key = core.normalize_symbol(symbol)
    return next((p for p in get_open_positions() if core.normalize_symbol(p["symbol"]) == key), None)

@app.route("/api/positions/<symbol>")
@require_login
def api_position_detail(symbol):
    """Scheda di una posizione aperta: apertura, prezzi, PnL, rationale dei 5 agenti, stop e take profit."""
    pos = _find_position(symbol)
    if not pos:
        return jsonify({"status": "error", "message": f"Nessuna posizione aperta su {symbol}"}), 404
    info = bot_state.get("ledger_open", {}).get(core.normalize_symbol(pos["symbol"]), {})
    entry = core.last_entry_execution(pos["yf_symbol"])
    rationale = (entry or {}).get("rationale") or {}
    rationale_source = "al momento dell'acquisto" if rationale.get("agents") else None
    if not rationale.get("agents"):
        live = core.quant_rationale(pos["yf_symbol"], max_age_sec=None)
        if live:
            rationale = {**rationale, "agents": live}
            rationale_source = "ultima valutazione disponibile (acquisto non registrato nel journal)"
    avg = pos["avg_entry_price"]
    stop_pct = info.get("stop_pct") or core.get_config()["stop_loss_pct"]
    package = rationale.get("risk_package") or {}
    agents = rationale.get("agents") or {}
    take_profit = package.get("target_price") or (agents.get("agent_03_risk") or {}).get("take_profit_price")
    return jsonify({
        "position": pos,
        "opened_at": info.get("opened_at") or (entry or {}).get("timestamp"),
        "allocation_pct": info.get("allocation_pct"), "conviction": info.get("conviction"),
        "stop_loss": {"pct": stop_pct, "price": round(avg * (1 + stop_pct / 100), 6) if avg else None,
                      "source": "stop ATR del CIO" if info.get("stop_pct") else "stop di riserva"},
        "take_profit": {"price": take_profit,
                        "pct": round((take_profit / avg - 1) * 100, 2) if take_profit and avg else None},
        "rationale": rationale or None, "rationale_source": rationale_source,
        "entry_execution": entry,
    })

@app.route("/api/positions/<symbol>/close", methods=["POST"])
@require_token
def api_position_close(symbol):
    """🔴 VENDI SUBITO: chiusura manuale immediata di una singola posizione."""
    if not alpaca_client:
        return jsonify({"status": "error", "message": "Credenziali Alpaca non configurate."}), 503
    pos = _find_position(symbol)
    if not pos:
        return jsonify({"status": "error", "message": f"Nessuna posizione aperta su {symbol}"}), 404
    try:
        _cancel_open_orders(pos["symbol"])
    except Exception as e:
        log_message(f"Errore annullamento ordini aperti di {pos['symbol']}: {e}")
    try:
        order = core.close_position(pos["symbol"])
    except Exception as e:
        log_message(f"Errore vendita manuale {pos['symbol']}: {e}")
        return jsonify({"status": "error", "message": f"Vendita di {pos['symbol']} non riuscita: {e}"}), 502
    log_message(f"🔴 VENDI SUBITO dalla dashboard: {pos['qty']} x {pos['symbol']} (ID: {getattr(order, 'id', '?')})")
    core.agent_say("Execution Desk", f"SELL 100% {pos['symbol']} (manuale, dashboard) inviato ad Alpaca", "veto")
    record_sell(pos, "MANUAL SELL", order, reason="Vendi subito (dashboard)", source="manual")
    with _cache_lock:
        _cache.clear()
    return jsonify({"status": "success", "message": f"Vendita di {pos['symbol']} inviata."})

@app.route("/api/history")
@require_login
def api_history():
    """Registro operazioni; ?offline=1 solo quelle eseguite mentre la dashboard era chiusa."""
    offline = request.args.get("offline", "0") in ("1", "true")
    limit = max(1, min(request.args.get("limit", default=200, type=int), 1000))
    return jsonify({"executions": core.list_executions(offline_only=offline, limit=limit)})

@app.route("/api/settings", methods=["GET"])
@require_login
def api_settings_get():
    return jsonify(core.public_config())

@app.route("/api/settings", methods=["POST"])
@require_token
def api_settings_post():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Corpo JSON non valido"}), 400
    try:
        core.update_config(data)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except OSError as e:
        return jsonify({"status": "error", "message": f"Impossibile salvare config.json: {e}"}), 500
    log_message("⚙️ Impostazioni aggiornate da Dashboard Web.")
    return jsonify({"status": "success", "message": "Impostazioni salvate", "settings": core.public_config()})

@app.route("/api/scan", methods=["POST"])
@app.route("/api/trigger", methods=["POST"])
@require_token
def api_trigger():
    if scan_lock.locked():
        return jsonify({"status": "warning", "message": "Il CIO sta già valutando: attendi la fine del ciclo."})

    log_message("⚡ Forza CIO dalla dashboard: valutazione immediata delle schede in coda.")
    core.agent_say("CIO", "⚡ Override manuale: valutazione immediata della coda", "alert")
    threading.Thread(target=run_trading_cycle, kwargs={"manual": True, "trigger": "⚡ Forza CIO"}, daemon=True).start()
    return jsonify({"status": "success", "message": "CIO attivato: valutazione delle schede in coda"})

@app.route("/api/toggle", methods=["POST"])
@require_token
def api_toggle():
    bot_state["active"] = not bot_state["active"]
    if bot_state["active"]:
        wake_event.set()  # riparte subito senza attendere l'intervallo
    elif not scan_lock.locked():
        bot_state["status"] = "In pausa"
    log_message(f"Stato Bot impostato a: Active={bot_state['active']}")
    return jsonify({"active": bot_state["active"], "is_running": bot_state["active"]})

@app.route("/api/liquidate", methods=["POST"])
@require_token
def api_liquidate():
    if not alpaca_client:
        return jsonify({"status": "error", "message": "Credenziali Alpaca non configurate."}), 503

    # PANIC: il bot va in pausa, altrimenti al ciclo successivo riaprirebbe posizioni
    bot_state["active"] = False
    if not scan_lock.locked():
        bot_state["status"] = "In pausa (PANIC)"
    log_message("🚨 PANIC - CHIUDI TUTTO dalla dashboard: bot in pausa, annullo gli ordini e chiudo tutte le posizioni.")
    core.agent_say("Execution Desk", "🚨 PANIC: bot in pausa, chiusura di tutte le posizioni", "veto")
    positions = get_open_positions()
    if not positions:
        return jsonify({"status": "warning", "message": "Nessuna posizione aperta da liquidare. Bot in pausa."})

    # Annulla gli ordini aperti: altrimenti le quote sono bloccate e la vendita fallisce
    try:
        alpaca_client.cancel_orders()
    except Exception as e:
        log_message(f"Errore annullamento ordini aperti: {e}")

    count = 0
    for pos in positions:
        sym = pos["symbol"]
        qty = pos["qty"]
        try:
            order = core.close_position(sym)
            log_message(f"🚨 LIQUIDAZIONE MANUALE: Vendita {qty} x {sym}")
            record_sell(pos, "PANIC SELL", order, reason="🚨 PANIC - CHIUDI TUTTO (dashboard)", source="manual")
            count += 1
        except Exception as e:
            log_message(f"Errore vendita manuale {sym}: {e}")

    with _cache_lock:
        _cache.clear()
    return jsonify({"status": "success", "message": f"PANIC: {count}/{len(positions)} posizioni in chiusura, bot in pausa "
                                                   "(premi Riprendi per riattivarlo)."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
