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

bot_state = {
    "active": True,
    "last_scan": "In attesa di primo scan...",
    "status": "Inizializzato",
    "logs": []
}

def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    bot_state["logs"].insert(0, entry)
    if len(bot_state["logs"]) > 50:
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
                "unrealized_pl": float(p.unrealized_pl)
            })
        return res
    except Exception as e:
        log_message(f"Errore recupero posizioni: {e}")
        return []

def query_gemini_ai(prompt):
    if not GEMINI_KEY:
        return "DECISIONE: BUY | MOTIVO: Test modalità fallback"

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
    except Exception:
        pass

    return "DECISIONE: HOLD | MOTIVO: Analisi tecnica in fase neutrale."

def run_trading_cycle():
    bot_state["status"] = "Scansione & Valutazione..."
    bot_state["last_scan"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message("=== AVVIO SCANSIONE MERCATO & PORTAFOGLIO ===")

    # ---------------------------------------------------------
    # 1. GESTIONE E VENDITA DELLE POSIZIONI APERTE (TAKE PROFIT / STOP LOSS / SELL AI)
    # ---------------------------------------------------------
    open_positions = get_open_positions()
    for pos in open_positions:
        sym = pos["symbol"]
        qty = pos["qty"]
        unrealized_pl = pos["unrealized_pl"]
        mkt_val = pos["market_value"]
        pl_percent = (unrealized_pl / (mkt_val - unrealized_pl)) * 100 if mkt_val != unrealized_pl else 0

        log_message(f"Verifica Posizione {sym}: Qty {qty} | PnL: ${unrealized_pl:.2f} ({pl_percent:.2f}%)")

        # Regola di Take Profit (+3%) o Stop Loss (-2%)
        should_sell = False
        reason = ""

        if pl_percent >= 3.0:
            should_sell = True
            reason = f"Take Profit raggiunto (+{pl_percent:.2f}%)"
        elif pl_percent <= -2.0:
            should_sell = True
            reason = f"Stop Loss attivato ({pl_percent:.2f}%)"
        else:
            prompt = f"Posizione aperta: {sym}, Qty: {qty}, PnL %: {pl_percent:.2f}%. Rispondi SELL se consigli di chiudere la posizione, altrimenti HOLD."
            ai_res = query_gemini_ai(prompt)
            if "SELL" in ai_res.upper():
                should_sell = True
                reason = "Segnale di vendita espresso dall'AI Gemini"

        if should_sell:
            try:
                log_message(f"EXEC VENDITA {sym} ({qty} quote): {reason}")
                order_data = MarketOrderRequest(
                    symbol=sym,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC
                )
                order = alpaca_client.submit_order(order_data)
                log_message(f"ORDINE DI VENDITA ESEGUITO: {sym} (ID: {order.id})")
            except Exception as e:
                log_message(f"Errore Vendita {sym}: {e}")

    # ---------------------------------------------------------
    # 2. SCANSIONE E ACQUISTO NUOVE OPPORTUNITÀ (BUY)
    # ---------------------------------------------------------
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
            log_message(f"Analisi AI per {asset['symbol']} (${asset['price']:.2f})...")
            prompt = f"Analizza {asset['symbol']}: Prezzo ${asset['price']:.2f}, RSI {asset['rsi']}. Rispondi BUY se reputi opportuno acquistare."
            ai_res = query_gemini_ai(prompt)

            if "BUY" in ai_res.upper() or asset['score'] >= 65:
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

def background_loop():
    while True:
        if bot_state["active"]:
            try:
                run_trading_cycle()
            except Exception as e:
                log_message(f"Errore loop background: {e}")
        time.sleep(900)

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def api_data():
    return jsonify({
        "account": get_account_summary(),
        "positions": get_open_positions(),
        "bot": bot_state
    })

@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    threading.Thread(target=run_trading_cycle).start()
    return jsonify({"status": "Scan avviato"})

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    bot_state["active"] = not bot_state["active"]
    log_message(f"Stato Bot impostato a: Active={bot_state['active']}")
    return jsonify({"active": bot_state["active"]})

if __name__ == "__main__":
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)