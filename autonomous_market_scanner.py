import os
import time
import requests
import dotenv
import yfinance as yf
import google.generativeai as genai
import resend

dotenv.load_dotenv()

ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
RESEND_KEY = os.getenv("RESEND_API_KEY")

if RESEND_KEY:
    resend.api_key = RESEND_KEY

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
    "Content-Type": "application/json"
}

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    ai_model = genai.GenerativeModel('gemini-3.8-flash')

WATCHLIST = ["BTC-USD", "ETH-USD", "ADA-USD", "SOL-USD", "NVDA", "AAPL", "TSLA", "MSFT"]

def send_trade_alert(symbol, action, qty, price):
    """Invia un'email di notifica tramite Resend quando un ordine viene eseguito."""
    if not RESEND_KEY:
        return

    try:
        params = {
            "from": "Trading Bot <onboarding@resend.dev>",
            "to": ["TUA_EMAIL@gmail.com"], # Sostituisci con la tua email quando vuoi attivarlo
            "subject": f"🚀 Bot Trading: Ordine {action.upper()} su {symbol}",
            "html": f"""
                <h2>Esecuzione Ordine Trading</h2>
                <p><strong>Azione:</strong> {action.upper()}</p>
                <p><strong>Ticker:</strong> {symbol}</p>
                <p><strong>Quantità:</strong> {qty}</p>
                <p><strong>Prezzo stimato:</strong> ${price:.2f}</p>
            """
        }
        resend.Emails.send(params)
    except Exception as e:
        print(f"[!] Errore invio email Resend: {e}")

def get_account_summary():
    """Recupera bilancio, valore totale e patrimonio dal conto Alpaca."""
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/account", headers=HEADERS)
        if r.status_code == 200:
            data = r.json()
            return {
                "cash": float(data.get("cash", 0)),
                "equity": float(data.get("equity", 0)),
                "buying_power": float(data.get("buying_power", 0))
            }
    except Exception as e:
        print(f"[!] Errore recupero account Alpaca: {e}")
    return {"cash": 0.0, "equity": 0.0, "buying_power": 0.0}

def get_positions():
    """Recupera le posizioni attualmente aperte in portafoglio."""
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/positions", headers=HEADERS)
        if r.status_code == 200:
            positions = {}
            for p in r.json():
                clean_sym = p['symbol'].replace("/", "")
                positions[clean_sym] = {
                    "qty": float(p['qty']),
                    "market_value": float(p['market_value']),
                    "unrealized_pl": float(p['unrealized_pl']),
                    "unrealized_plpc": float(p['unrealized_plpc']) * 100,
                    "avg_entry_price": float(p['avg_entry_price'])
                }
            return positions
    except Exception as e:
        print(f"[!] Errore recupero posizioni: {e}")
    return {}

def print_recent_orders():
    """Mostra gli ultimi ordini eseguiti (acquisti/vendite)."""
    print("\n--- ULTIMI MOVIMENTI ESEGUITI ---")
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/orders?status=closed&limit=5", headers=HEADERS)
        if r.status_code == 200 and r.json():
            for o in r.json():
                side = o.get("side", "").upper()
                sym = o.get("symbol")
                qty = o.get("filled_qty", 0)
                price = o.get("filled_avg_price")
                p_str = f"${float(price):.2f}" if price else "N/D"
                print(f" • [{side}] {qty}x {sym} @ {p_str} - Status: {o.get('status')}")
        else:
            print("Nessun movimento recente registrato.")
    except Exception as e:
        print(f"[!] Impossibile recuperare lo storico ordini: {e}")

def fetch_news(symbol):
    if not FINNHUB_KEY:
        return "Nessuna notizia"
    try:
        clean = symbol.split("-")[0]
        url = f"https://finnhub.io/api/v1/company-news?symbol={clean}&from=2026-09-01&to=2026-10-05&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200 and r.json():
            return " | ".join([a.get('headline', '') for a in r.json()[:3]])
    except Exception:
        pass
    return "Nessuna notizia rilevante"

def scan():
    print("\n[1/4] Scansione di mercato in corso...")
    results = []
    for ticker in WATCHLIST:
        try:
            df = yf.Ticker(ticker).history(period="5d", interval="1h")
            if len(df) > 5:
                p = float(df['Close'].iloc[-1])
                change = float(((df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]) * 100)
                score = min(100, max(10, int(50 + change * 5)))
                results.append({"symbol": ticker, "price": p, "score": score})
        except Exception:
            continue
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:3]

