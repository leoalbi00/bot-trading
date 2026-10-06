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
    "logs": deque(maxlen=60),  # ordine cronologico: il più recente è in fondo
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

def run_trading_cycle(manual=False):
    # Verifica che non ci sia un'altra scansione in corso
    if not scan_lock.acquire(blocking=False):
        log_message("⚠️ Scansione già in corso. Attendi il completamento.")
        return

    try:
        bot_state["status"] = "Scansione & Valutazione in corso..."
        bot_state["last_scan"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message("=== AVVIO SCANSIONE MERCATO & PORTAFOGLIO ===")

        cfg = core.get_config()
        auto_trade = cfg["auto_execute_trades"]
        if not auto_trade:
            log_message("🧭 Modalità Advisor: le decisioni vengono solo registrate, nessun ordine inviato.")

        if not alpaca_client:
            log_message("⚠️ Credenziali Alpaca non configurate: nessun ordine verrà inviato.")

        # Ordini già aperti: evitano duplicati e accumuli a mercato chiuso
        pending = core.get_pending_order_symbols(log=log_message)
        if pending is None:
            log_message("⚠️ Stato ordini pendenti sconosciuto: salto l'invio di ordini in questo ciclo.")
        elif pending:
            log_message(f"Ordini pendenti su: {sorted(pending)}")
        market_open = core.is_market_open(log=log_message)

        # ---------------------------------------------------------
        # 1. VALUTAZIONE PREDITTIVA DI VENDITA SULLE POSIZIONI APERTE
        # ---------------------------------------------------------
        open_positions = get_open_positions()
        held = {core.normalize_symbol(p["symbol"]) for p in open_positions}

        for pos in open_positions:
            if not manual and should_abort():
                return
            sym = pos["symbol"]
            yf_sym = pos["yf_symbol"]
            qty = pos["qty"]
            unrealized_pl = pos["unrealized_pl"]
            mkt_val = pos["market_value"]
            pl_percent = pos["unrealized_plpc"]

            if pending is None or core.normalize_symbol(sym) in pending:
                log_message(f"{sym}: ordine già pendente o stato ordini ignoto, salto la valutazione di vendita.")
                continue

            set_ai_analysis(
                symbol=sym,
                rsi="Calcolo...",
                sentiment="Recupero news...",
                ai_verdict="VALUTAZIONE VENDITA",
                reasoning=f"Analisi del rischio in corso per la posizione aperta su {sym}..."
            )

            news_summary = core.get_recent_news(yf_sym)
            rsi, _ = core.get_rsi_and_price(yf_sym)
            rsi_val = rsi if rsi is not None else "N/A"

            log_message(f"Verifica Posizione {sym}: PnL ${unrealized_pl:.2f} ({pl_percent:.2f}%) | RSI: {rsi_val}")

            if pl_percent <= cfg["stop_loss_pct"]:
                # Lo stop loss ha la precedenza: nessuna chiamata IA
                decision = "SELL"
                ai_res = f"Stop Loss di sicurezza ({cfg['stop_loss_pct']:.1f}%) raggiunto: PnL {pl_percent:.2f}%"
                verdict = "SELL (Stop Loss)"
            else:
                prompt = f"""
                Sei un agente di risk management per un bot quantitativo.
                Analizza la posizione aperta per l'asset {yf_sym}:
                - Quantità detenuta: {qty}
                - Valore di mercato attuale: ${mkt_val:.2f}
                - Profit/Loss attuale: ${unrealized_pl:.2f} ({pl_percent:.2f}%)
                - RSI (1h): {rsi_val}
                - Ultime notizie/headlines sul titolo: "{news_summary}"

                Valuta se esistono rischi imminenti di ribasso, perdita di momentum o se le notizie indicano un sentiment negativo.
                Devi decidere se VENDERE SUBITO per proteggere il capitale o incassare il profitto, oppure MANTENERE.

                Inizia la risposta con esattamente 'DECISIONE: SELL' oppure 'DECISIONE: HOLD', seguito da una breve motivazione.
                """
                log_message(f"Interrogazione Gemini per vendita {sym}...")
                ai_res = core.query_ai(prompt, log=log_message, symbol=yf_sym)
                decision = core.parse_decision(ai_res, allowed=("SELL", "HOLD"))
                verdict = "SELL (Vendita)" if decision == "SELL" else "HOLD (Mantiene)"

            set_ai_analysis(
                symbol=sym,
                rsi=str(rsi_val),
                sentiment=short_text(news_summary),
                ai_verdict=verdict,
                reasoning=ai_res
            )

            if decision == "SELL" and not auto_trade:
                log_message(f"🧭 [Advisor] Suggerita VENDITA di {sym} ({qty} quote): ordine non inviato.")
            elif decision == "SELL" and alpaca_client:
                try:
                    log_message(f"🚨 VENDITA PREDITTIVA {sym} ({qty} quote): {ai_res}")
                    order = core.close_position(sym)
                    pending.add(core.normalize_symbol(sym))
                    note = "" if market_open or pos["is_crypto"] else " (mercato chiuso: eseguito all'apertura)"
                    log_message(f"ORDINE VENDITA INVIATO: {sym} (ID: {order.id}){note}")
                except Exception as e:
                    log_message(f"Errore Vendita {sym}: {e}")

        # ---------------------------------------------------------
        # 2. SCANSIONE E ACQUISTO NUOVE OPPORTUNITÀ (BUY)
        # ---------------------------------------------------------
        log_message("Avvio scansione Watchlist per nuove opportunità...")
        candidates = []
        for ticker in cfg["watchlist"]:
            rsi, price = core.get_rsi_and_price(ticker)
            if rsi is None:
                continue
            score = 50 + (30 if rsi < 45 else -20 if rsi > 70 else 0)
            candidates.append({"symbol": ticker, "price": price, "rsi": rsi, "score": score})

        candidates.sort(key=lambda x: x['score'], reverse=True)
        top_3 = candidates[:3]
        log_message(f"Asset selezionati per analisi BUY: {[c['symbol'] for c in top_3]}")

        acc = get_account_summary()
        funds = max(core.available_funds(acc), core.available_funds(acc, crypto=True))
        if funds <= core.MIN_ORDER_USD:
            log_message(f"[Trading] Liquidità disponibile insufficiente per nuovi acquisti (${funds:,.2f})")
        else:
            for asset in top_3:
                if not manual and should_abort():
                    return
                sym = asset['symbol']
                key = core.normalize_symbol(sym)
                if key in held:
                    log_message(f"{sym}: posizione già aperta, nessun nuovo acquisto.")
                    continue
                if pending is None or key in pending:
                    log_message(f"{sym}: ordine già pendente o stato ordini ignoto, salto.")
                    continue
                if not core.is_crypto(sym) and not market_open:
                    log_message(f"{sym}: mercato azionario chiuso, nessun ordine accodato.")
                    continue
                allocation = core.available_funds(acc, crypto=core.is_crypto(sym)) * cfg["max_allocation_pct"] / 100
                if allocation < core.MIN_ORDER_USD:
                    log_message(f"[Trading] {sym}: budget ${allocation:,.2f} sotto il minimo di ${core.MIN_ORDER_USD:.0f}, salto.")
                    continue

                set_ai_analysis(
                    symbol=sym,
                    rsi=str(asset['rsi']),
                    sentiment="Download notizie in corso...",
                    ai_verdict="VALUTAZIONE ACQUISTO",
                    reasoning=f"Analisi ingresso mercato per {sym}..."
                )

                news = core.get_recent_news(sym)
                log_message(f"Analisi AI in corso per {sym} (${asset['price']:.2f})...")

                prompt = (
                    f"Analizza {sym}: Prezzo ${asset['price']:.2f}, RSI {asset['rsi']}. Notizie: '{news}'. "
                    f"Inizia la risposta con esattamente 'DECISIONE: BUY' se reputi opportuno acquistare "
                    f"oppure 'DECISIONE: HOLD', seguito da una breve motivazione."
                )
                ai_res = core.query_ai(prompt, log=log_message, symbol=sym)
                is_buy = core.parse_decision(ai_res, allowed=("BUY", "HOLD")) == "BUY"

                set_ai_analysis(
                    symbol=sym,
                    rsi=str(asset['rsi']),
                    sentiment=short_text(news),
                    ai_verdict="BUY (Acquisto)" if is_buy else "HOLD (Monitora)",
                    reasoning=ai_res
                )

                if is_buy and not auto_trade:
                    log_message(f"🧭 [Advisor] Suggerito ACQUISTO di ${allocation:.2f} di {sym}: ordine non inviato.")
                elif is_buy and alpaca_client:
                    try:
                        order = core.submit_notional_buy(sym, allocation)
                        pending.add(key)
                        log_message(f"ORDINE ACQUISTO INVIATO: ${allocation:.2f} di {sym} (ID: {order.id})")
                    except Exception as e:
                        log_message(f"Errore Ordine Acquisto {sym}: {e}")

        bot_state["status"] = "Attivo (In attesa ciclo)" if bot_state["active"] else "In pausa"
        log_message("=== SCANSIONE COMPLETATA ===")

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
