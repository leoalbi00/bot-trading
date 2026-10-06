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
    "latest_ai_analysis": {
        "symbol": "INIZIALIZZO...",
        "rsi": "--",
        "sentiment": "Premi SCAN ORA per avviare",
        "ai_verdict": "IN ATTESA",
        "reasoning": "Il bot sta attendendo il primo ciclo di scansione dei mercati."
    }
}

def log_message(msg):
    now = datetime.datetime.now()
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
            "non_marginable_buying_power": float(acc.non_marginable_buying_power or 0)
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

def execute_buy(sym, amount, auto_trade, pending, label="ACQUISTO"):
    """Acquisto a importo (notional) o segnalazione in modalità Advisor. Restituisce l'ordine o None."""
    if not auto_trade:
        log_message(f"🧭 [Advisor] Suggerito {label} di ${amount:,.2f} di {sym}: ordine non inviato.")
        return None
    if not alpaca_client:
        return None
    try:
        order = core.submit_notional_buy(sym, amount)
        pending.add(core.normalize_symbol(sym))
        log_message(f"✅ ORDINE {label} INVIATO: ${amount:,.2f} di {sym} (ID: {order.id})")
        return order
    except Exception as e:
        log_message(f"Errore Ordine Acquisto {sym}: {e}")
        return None

def rotate_capital(sell_report, target, cfg, auto_trade, pending):
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
    execute_buy(target, amount, auto_trade, pending, label="ACQUISTO DA ROTAZIONE")

def describe_decision(d):
    if d["action"] == "ROTATE":
        return f"ROTATE {d['sell_symbol']} → {d['buy_symbol']}"
    if d["action"] == "BUY":
        return f"BUY {d['buy_symbol']}"
    if d["action"] == "SELL":
        return f"SELL {d['sell_symbol']}"
    return "HOLD"

