import os
import time
import threading
import datetime
import dotenv
import pandas as pd
import yfinance as yf
import ta
from flask import Flask, jsonify, render_template, request
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

dotenv.load_dotenv()

ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

alpaca_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True) if ALPACA_KEY else None

WATCHLIST = ["BTC-USD", "ETH-USD", "SOL-USD", "NVDA", "AAPL", "TSLA", "MSFT", "AMD"]

# Aggiunto Lock per impedire scansioni multiple simultanee
scan_lock = threading.Lock()

bot_state = {
    "active": True,
    "last_scan": "In attesa del primo scan...",
    "status": "Inizializzato",
    "logs": [],
    "latest_ai_analysis": {
        "symbol": "INIZIALIZZO...",
        "rsi": "--",
        "sentiment": "Premi SCAN ORA per avviare",
        "ai_verdict": "IN ATTESA",
        "reasoning": "Il bot sta attendendo il primo ciclo di scansione dei mercati."
    }
}

def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    bot_state["logs"].insert(0, entry)
    if len(bot_state["logs"]) > 60:
        bot_state["logs"].pop()

def get_account_summary():
    if not alpaca_client:
        return {"cash": 0, "portfolio": 0, "buying_power": 0}
    try:
        acc = alpaca_client.get_account()
        return {
            "cash": float(acc.cash),
            "portfolio": float(acc.portfolio_value),
            "buying_power": float(acc.buying_power)
        }
    except Exception as e:
        log_message(f"Errore lettura account: {e}")
        return {"cash": 0, "portfolio": 0, "buying_power": 0}

def get_open_positions():
    if not alpaca_client:
        return []
    try:
        positions = alpaca_client.get_all_positions()
        res = []
        for p in positions:
            res.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "side": getattr(p, 'side', 'long').upper()
            })
        return res
    except Exception as e:
        log_message(f"Errore recupero posizioni: {e}")
        return []

def get_recent_news(ticker):
    """Recupera le ultime notizie per un asset tramite yfinance."""
    try:
        t = yf.Ticker(ticker)
        news = t.news
        if news:
            titles = [item.get('title', '') for item in news[:3] if item.get('title')]
            if titles:
                return " | ".join(titles)
    except Exception:
        pass
    return "Nessuna notizia rilevante recente."

def query_gemini_ai(prompt):
    if not GEMINI_KEY:
        log_message("⚠️ GEMINI_API_KEY non trovata.")
        return "DECISIONE: HOLD | MOTIVO: API Key non configurata"

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_KEY)
        for m in ['gemini-2.0-flash', 'gemini-1.5-flash']:
            try:
                res = client.models.generate_content(model=m, contents=prompt)
                if res and res.text:
                    return res.text
            except Exception:
                continue
    except Exception as e:
        log_message(f"Errore chiamata Gemini: {e}")

    return "DECISIONE: HOLD | MOTIVO: Risposta fallback per errore API"

