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
DATA_CACHE_TTL = 5  # secondi: limita le chiamate ad Alpaca dal polling della dashboard

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
    "logs": deque(maxlen=150),  # ordine cronologico: il più recente è in fondo
    "boardroom": [],  # badge con il parere dei principali agenti (dashboard)
    "office": {},     # Ufficio Virtuale: ricerca dell'Esploratore #1, revisione e decisione del CIO
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

def execute_sell(pos, label, reason, auto_trade, pending, market_open):
    """Chiude una posizione (o la segnala in modalità Advisor). Restituisce l'ordine o None."""
    sym, qty = pos["symbol"], pos["qty"]
    if not auto_trade:
        log_message(f"🧭 [Advisor] Suggerita VENDITA ({label}) di {sym} ({qty} quote): ordine non inviato.")
        return None
    if not alpaca_client:
        return None
    try:
        order = core.close_position(sym)
        pending.add(core.normalize_symbol(sym))
        note = "" if market_open or pos["is_crypto"] else " (mercato chiuso: eseguito all'apertura)"
        log_message(f"🚨 ORDINE VENDITA ({label}) INVIATO: {sym} {qty} quote (ID: {order.id}){note}")
        return order
    except Exception as e:
        log_message(f"Errore Vendita {sym}: {e}")
        return None

def execute_buy(sym, amount, auto_trade, pending, label="ACQUISTO", stop_pct=None):
    """Acquisto a importo (notional) o segnalazione in modalità Advisor. Restituisce l'ordine o None."""
    if not auto_trade:
        log_message(f"🧭 [Advisor] Suggerito {label} di ${amount:,.2f} di {sym}: ordine non inviato.")
        return None
    if not alpaca_client:
        return None
    try:
        order = core.submit_notional_buy(sym, amount, stop_pct=stop_pct)
        pending.add(core.normalize_symbol(sym))
        log_message(f"✅ ORDINE {label} INVIATO: ${amount:,.2f} di {sym} (ID: {order.id})")
        return order
    except Exception as e:
        log_message(f"Errore Ordine Acquisto {sym}: {e}")
        return None

def rotate_capital(sell_report, target, cfg, auto_trade, pending, stop_pct=None):
    """Opportunity Cost Trade: vende sell_report e reinveste il ricavato su target entro il limite di esposizione."""
    pos = sell_report["pos"]
    if not auto_trade:
        log_message(f"🧭 [Advisor] Rotazione suggerita {pos['symbol']} → {target}: ordini non inviati.")
        return
    order = execute_sell(pos, "PER ROTAZIONE", f"Capitale riallocato su {target}", auto_trade, pending, True)
    if not order:
        return
    filled = core.wait_for_fill(order.id, timeout=30, log=log_message)
    if not filled:
        log_message(f"🔄 Vendita di {pos['symbol']} non ancora eseguita: l'acquisto di {target} è rimandato al prossimo ciclo.")
        return

    proceeds = float(filled.filled_qty or 0) * float(filled.filled_avg_price or 0)
    exposure_after = sum(abs(p["market_value"]) for p in get_open_positions())
    funds, _ = core.buy_budget(get_account_summary(), exposure_after, cfg, crypto=core.is_crypto(target))
    amount = min(proceeds, funds)
    if amount < core.MIN_ORDER_USD:
        log_message(f"🔄 Nessun reinvestimento in {target}: fondi entro il limite di esposizione ${funds:,.2f}.")
        return
    execute_buy(target, amount, auto_trade, pending, label="ACQUISTO DA ROTAZIONE", stop_pct=stop_pct)

def describe_decision(d):
    if d["action"] == "ROTATE":
        return f"ROTATE {d['sell_symbol']} → {d['buy_symbol']}"
    if d["action"] == "BUY":
        return f"BUY {d['buy_symbol']}"
    if d["action"] == "SELL":
        return f"SELL {d['sell_symbol']}"
    return "HOLD"

def badge(agent, value, tone="ok"):
    return {"agent": agent, "value": value, "tone": tone}

