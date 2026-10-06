import os
import sys
import time
import argparse
import datetime
import requests
import resend
import yfinance as yf

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

import trading_core as core
from trading_core import alpaca_client

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
RESEND_KEY = os.getenv("RESEND_API_KEY")
ALERT_EMAIL = os.getenv("ALERT_EMAIL")  # destinatario notifiche; se assente le email sono disattivate

if RESEND_KEY:
    resend.api_key = RESEND_KEY

def send_trade_alert(symbol, action, amount, price):
    """Invia un'email di notifica tramite Resend quando un ordine viene inviato."""
    if not RESEND_KEY or not ALERT_EMAIL:
        return

    try:
        params = {
            "from": "Trading Bot <onboarding@resend.dev>",
            "to": [ALERT_EMAIL],
            "subject": f"🚀 Bot Trading: Ordine {action.upper()} su {symbol}",
            "html": f"""
                <h2>Esecuzione Ordine Trading</h2>
                <p><strong>Azione:</strong> {action.upper()}</p>
                <p><strong>Ticker:</strong> {symbol}</p>
                <p><strong>Quantità / Importo:</strong> {amount}</p>
                <p><strong>Prezzo stimato:</strong> ${price:.2f}</p>
            """
        }
        resend.Emails.send(params)
    except Exception as e:
        print(f"[!] Errore invio email Resend: {e}")

def get_account_summary():
    """Recupera bilancio, valore totale e patrimonio dal conto Alpaca."""
    if not alpaca_client:
        print("[!] Credenziali Alpaca non configurate.")
        return {"cash": 0.0, "equity": 0.0, "buying_power": 0.0, "non_marginable_buying_power": 0.0}
    try:
        acc = alpaca_client.get_account()
        return {
            "cash": float(acc.cash),
            "equity": float(acc.equity),
            "buying_power": float(acc.buying_power),
            "non_marginable_buying_power": float(acc.non_marginable_buying_power or 0)
        }
    except Exception as e:
        print(f"[!] Errore recupero account Alpaca: {e}")
    return {"cash": 0.0, "equity": 0.0, "buying_power": 0.0, "non_marginable_buying_power": 0.0}

def get_positions():
    """Recupera le posizioni aperte, indicizzate per simbolo normalizzato (es. BTCUSD)."""
    if not alpaca_client:
        return {}
    try:
        positions = {}
        for p in alpaca_client.get_all_positions():
            positions[core.normalize_symbol(p.symbol)] = {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,
                "avg_entry_price": float(p.avg_entry_price)
            }
        return positions
    except Exception as e:
        print(f"[!] Errore recupero posizioni: {e}")
    return {}

def print_recent_orders():
    """Mostra gli ultimi ordini chiusi (acquisti/vendite)."""
    print("\n--- ULTIMI MOVIMENTI ESEGUITI ---")
    if not alpaca_client:
        print("Credenziali Alpaca non configurate.")
        return
    try:
        orders = alpaca_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=5))
        if not orders:
            print("Nessun movimento recente registrato.")
        for o in orders:
            side = str(getattr(o.side, "value", o.side)).upper()
            status = getattr(o.status, "value", o.status)
            price = o.filled_avg_price
            p_str = f"${float(price):.2f}" if price else "N/D"
            print(f" • [{side}] {o.filled_qty}x {o.symbol} @ {p_str} - Status: {status}")
    except Exception as e:
        print(f"[!] Impossibile recuperare lo storico ordini: {e}")

def fetch_news(symbol):
    """Notizie Finnhub degli ultimi 30 giorni (solo azioni); per le crypto usa yfinance."""
    if core.is_crypto(symbol) or not FINNHUB_KEY:
        return core.get_recent_news(symbol)
    try:
        today = datetime.date.today()
        params = {
            "symbol": symbol,
            "from": (today - datetime.timedelta(days=30)).isoformat(),
            "to": today.isoformat(),
            "token": FINNHUB_KEY,
        }
        r = requests.get("https://finnhub.io/api/v1/company-news", params=params, timeout=core.HTTP_TIMEOUT)
        if r.status_code == 200:
            headlines = [a.get('headline') for a in r.json()[:3] if a.get('headline')]
            if headlines:
                return " | ".join(headlines)
        else:
            print(f"[!] Finnhub {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[!] Errore notizie Finnhub: {e}")
    return core.get_recent_news(symbol)

def scan():
    print("\n[1/4] Scansione di mercato in corso...")
    results = []
    for ticker in core.get_config()["watchlist"]:
        try:
            df = yf.Ticker(ticker).history(period="5d", interval="1h")
            if len(df) > 5:
                p = float(df['Close'].iloc[-1])
                change = float(((df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]) * 100)
                score = min(100, max(10, int(50 + change * 5)))
                results.append({"symbol": ticker, "price": p, "score": score})
        except Exception as e:
            print(f"[!] Errore dati {ticker}: {e}")
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:3]