def run_trading_cycle():
    # Verifica che non ci sia un'altra scansione in corso
    if not scan_lock.acquire(blocking=False):
        log_message("⚠️ Scansione già in corso. Attendi il completamento.")
        return

    try:
        bot_state["status"] = "Scansione & Valutazione in corso..."
        bot_state["last_scan"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message("=== AVVIO SCANSIONE MERCATO & PORTAFOGLIO ===")

        # ---------------------------------------------------------
        # 1. VALUTAZIONE PREDITTIVA DI VENDITA SULLE POSIZIONI APERTE
        # ---------------------------------------------------------
        open_positions = get_open_positions()
        for pos in open_positions:
            sym = pos["symbol"]
            qty = pos["qty"]
            unrealized_pl = pos["unrealized_pl"]
            mkt_val = pos["market_value"]
            pl_percent = (unrealized_pl / (mkt_val - unrealized_pl)) * 100 if mkt_val != unrealized_pl else 0

            # Aggiornamento intermedio per interfaccia grafica
            bot_state["latest_ai_analysis"] = {
                "symbol": sym,
                "rsi": "Calcolo...",
                "sentiment": "Recupero news...",
                "ai_verdict": "VALUTAZIONE VENDITA",
                "reasoning": f"Analisi del rischio in corso per la posizione aperta su {sym}..."
            }

            news_summary = get_recent_news(sym)
            rsi_val = "N/A"
            try:
                df = yf.Ticker(sym).history(period="1mo", interval="1h")
                if len(df) >= 20:
                    rsi_val = round(float(ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1]), 2)
            except Exception:
                pass

            log_message(f"Verifica Posizione {sym}: PnL ${unrealized_pl:.2f} ({pl_percent:.2f}%) | RSI: {rsi_val}")

            prompt = f"""
            Sei un agente di risk management per un bot quantitativo.
            Analizza la posizione aperta per l'asset {sym}:
            - Quantità detenuta: {qty}
            - Valore di mercato attuale: ${mkt_val:.2f}
            - Profit/Loss attuale: ${unrealized_pl:.2f} ({pl_percent:.2f}%)
            - RSI (1h): {rsi_val}
            - Ultime notizie/headlines sul titolo: "{news_summary}"

            Valuta se esistono rischi imminenti di ribasso, perdita di momentum o se le notizie indicano un sentiment negativo.
            Devi decidere se VENDERE SUBITO per proteggere il capitale o incassare il profitto, oppure MANTENERE.
            
            Rispondi includendo 'DECISIONE: SELL' oppure 'DECISIONE: HOLD' seguiti da una breve motivazione.
            """

            log_message(f"Interrogazione Gemini per vendita {sym}...")
            ai_res = query_gemini_ai(prompt)
            should_sell = "SELL" in ai_res.upper()
            
            # Aggiorna monitoraggio IA con il verdetto finale
            bot_state["latest_ai_analysis"] = {
                "symbol": sym,
                "rsi": str(rsi_val),
                "sentiment": news_summary[:80] + "..." if len(news_summary) > 80 else news_summary,
                "ai_verdict": "SELL (Vendita)" if should_sell else "HOLD (Mantiene)",
                "reasoning": ai_res
            }
            
            if pl_percent <= -5.0:
                should_sell = True
                ai_res = "Stop Loss di sicurezza estrema (-5%)"

            if should_sell:
                try:
                    log_message(f"🚨 VENDITA PREDITTIVA {sym} ({qty} quote): {ai_res}")
                    order_data = MarketOrderRequest(
                        symbol=sym,
                        qty=qty,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.GTC
                    )
                    order = alpaca_client.submit_order(order_data)
                    log_message(f"ORDINE VENDITA ESEGUITO: {sym} (ID: {order.id})")
                except Exception as e:
                    log_message(f"Errore Vendita {sym}: {e}")

        # ---------------------------------------------------------
        # 2. SCANSIONE E ACQUISTO NUOVE OPPORTUNITÀ (BUY)
        # ---------------------------------------------------------
        log_message("Avvio scansione Watchlist per nuove opportunità...")
        candidates = []
        for ticker in WATCHLIST:
            try:
                df = yf.Ticker(ticker).history(period="1mo", interval="1h")
                if len(df) >= 20:
                    rsi = float(ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1])
                    price = float(df['Close'].iloc[-1])
                    score = 50 + (30 if rsi < 45 else -20 if rsi > 70 else 0)
                    candidates.append({"symbol": ticker, "price": price, "rsi": round(rsi, 2), "score": score})
            except Exception:
                continue

        candidates.sort(key=lambda x: x['score'], reverse=True)
        top_3 = candidates[:3]
        log_message(f"Asset selezionati per analisi BUY: {[c['symbol'] for c in top_3]}")

        acc = get_account_summary()
        if acc["cash"] < 10:
            log_message("Liquidità Cash insufficiente (< $10) per nuovi acquisti.")
        else:
            for asset in top_3:
                # Aggiornamento intermedio per interfaccia grafica
                bot_state["latest_ai_analysis"] = {
                    "symbol": asset['symbol'],
                    "rsi": str(asset['rsi']),
                    "sentiment": "Download notizie in corso...",
                    "ai_verdict": "VALUTAZIONE ACQUISTO",
                    "reasoning": f"Analisi ingresso mercato per {asset['symbol']}..."
                }

                news = get_recent_news(asset['symbol'])
                log_message(f"Analisi AI in corso per {asset['symbol']} (${asset['price']:.2f})...")
                
                prompt = f"Analizza {asset['symbol']}: Prezzo ${asset['price']:.2f}, RSI {asset['rsi']}. Notizie: '{news}'. Rispondi 'DECISIONE: BUY' se reputi opportuno acquistare oppure 'DECISIONE: HOLD'."
                ai_res = query_gemini_ai(prompt)

                is_buy = "BUY" in ai_res.upper()

                # Aggiorna monitoraggio IA con il verdetto
                bot_state["latest_ai_analysis"] = {
                    "symbol": asset['symbol'],
                    "rsi": str(asset['rsi']),
                    "sentiment": news[:80] + "..." if len(news) > 80 else news,
                    "ai_verdict": "BUY (Acquisto)" if is_buy else "HOLD (Monitora)",
                    "reasoning": ai_res
                }

                if is_buy:
                    allocation = acc["cash"] * 0.15
                    if allocation >= 10:
                        qty = max(1, int(allocation / asset['price']))
                        sym = asset['symbol'].replace("-", "")
                        try:
                            order_data = MarketOrderRequest(
                                symbol=sym,
                                qty=qty,
                                side=OrderSide.BUY,
                                time_in_force=TimeInForce.GTC
                            )
                            order = alpaca_client.submit_order(order_data)
                            log_message(f"ORDINE ESEGUITO ACQUISTO: {qty} x {sym} (ID: {order.id})")
                        except Exception as e:
                            log_message(f"Errore Ordine Acquisto {sym}: {e}")

        bot_state["status"] = "Attivo (In attesa ciclo)"
        log_message("=== SCANSIONE COMPLETATA ===")
        
    finally:
        # Rilascia sempre il lock alla fine della scansione
        scan_lock.release()