def run_trading_cycle(manual=False, boot=False):
    """Ciclo del boardroom. Con boot=True (primo ciclo dopo avvio/deploy) non esegue acquisti né rotazioni:
    solo analisi e vendite difensive, così un deploy non apre mai nuove posizioni."""
    # Verifica che non ci sia un'altra scansione in corso
    if not scan_lock.acquire(blocking=False):
        log_message("⚠️ Scansione già in corso. Attendi il completamento.")
        return

    try:
        bot_state["status"] = "Scansione & Valutazione in corso..."
        bot_state["last_scan"] = core.now_local().strftime("%Y-%m-%d %H:%M:%S")
        log_message("=== AVVIO VIRTUAL BOARDROOM (8 AGENTI) ===")
        if boot:
            log_message("🌅 Ciclo di avvio: solo analisi e vendite difensive, nessun acquisto dopo il deploy.")

        cfg = core.get_config()
        auto_trade = cfg["auto_execute_trades"]
        if not auto_trade:
            log_message("🧭 Modalità Advisor: le decisioni vengono solo registrate, nessun ordine inviato.")
        if not alpaca_client:
            log_message("⚠️ Credenziali Alpaca non configurate: nessun ordine verrà inviato.")

        # Ordini già aperti: evitano duplicati e accumuli a mercato chiuso
        pending = core.get_pending_order_symbols(log=log_message)
        orders_allowed = pending is not None
        if not orders_allowed:
            log_message("⚠️ Stato ordini pendenti sconosciuto: nessun ordine in questo ciclo.")
            pending = set()
        elif pending:
            log_message(f"Ordini pendenti su: {sorted(pending)}")
        market_open = core.is_market_open(log=log_message)
        positions = get_open_positions()
        acc = get_account_summary()
        state = core.load_state()
        set_ai_analysis(symbol="BOARDROOM", rsi="--", sentiment="Riunione del comitato in corso",
                        ai_verdict="ANALISI IN CORSO", reasoning="Gli 8 agenti stanno preparando i loro report...")

        # Agente 1: Market Analyst
        analysis = core.market_analyst(cfg["watchlist"] + [p["yf_symbol"] for p in positions], log=log_message)
        if not manual and should_abort():
            return
        # Ufficio Virtuale: l'Esploratore #1 perlustra un settore fuori dalla watchlist
        held_keys = {core.normalize_symbol(p["yf_symbol"]) for p in positions}
        scout_entry, scout_picks = core.run_esploratore_scout(
            exclude_keys=set(analysis) | held_keys | pending, market_open=market_open, log=log_message)
        scout_keys = set()
        for pick in scout_picks:
            key = core.normalize_symbol(pick["symbol"])
            analysis[key] = {k: pick[k] for k in ("symbol", "ind", "score", "class", "scout")}
            scout_keys.add(key)
        # Storico ordini Alpaca: trade chiusi, data di apertura e stop delle posizioni (nessuno stato locale)
        ledger = core.sync_ledger(log=log_message)
        # Agente 7: Post-Trade Auditor (penalità allo score prima delle altre valutazioni)
        audit = core.post_trade_auditor(analysis, log=log_message, ledger=ledger)
        # Agente 5: Volume & Liquidity
        volume = core.volume_agent(analysis, log=log_message)
        # Agente 4: Macro Regime
        macro = core.macro_regime(log=log_message)
        # Agente 6: Drawdown Controller
        drawdown = core.drawdown_controller(acc, state, log=log_message)

        buy_class = core.broker_candidates(analysis, held_keys, pending, market_open)
        # Le scoperte dell'Esploratore passano sempre dal Reparto Revisione (sentiment e volatilità inclusi)
        focus = list(dict.fromkeys([p["yf_symbol"] for p in positions] + [a["symbol"] for a in buy_class[:6]]
                                   + [analysis[k]["symbol"] for k in scout_keys]))
        # Agente 2: Sentiment Intelligence
        sentiment = core.sentiment_agent(focus, log=log_message)
        # Agente 3: Volatility Manager
        vol, stops, trailing = core.volatility_agent(focus, positions, cfg, log=log_message, ledger=ledger)

        # Risk Manager: stato delle posizioni con stop dinamici e trailing stop
        risk = core.risk_manager(positions, analysis, acc, cfg, log=log_message, stops=stops, trailing=trailing, ledger=ledger)

        # Vendite difensive obbligatorie (consentite anche con il blocco da drawdown)
        sold = set()
        for r in risk["positions"]:
            if r["status"] not in ("STOP_LOSS", "TRAILING_STOP", "RIBASSISTA", "STALLO"):
                continue
            pos = r["pos"]
            key = core.normalize_symbol(pos["symbol"])
            if not orders_allowed or key in pending:
                log_message(f"💼 [CIO] {pos['symbol']}: vendita ({r['status']}) rimandata, ordine già pendente.")
                continue
            log_message(f"💼 [CIO] SELL difensivo {pos['symbol']} ({r['status']}): {r['reason']}")
            if execute_sell(pos, r["status"].replace("_", " "), r["reason"], auto_trade, pending, market_open) or not auto_trade:
                sold.add(key)

        # Filtri del comitato sui candidati all'acquisto
        candidates, excluded = [], []
        for a in buy_class:
            key = core.normalize_symbol(a["symbol"])
            if drawdown["blocked"]:
                excluded.append((a["symbol"], "acquisti bloccati dal Drawdown Controller"))
            elif sentiment.get(key, {}).get("veto"):
                excluded.append((a["symbol"], f"veto Sentiment {sentiment[key]['sentiment']:+d}"))
            elif volume.get(key, {}).get("status") == "FALSO_BREAKOUT":
                excluded.append((a["symbol"], f"falso breakout, volume {volume[key]['ratio']}x"))
            elif key not in {core.normalize_symbol(s) for s in focus}:
                continue  # oltre i primi 6: non analizzato da Sentiment/Volatilità
            else:
                candidates.append(a)
        if excluded:
            log_message(f"⛔ [Comitato] Esclusi: {', '.join(f'{s} ({w})' for s, w in excluded)}")

        # Reparto Revisione: esito per ogni scoperta dell'Esploratore
        review = {}
        excluded_why = {core.normalize_symbol(s): w for s, w in excluded}
        admitted = {core.normalize_symbol(a["symbol"]) for a in candidates}
        for key in scout_keys:
            a = analysis[key]
            sent, vol_f = sentiment.get(key, {}), volume.get(key, {})
            checks = (f"tecnico {a['score']}{' (penalità auditor)' if a.get('audit_penalty') else ''}, "
                      f"sentiment {sent.get('sentiment', 0):+d}, volume {vol_f.get('ratio')}x, "
                      f"drawdown {drawdown['drawdown_pct']:+.2f}%")
            if key in admitted:
                review[key] = {"symbol": a["symbol"], "verdict": "APPROVATO", "detail": checks}
            else:
                why = excluded_why.get(key) or ("score sotto la soglia BUY dopo la revisione" if a["class"] != "BUY"
                                                else "non acquistabile ora (mercato chiuso o ordine pendente)")
                review[key] = {"symbol": a["symbol"], "verdict": "RESPINTO", "detail": f"{why}; {checks}"}
        if review:
            log_message("🏢 [Reparto Revisione] " + " | ".join(
                f"{r['symbol']}: {r['verdict']} ({r['detail']})" for r in review.values()))

        # Agente 8: Chief Investment Officer
        board = {"risk": risk, "macro": macro, "drawdown": drawdown, "volatility": vol, "sentiment": sentiment,
                 "volume": volume, "audit": audit, "candidates": candidates, "excluded": excluded,
                 "scout": scout_entry, "review": review}
        decision, source = core.ask_broker_ai(core.build_cio_prompt(board, cfg), log=log_message,
                                              system=core.CIO_SYSTEM_PROMPT)
        if not decision:
            log_message("🧮 Nessuna IA disponibile: decide il CIO quantitativo di riserva.")
            decision, source = core.ta_broker(risk, candidates), "Quant"
        log_message(f"💼 [CIO] Proposta ({source}): {describe_decision(decision)} — {core.summarize_reason(decision['reason'], 260)}")

        final = core.validate_broker_decision(decision, risk, candidates, sold_keys=sold | pending, log=log_message)
        if describe_decision(final) != describe_decision(decision):
            log_message(f"💼 [CIO] Decisione finale: {describe_decision(final)} — {final['reason']}")

        # Esito della scoperta dell'Esploratore: approvata solo se il CIO la compra davvero
        scout_buy = final["action"] in ("BUY", "ROTATE") and core.normalize_symbol(final["buy_symbol"]) in scout_keys
        if scout_keys:
            verdict = "APPROVATA" if scout_buy else "RESPINTA"
            log_message(f"🏢 [CIO → Ufficio Virtuale] Scoperta dell'Esploratore #1 {verdict}: {describe_decision(final)}"
                        + (" (il CIO l'aveva segnalata come approvata)" if decision.get("scout_discovery_approved") and not scout_buy else ""))
        cio_outcome = {"approved": scout_buy, "decision": describe_decision(final), "source": source,
                       "reason": core.summarize_reason(final["reason"] or decision["reason"], 300),
                       "suspended": boot and final["action"] in ("BUY", "ROTATE")}
        if scout_entry:
            core.update_scout_registry(core.SCOUT_ID, review, cio_outcome)
            bot_state["office"] = {
                "scout_id": scout_entry["scout_id"], "sector": scout_entry["sector_scanned"],
                "tickers_inspected": scout_entry["tickers_inspected"], "timestamp": scout_entry["timestamp"],
                "discoveries": [{**d, **review.get(core.normalize_symbol(d["symbol"]), {})} for d in scout_entry["discoveries"]],
                "cio": cio_outcome,
            }

        target = final["buy_symbol"] or final["sell_symbol"]
        target_key = core.normalize_symbol(target) if target else None
        target_info = analysis.get(target_key) if target else None
        exec_note = ""
        if orders_allowed and final["action"] in ("BUY", "ROTATE"):
            crypto = core.is_crypto(final["buy_symbol"])
            factor = macro["crypto" if crypto else "stock"]["factor"]
            pct, pct_eff = core.cio_allocation(final, target_info["score"] if target_info else None, cfg, factor)
            stop = core.cio_stop(final, vol.get(target_key))
            exec_note = (f"allocazione {pct:.1f}%" + (f" → {pct_eff:.1f}% (macro RISK-OFF)" if factor < 1 else "")
                         + (f", stop {stop:.1f}%" if stop is not None else ""))
            log_message(f"💼 [CIO] {final['buy_symbol']}: {exec_note}")

        if boot and final["action"] in ("BUY", "ROTATE"):
            log_message(f"🌅 [Avvio] {describe_decision(final)} non eseguito: acquisti sospesi nel ciclo di avvio "
                        f"(riprendono tra {cfg['scan_interval_min']} minuti).")
            exec_note = (exec_note + " · " if exec_note else "") + "sospeso (ciclo di avvio)"
        elif not orders_allowed or final["action"] == "HOLD":
            pass
        elif final["action"] == "BUY":
            _, allocation = core.buy_budget(acc, risk["exposure"], cfg, crypto=crypto, pct=pct_eff)
            execute_buy(final["buy_symbol"], allocation, auto_trade, pending, label=f"ACQUISTO CIO {pct_eff:.0f}%", stop_pct=stop)
        else:
            sell_report = next(r for r in risk["positions"]
                               if core.normalize_symbol(r["pos"]["yf_symbol"]) == core.normalize_symbol(final["sell_symbol"]))
            if final["action"] == "SELL":
                execute_sell(sell_report["pos"], "DECISIONE CIO", final["reason"], auto_trade, pending, market_open)
            else:
                log_message(f"🔄 Rotazione capitale: {sell_report['pos']['symbol']} (score {sell_report['score']}) → "
                            f"{final['buy_symbol']}")
                rotate_capital(sell_report, final["buy_symbol"], cfg, auto_trade, pending, stop_pct=stop)
        core.save_state(state)

        # Badge per la dashboard
        m_s, m_c = macro["stock"], macro["crypto"]
        vetoes = [v["symbol"] for v in sentiment.values() if v["veto"]]
        t_sent = sentiment.get(target_key) if target else None
        t_vol = volume.get(target_key) if target else None
        fakes = [s for s, w in excluded if "falso breakout" in w]
        bot_state["boardroom"] = [
            badge("Macro", f"Azioni {m_s['regime']} · Crypto {m_c['regime']}",
                  "bad" if "RISK-OFF" in (m_s["regime"], m_c["regime"]) else "ok"),
            badge("Sentiment", (f"{target} {t_sent['sentiment']:+d}" if t_sent else "-")
                  + (f" · veto: {', '.join(vetoes)}" if vetoes else ""),
                  "bad" if vetoes else ("ok" if not t_sent or t_sent["sentiment"] >= 0 else "warn")),
            badge("Volumi", (f"{target} {t_vol['ratio']}x {t_vol['status']}" if t_vol and t_vol["ratio"] is not None else "-")
                  + (f" · falsi breakout: {', '.join(fakes)}" if fakes else ""),
                  "warn" if fakes else "ok"),
            badge("Drawdown", f"{drawdown['drawdown_pct']:+.2f}%" + (" · ACQUISTI BLOCCATI" if drawdown["blocked"] else ""),
                  "bad" if drawdown["blocked"] else ("warn" if drawdown["drawdown_pct"] < -2 else "ok")),
            badge("CIO", f"{describe_decision(final)} ({source})" + (f" · {exec_note}" if exec_note else ""),
                  {"BUY": "ok", "ROTATE": "warn", "SELL": "bad"}.get(final["action"], "neutral")),
        ]
        set_ai_analysis(
            symbol=target or "PORTAFOGLIO",
            rsi=str(target_info["ind"]["rsi"]) if target_info else "--",
            sentiment=short_text(t_sent["news"]) if t_sent else f"Esposizione ${risk['exposure']:,.0f} / capitale ${risk['equity']:,.0f}",
            ai_verdict=f"{describe_decision(final)} ({source})",
            reasoning=final["reason"] or decision["reason"],
        )

        bot_state["status"] = "Attivo (In attesa ciclo)" if bot_state["active"] else "In pausa"
        log_message("=== BOARDROOM COMPLETATO ===")

    finally:
        if bot_state["status"].startswith("Scansione"):
            bot_state["status"] = "In pausa" if not bot_state["active"] else "Attivo (In attesa ciclo)"
        # Rilascia sempre il lock alla fine della scansione
        scan_lock.release()