def evaluate_and_trade(asset, positions, pending, market_open):
    key = core.normalize_symbol(asset['symbol'])
    holding = positions.get(key)

    status_str = "NON in portafoglio"
    if holding:
        status_str = f"In portafoglio ({holding['qty']} quote, P&L attuale: {holding['unrealized_plpc']:.2f}%)"

    print(f"\n[2/4] Valutazione AI per {asset['symbol']} (${asset['price']:.2f}) | {status_str}...")

    if pending is None or key in pending:
        print(f"[i] Ordine già pendente (o stato ordini sconosciuto) su {asset['symbol']}: salto.")
        return
    if not core.is_crypto(asset['symbol']) and not market_open and not holding:
        print(f"[i] Mercato azionario chiuso: nessun nuovo acquisto su {asset['symbol']}.")
        return

    news = fetch_news(asset['symbol'])

    prompt = (
        f"Sei un trader algoritmico. Asset: {asset['symbol']}, Prezzo attuale: ${asset['price']:.2f}, "
        f"Score momentum: {asset['score']}/100, Stato Posizione: {status_str}, Notizie: {news}.\n"
        f"Inizia la risposta con esattamente 'DECISIONE: BUY', 'DECISIONE: SELL' oppure 'DECISIONE: HOLD' "
        f"e motiva in una frase."
    )

    text = core.query_ai(prompt)
    print(f"Decisione AI:\n{text}")
    decision = core.parse_decision(text)

    if not alpaca_client:
        print("[!] Credenziali Alpaca non configurate: nessun ordine inviato.")
        return
    if decision != "HOLD" and not core.get_config()["auto_execute_trades"]:
        print(f"[i] Modalità Advisor: suggerito {decision} su {asset['symbol']}, ordine non inviato.")
        return

    try:
        # LOGICA DI ACQUISTO
        if decision == "BUY":
            if holding:
                print(f"[i] Posizione già aperta su {asset['symbol']}: nessun acquisto aggiuntivo.")
                return
            if not core.is_crypto(asset['symbol']) and not market_open:
                print(f"[i] Mercato azionario chiuso: acquisto di {asset['symbol']} non inviato.")
                return
            funds = core.available_funds(get_account_summary(), crypto=core.is_crypto(asset['symbol']))
            allocation = funds * core.get_config()['max_allocation_pct'] / 100
            if funds <= core.MIN_ORDER_USD:
                print(f"[Trading] Liquidità disponibile insufficiente per nuovi acquisti (${funds:,.2f})")
            elif allocation >= core.MIN_ORDER_USD:
                print(f"[3/4] Invio ordine di ACQUISTO Alpaca: ${allocation:.2f} di {asset['symbol']}...")
                order = core.submit_notional_buy(asset['symbol'], allocation)
                pending.add(key)
                print(f"[4/4] ORDINE DI ACQUISTO INVIATO! ID: {order.id}")
                send_trade_alert(asset['symbol'], "BUY", f"${allocation:.2f}", asset['price'])
            else:
                print(f"[Trading] Budget ${allocation:,.2f} sotto il minimo di ${core.MIN_ORDER_USD:.0f}: nessun acquisto.")

        # LOGICA DI VENDITA
        elif decision == "SELL":
            if holding and holding['qty'] > 0:
                print(f"[3/4] Invio ordine di VENDITA Alpaca: Chiusura {holding['qty']} quote di {asset['symbol']}...")
                order = core.close_position(holding['symbol'])
                pending.add(key)
                print(f"[4/4] ORDINE DI VENDITA INVIATO! ID: {order.id}")
                send_trade_alert(asset['symbol'], "SELL", holding['qty'], asset['price'])
            else:
                print(f"[i] L'AI consiglia SELL su {asset['symbol']}, ma non possiedi quote in portafoglio.")

    except Exception as e:
        print(f"[!] Errore durante l'invio dell'ordine: {e}")

def run_once():
    print(f"=== AVVIO BOT DI TRADING AUTONOMO ({datetime.datetime.now():%Y-%m-%d %H:%M:%S}) ===")

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
        for pos in positions.values():
            print(f" • {pos['symbol']}: {pos['qty']} quote | Valore: ${pos['market_value']:.2f} | P&L: ${pos['unrealized_pl']:.2f} ({pos['unrealized_plpc']:.2f}%)")
    else:
        print("Nessuna posizione attualmente in portafoglio.")

    # 3. Ultimi Movimenti
    print_recent_orders()

    # 4. Scansione e Valutazione
    pending = core.get_pending_order_symbols()
    market_open = core.is_market_open()
    for a in scan():
        evaluate_and_trade(a, positions, pending, market_open)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scanner di mercato autonomo")
    parser.add_argument("--loop", action="store_true", help="esegue la scansione ciclicamente")
    parser.add_argument("--interval", type=int, default=None,
                        help="secondi tra una scansione e l'altra in modalità --loop (default: scan_interval_min di config.json)")
    args = parser.parse_args()

    if not args.loop:
        run_once()
        sys.exit(0)

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[!] Errore ciclo scanner: {e}")
        sys.stdout.flush()
        time.sleep(args.interval or core.get_config()["scan_interval_min"] * 60)