def background_loop():
    time.sleep(3) # Pausa di 3 secondi all'avvio per caricamento server
    while True:
        if bot_state["active"]:
            try:
                run_trading_cycle()
            except Exception as e:
                log_message(f"Errore loop background: {e}")
        time.sleep(900)

app = Flask(__name__)

if not hasattr(app, 'bot_started'):
    app.bot_started = True
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ping")
def ping():
    return jsonify({"status": "alive", "timestamp": datetime.datetime.now().isoformat()}), 200

@app.route("/api/data")
def api_data():
    return jsonify({
        "account": get_account_summary(),
        "positions": get_open_positions(),
        "bot": bot_state,
        "sources": {
            "yfinance": "Yahoo Finance API (News & Historical)",
            "alpaca": "Alpaca Paper Trading v2 API",
            "gemini": "Google Gemini AI (Modello Decisionale)",
            "ta": "Indicatori Tecnici RSI(14) e SMA"
        }
    })

@app.route("/api/scan", methods=["POST"])
@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    if scan_lock.locked():
        return jsonify({"status": "warning", "message": "Scansione già in corso!"})
        
    log_message("⚡ Avvio manuale scansione da Dashboard Web...")
    threading.Thread(target=run_trading_cycle, daemon=True).start()
    return jsonify({"status": "success", "message": "Scansione avviata con successo"})

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    bot_state["active"] = not bot_state["active"]
    log_message(f"Stato Bot impostato a: Active={bot_state['active']}")
    return jsonify({"active": bot_state["active"], "is_running": bot_state["active"]})

@app.route("/api/liquidate", methods=["POST"])
def api_liquidate():
    positions = get_open_positions()
    if not positions:
        return jsonify({"status": "warning", "message": "Nessuna posizione aperta da liquidare."})

    count = 0
    for pos in positions:
        sym = pos["symbol"]
        qty = pos["qty"]
        try:
            order_data = MarketOrderRequest(
                symbol=sym,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC
            )
            alpaca_client.submit_order(order_data)
            log_message(f"🚨 LIQUIDAZIONE MANUALE: Vendita {qty} x {sym}")
            count += 1
        except Exception as e:
            log_message(f"Errore vendita manuale {sym}: {e}")

    return jsonify({"status": "success", "message": f"Liquidazione completata. Chiusi {count} ordini."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)