def background_loop():
    # Grace period: lascia stabilizzare server e connessioni API prima di toccare Alpaca
    time.sleep(core.STARTUP_GRACE_SECONDS)
    try:
        core.startup_system_sync(log=log_message)
    except Exception as e:
        log_message(f"🔄 [Sync] Errore sincronizzazione di avvio: {e}")
    last_run = 0.0
    boot = True  # il primo ciclo dopo l'avvio non apre posizioni
    while True:
        # L'intervallo viene riletto da config.json a ogni giro
        interval = core.get_config()["scan_interval_min"] * 60
        if bot_state["active"] and time.time() - last_run >= interval:
            last_run = time.time()
            try:
                run_trading_cycle(boot=boot)
                boot = False
            except Exception as e:
                log_message(f"Errore loop background: {e}")
        # Controlla ogni 30s; si risveglia subito se il bot viene riattivato
        if wake_event.wait(30):
            wake_event.clear()
            last_run = 0.0

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
    log_message(f"🧵 Thread di trading e Keep-Alive avviati (PID {os.getpid()})")
    cfg = core.get_config()
    mode = "Auto-Trading attivo" if cfg["auto_execute_trades"] else "Advisor (nessun ordine)"
    locked = core.env_overrides()
    source = (f"fissata da {core.ENV_OVERRIDES['auto_execute_trades']}" if "auto_execute_trades" in locked
              else "default/config.json (BOT_AUTO_EXECUTE non impostata)")
    log_message(f"⚙️ Modalità di avvio: {mode} — {source}")
    if locked:
        log_message(f"⚙️ Impostazioni fissate da variabili d'ambiente: "
                    f"{', '.join(f'{core.ENV_OVERRIDES[k]}={v}' for k, v in locked.items())}")
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