def evaluate_and_trade(asset, positions):
    clean_sym = asset['symbol'].replace("-", "")
    holding = positions.get(clean_sym, None)
    
    status_str = "NON in portafoglio"
    if holding:
        status_str = f"In portafoglio ({holding['qty']} quote, P&L attuale: {holding['unrealized_plpc']:.2f}%)"

    print(f"\n[2/4] Valutazione AI per {asset['symbol']} (${asset['price']:.2f}) | {status_str}...")
    news = fetch_news(asset['symbol'])
    
    prompt = (
        f"Sei un trader algoritmico. Asset: {asset['symbol']}, Prezzo attuale: ${asset['price']:.2f}, "
        f"Score momentum: {asset['score']}/100, Stato Posizione: {status_str}, Notizie: {news}.\n"
        f"Rispondi tassativamente iniziando con la tua decisione (BUY, SELL o HOLD) e motivando in una frase."
    )
    
    try:
        res = ai_model.generate_content(prompt)
        text = res.text
        print(f"Decisione AI:\n{text}")
        
        decision = text.strip().upper()
        
        # LOGICA DI ACQUISTO
        if "BUY" in decision:
            acc = get_account_summary()
            cash = acc['cash']
            allocation = cash * 0.15
            if allocation >= 10:
                qty = max(1, int(allocation / asset['price']))
                print(f"[3/4] Invio ordine di ACQUISTO Alpaca: {qty} quote di {asset['symbol']}...")
                order = {
                    "symbol": clean_sym,
                    "qty": qty,
                    "side": "buy",
                    "type": "market",
                    "time_in_force": "gtc"
                }
                r = requests.post(f"{ALPACA_BASE_URL}/orders", headers=HEADERS, json=order)
                if r.status_code in [200, 201]:
                    print(f"[4/4] ORDINE DI ACQUISTO ESEGUITO! ID: {r.json().get('id')}")
                    send_trade_alert(asset['symbol'], "BUY", qty, asset['price'])
                else:
                    print(f"[X] Errore Alpaca: {r.status_code} - {r.text}")
            else:
                print("[!] Liquidità insufficiente per un nuovo acquisto.")

        # LOGICA DI VENDITA
        elif "SELL" in decision:
            if holding and holding['qty'] > 0:
                qty_to_sell = holding['qty']
                print(f"[3/4] Invio ordine di VENDITA Alpaca: Chiusura {qty_to_sell} quote di {asset['symbol']}...")
                order = {
                    "symbol": clean_sym,
                    "qty": qty_to_sell,
                    "side": "sell",
                    "type": "market",
                    "time_in_force": "gtc"
                }
                r = requests.post(f"{ALPACA_BASE_URL}/orders", headers=HEADERS, json=order)
                if r.status_code in [200, 201]:
                    print(f"[4/4] ORDINE DI VENDITA ESEGUITO! ID: {r.json().get('id')}")
                    send_trade_alert(asset['symbol'], "SELL", qty_to_sell, asset['price'])
                else:
                    print(f"[X] Errore Alpaca vendita: {r.status_code} - {r.text}")
            else:
                print(f"[i] L'AI consiglia SELL su {asset['symbol']}, ma non possiedi quote in portafoglio.")

    except Exception as e:
        print(f"[!] Errore durante l'elaborazione: {e}")

if __name__ == "__main__":
    print("=== AVVIO BOT DI TRADING AUTONOMO ===")
    
    # 1. Bilancio Account
    acc = get_account_summary()
    print(f"\n--- BILANCIO CONTO ---")
    print(f" • Liquidità disponibile: ${acc['cash']:,.2f}")
    print(f" • Valore Totale Conto:   ${acc['equity']:,.2f}")
    print(f" • Potere d'acquisto:     ${acc['buying_power']:,.2f}")

    # 2. Posizioni Aperte
    positions = get_positions()
    print(f"\n--- POSIZIONI APERTE ({len(positions)}) ---")
    if positions:
        for sym, pos in positions.items():
            print(f" • {sym}: {pos['qty']} quote | Valore: ${pos['market_value']:.2f} | P&L: ${pos['unrealized_pl']:.2f} ({pos['unrealized_plpc']:.2f}%)")
    else:
        print("Nessuna posizione attualmente in portafoglio.")

    # 3. Ultimi Movimenti
    print_recent_orders()

    # 4. Scansione e Valutazione
    top = scan()
    for a in top:
        evaluate_and_trade(a, positions)
        