def run_trading_cycle(manual=False):
    # Verifica che non ci sia un'altra scansione in corso
    if not scan_lock.acquire(blocking=False):
        log_message("⚠️ Scansione già in corso. Attendi il completamento.")
        return

    try:
        bot_state["status"] = "Scansione & Valutazione in corso..."
        bot_state["last_scan"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message("=== AVVIO CICLO DESK MULTI-AGENTE ===")

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

        # ---------------- FASE 1: ANALISTA DI MERCATO ----------------
        log_message("━━━ FASE 1 · ANALISTA DI MERCATO ━━━")
        set_ai_analysis(symbol="DESK", rsi="--", sentiment="Fase 1: Analista di mercato",
                        ai_verdict="ANALISI IN CORSO", reasoning="Calcolo di RSI, MACD, ROC, SMA20/50 e Score di Forza...")
        analysis = core.market_analyst(cfg["watchlist"] + [p["yf_symbol"] for p in positions], log=log_message)
        if not manual and should_abort():
            return

        # ---------------- FASE 2: RISK MANAGER ----------------
        log_message("━━━ FASE 2 · RISK MANAGER ━━━")
        risk = core.risk_manager(positions, analysis, acc, cfg, log=log_message)

        # ---------------- FASE 3: PORTFOLIO BROKER ----------------
        log_message("━━━ FASE 3 · PORTFOLIO BROKER ━━━")
        sold = set()
        for r in risk["positions"]:
            if r["status"] not in ("STOP_LOSS", "RIBASSISTA", "STALLO"):
                continue
            pos = r["pos"]
            key = core.normalize_symbol(pos["symbol"])
            if not orders_allowed or key in pending:
                log_message(f"💼 [Broker] {pos['symbol']}: vendita ({r['status']}) rimandata, ordine già pendente.")
                continue
            log_message(f"💼 [Broker] SELL obbligatorio {pos['symbol']} ({r['status']}): {r['reason']}")
            if execute_sell(pos, r["status"].replace("_", " "), r["reason"], auto_trade, pending, market_open) or not auto_trade:
                sold.add(key)

        held_keys = {core.normalize_symbol(p["yf_symbol"]) for p in positions}
        candidates = core.broker_candidates(analysis, held_keys, pending, market_open)
        if not market_open:
            log_message("Mercato azionario chiuso: solo crypto tra i candidati all'acquisto.")
        news = {a["symbol"]: core.get_recent_news(a["symbol"]) for a in candidates[:3]}

        prompt = core.build_broker_prompt(risk, candidates, cfg, news)
        decision, source = core.ask_broker_ai(prompt, log=log_message)
        if not decision:
            log_message("🧮 Nessuna IA disponibile: decide il Broker quantitativo di riserva.")
            decision, source = core.ta_broker(risk, candidates), "Quant"
        log_message(f"💼 [Broker] Proposta ({source}): {describe_decision(decision)} — {core.summarize_reason(decision['reason'], 220)}")

        final = core.validate_broker_decision(decision, risk, candidates, sold_keys=sold | pending, log=log_message)
        if describe_decision(final) != describe_decision(decision):
            log_message(f"💼 [Broker] Decisione finale: {describe_decision(final)} — {final['reason']}")

        target = final["buy_symbol"] or final["sell_symbol"]
        target_info = analysis.get(core.normalize_symbol(target)) if target else None
        set_ai_analysis(
            symbol=target or "PORTAFOGLIO",
            rsi=str(target_info["ind"]["rsi"]) if target_info else "--",
            sentiment=short_text(f"Esposizione ${risk['exposure']:,.0f} / capitale ${risk['equity']:,.0f}"),
            ai_verdict=f"{describe_decision(final)} ({source})",
            reasoning=final["reason"] or decision["reason"],
        )

        if not orders_allowed or final["action"] == "HOLD":
            pass
        elif final["action"] == "BUY":
            crypto = core.is_crypto(final["buy_symbol"])
            buy_info = analysis.get(core.normalize_symbol(final["buy_symbol"]))
            score = final.get("score") if final.get("score") is not None else (buy_info["score"] if buy_info else None)
            pct = core.allocation_pct_for_score(score, cfg)
            _, allocation = core.buy_budget(acc, risk["exposure"], cfg, crypto=crypto, score=score)
            label = "STRONG BUY" if score is not None and score >= core.STRONG_BUY_SCORE else "BUY"
            log_message(f"💼 [Broker] {label} {final['buy_symbol']}: score {score} → allocazione {pct:.1f}% del capitale (${allocation:,.2f})")
            execute_buy(final["buy_symbol"], allocation, auto_trade, pending, label=f"ACQUISTO {label}")
        else:
            sell_report = next(r for r in risk["positions"]
                               if core.normalize_symbol(r["pos"]["yf_symbol"]) == core.normalize_symbol(final["sell_symbol"]))
            if final["action"] == "SELL":
                execute_sell(sell_report["pos"], "DECISIONE BROKER", final["reason"], auto_trade, pending, market_open)
            else:
                log_message(f"🔄 Rotazione capitale: {sell_report['pos']['symbol']} (score {sell_report['score']}) → "
                            f"{final['buy_symbol']}")
                rotate_capital(sell_report, final["buy_symbol"], cfg, auto_trade, pending)

        bot_state["status"] = "Attivo (In attesa ciclo)" if bot_state["active"] else "In pausa"
        log_message("=== CICLO COMPLETATO ===")

    finally:
        if bot_state["status"].startswith("Scansione"):
            bot_state["status"] = "In pausa" if not bot_state["active"] else "Attivo (In attesa ciclo)"
        # Rilascia sempre il lock alla fine della scansione
        scan_lock.release()

def background_loop():
    time.sleep(3)  # Pausa di 3 secondi all'avvio per caricamento server
    last_run = 0.0
    while True:
        # L'intervallo viene riletto da config.json a ogni giro
        interval = core.get_config()["scan_interval_min"] * 60
        if bot_state["active"] and time.time() - last_run >= interval:
            last_run = time.time()
            try:
                run_trading_cycle()
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
    mode = "Auto-Trading attivo" if core.get_config()["auto_execute_trades"] else "Advisor (nessun ordine)"
    log_message(f"⚙️ Modalità di avvio: {mode} — BOT_AUTO_EXECUTE={os.getenv('BOT_AUTO_EXECUTE', 'non impostata (default true)')}")

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
    return jsonify({"status": "alive", "timestamp": datetime.datetime.now().isoformat()}), 200

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