@app.route("/api/data")
@require_login
def api_data():
    with state_lock:
        bot = {
            "active": bot_state["active"],
            "last_scan": bot_state["last_scan"],
            "status": bot_state["status"],
            "logs": list(bot_state["logs"]),
            "latest_ai_analysis": dict(bot_state["latest_ai_analysis"]),
            "boardroom": list(bot_state["boardroom"]),
            "office": dict(bot_state["office"]),
        }
    return jsonify({
        "account": cached("account", get_account_summary),
        "positions": cached("positions", get_open_positions),
        "bot": bot,
        "sources": {
            "yfinance": "Yahoo Finance API (News & Historical)",
            "alpaca": "Alpaca Paper Trading v2 API",
            "ai": "Google Gemini / Groq Llama 3.3 + motore quantitativo di riserva",
            "ta": "Indicatori Tecnici RSI(14) e SMA"
        }
    })

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
        return jsonify({"status": "warning", "message": "Scansione già in corso!"})

    log_message("⚡ Avvio manuale scansione da Dashboard Web...")
    threading.Thread(target=run_trading_cycle, kwargs={"manual": True}, daemon=True).start()
    return jsonify({"status": "success", "message": "Scansione avviata con successo"})

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

    positions = get_open_positions()
    if not positions:
        return jsonify({"status": "warning", "message": "Nessuna posizione aperta da liquidare."})

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
            core.close_position(sym)
            log_message(f"🚨 LIQUIDAZIONE MANUALE: Vendita {qty} x {sym}")
            count += 1
        except Exception as e:
            log_message(f"Errore vendita manuale {sym}: {e}")

    with _cache_lock:
        _cache.clear()
    return jsonify({"status": "success", "message": f"Liquidazione inviata: {count}/{len(positions)} posizioni in chiusura."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
