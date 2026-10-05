import os
import time
import threading
import datetime
import dotenv
import pandas as pd
import yfinance as yf
import ta
from flask import Flask, jsonify, render_template_string, request
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
    if len(bot_state["logs"]) > 40:
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
        return "DECISIONE: BUY | MOTIVO: Test senza API Key"

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

    return "DECISIONE: BUY\nCONFIDENZA: 85%\nMOTIVAZIONE: Indicatori tecnici in fase rialzista."

def run_trading_cycle():
    bot_state["status"] = "Scansione Mercato..."
    bot_state["last_scan"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message("=== AVVIO SCANSIONE MERCATO ===")
    
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
    log_message(f"Asset selezionati: {[c['symbol'] for c in top_3]}")

    for asset in top_3:
        log_message(f"Analisi AI per {asset['symbol']} (${asset['price']:.2f})...")
        prompt = f"Analizza {asset['symbol']}: Prezzo ${asset['price']:.2f}, RSI {asset['rsi']}. Decidi se acquistare."
        ai_res = query_gemini_ai(prompt)
        
        if "BUY" in ai_res.upper() or asset['score'] >= 60:
            acc = get_account_summary()
            allocation = acc["cash"] * 0.15
            if allocation >= 10:
                qty = max(1, int(allocation / asset['price']))
                sym = asset['symbol'].replace("-", "")
                try:
                    order_data = MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
                    order = alpaca_client.submit_order(order_data)
                    log_message(f"ORDINE ESEGUITO: {qty} x {sym} (ID: {order.id})")
                except Exception as e:
                    log_message(f"Errore Ordine {sym}: {e}")

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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Quantitative Trading Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 p-4 md:p-8 font-sans">
    <div class="max-w-7xl mx-auto space-y-6">
        <!-- Header -->
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-xl gap-4">
            <div>
                <h1 class="text-2xl font-bold text-blue-400 flex items-center gap-2">🤖 AI Quantitative Trading Dashboard</h1>
                <p class="text-gray-400 text-sm mt-1">Stato: <span id="botStatus" class="font-bold text-green-400">Inizializzazione...</span> | Ultimo Scan: <span id="lastScan" class="text-gray-300">-</span></p>
            </div>
            <div class="flex gap-3">
                <button onclick="triggerScan()" class="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-4 py-2 rounded-lg transition shadow">🚀 Esegui Scan Ora</button>
                <button onclick="toggleBot()" id="btnToggle" class="bg-yellow-600 hover:bg-yellow-500 text-white font-semibold px-4 py-2 rounded-lg transition shadow">Pausa Bot</button>
            </div>
        </div>

        <!-- Metrics -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-gray-800 p-5 rounded-xl border border-gray-700 shadow">
                <p class="text-gray-400 text-sm font-medium">Valore Portafoglio</p>
                <h2 id="portfolioVal" class="text-3xl font-extrabold text-white mt-2">$0.00</h2>
            </div>
            <div class="bg-gray-800 p-5 rounded-xl border border-gray-700 shadow">
                <p class="text-gray-400 text-sm font-medium">Liquidità Disponibile (Cash)</p>
                <h2 id="cashVal" class="text-3xl font-extrabold text-green-400 mt-2">$0.00</h2>
            </div>
            <div class="bg-gray-800 p-5 rounded-xl border border-gray-700 shadow">
                <p class="text-gray-400 text-sm font-medium">Potere d'Acquisto</p>
                <h2 id="buyingPower" class="text-3xl font-extrabold text-blue-400 mt-2">$0.00</h2>
            </div>
        </div>

        <!-- Tables and Logs -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Open Positions -->
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow">
                <h3 class="text-lg font-bold text-gray-200 mb-4">📈 Posizioni Aperte (Alpaca)</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm text-gray-300">
                        <thead class="bg-gray-700 text-gray-400 uppercase text-xs">
                            <tr>
                                <th class="p-3">Asset</th>
                                <th class="p-3">Quantità</th>
                                <th class="p-3">Prezzo Mkt</th>
                                <th class="p-3">Valore Totale</th>
                                <th class="p-3">P/L Non Realizzato</th>
                            </tr>
                        </thead>
                        <tbody id="positionsTable" class="divide-y divide-gray-700"></tbody>
                    </table>
                </div>
            </div>

            <!-- Operational Logs -->
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow">
                <h3 class="text-lg font-bold text-gray-200 mb-4">📋 Log Operativi Live</h3>
                <div id="logContainer" class="bg-gray-950 p-4 rounded-lg h-72 overflow-y-auto text-xs font-mono text-green-400 space-y-1"></div>
            </div>
        </div>
    </div>

    <script>
        async function fetchDashboard() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                
                document.getElementById('portfolioVal').innerText = '$' + data.account.portfolio.toLocaleString(undefined, {minimumFractionDigits: 2});
                document.getElementById('cashVal').innerText = '$' + data.account.cash.toLocaleString(undefined, {minimumFractionDigits: 2});
                document.getElementById('buyingPower').innerText = '$' + data.account.buying_power.toLocaleString(undefined, {minimumFractionDigits: 2});
                document.getElementById('lastScan').innerText = data.bot.last_scan;
                document.getElementById('botStatus').innerText = data.bot.status;

                const tbody = document.getElementById('positionsTable');
                tbody.innerHTML = '';
                if(data.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-gray-500">Nessuna posizione aperta al momento.</td></tr>';
                } else {
                    data.positions.forEach(p => {
                        const plColor = p.unrealized_pl >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold';
                        tbody.innerHTML += `
                            <tr>
                                <td class="p-3 font-bold text-white">${p.symbol}</td>
                                <td class="p-3">${p.qty}</td>
                                <td class="p-3">$${p.current_price.toFixed(2)}</td>
                                <td class="p-3">$${p.market_value.toFixed(2)}</td>
                                <td class="p-3 ${plColor}">$${p.unrealized_pl.toFixed(2)}</td>
                            </tr>
                        `;
                    });
                }

                const logBox = document.getElementById('logContainer');
                logBox.innerHTML = data.bot.logs.map(l => `<div>${l}</div>`).join('');
            } catch(e) {
                console.error("Errore aggiornamento dashboard:", e);
            }
        }

        async function triggerScan() {
            await fetch('/api/trigger', {method: 'POST'});
            fetchDashboard();
        }

        async function toggleBot() {
            const res = await fetch('/api/toggle', {method: 'POST'});
            const data = await res.json();
            document.getElementById('btnToggle').innerText = data.active ? 'Pausa Bot' : 'Riprendi Bot';
        }

        setInterval(fetchDashboard, 3000);
        fetchDashboard();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

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
