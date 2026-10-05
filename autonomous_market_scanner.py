import os
import time
import requests
import dotenv
import yfinance as yf
import google.generativeai as genai

dotenv.load_dotenv()

ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
    "Content-Type": "application/json"
}

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')

WATCHLIST = ["BTC-USD", "ETH-USD", "ADA-USD", "SOL-USD", "NVDA", "AAPL", "TSLA", "MSFT"]

def get_alpaca_cash():
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/account", headers=HEADERS)
        if r.status_code == 200:
            return float(r.json().get("cash", 0))
    except Exception as e:
        print(f"[!] Errore recupero account Alpaca: {e}")
    return 0.0

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

def evaluate_and_trade(asset):
    print(f"\n[2/4] Valutazione AI per {asset['symbol']} (${asset['price']:.2f})...")
    news = fetch_news(asset['symbol'])
    prompt = f"Sei un trader algoritmico. Asset: {asset['symbol']}, Prezzo: ${asset['price']:.2f}, Score: {asset['score']}/100, Notizie: {news}. Rispondi proponendo BUY, HOLD o SELL e motivando brevemente."
    
    try:
        res = ai_model.generate_content(prompt)
        text = res.text
        print(f"Decisione AI:\n{text}")
        
        if "BUY" in text.upper():
            cash = get_alpaca_cash()
            allocation = cash * 0.15
            if allocation >= 10:
                qty = max(1, int(allocation / asset['price']))
                print(f"[3/4] Invio ordine Alpaca: {qty} quote di {asset['symbol']} (Valore ${allocation:.2f})...")
                order = {
                    "symbol": asset['symbol'].replace("-", ""),
                    "qty": qty,
                    "side": "buy",
                    "type": "market",
                    "time_in_force": "gtc"
                }
                r = requests.post(f"{ALPACA_BASE_URL}/orders", headers=HEADERS, json=order)
                if r.status_code in [200, 201]:
                    print(f"[4/4] ORDINE ESEGUITO CON SUCCESSO! ID: {r.json().get('id')}")
                else:
                    print(f"[X] Risposta Alpaca: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"[!] Errore durante l'elaborazione: {e}")

if __name__ == "__main__":
    print("=== AVVIO BOT DI TRADING AUTONOMO ===")
    cash = get_alpaca_cash()
    print(f"[✓] Connessione Alpaca OK. Liquidità disponibile: ${cash:,.2f}")
    
    top = scan()
    for a in top:
        evaluate_and_trade(a)
