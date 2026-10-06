"""Logica condivisa tra app.py e autonomous_market_scanner.py.

Contiene: conversione simboli Alpaca <-> yfinance, parsing robusto delle
decisioni IA, chiamate a Gemini, notizie e invio ordini con controlli di
sicurezza (ordini pendenti, mercato chiuso, ordini notional).
"""
import os
import re
import json
import secrets
import threading
import time

import dotenv
import ta
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

dotenv.load_dotenv()

ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

GROQ_KEY = os.getenv("GROQ_API_KEY")

# Modelli Gemini supportati, in ordine di preferenza (sovrascrivibili da .env)
# I modelli in 404 vengono esclusi automaticamente alla prima risposta negativa
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS",
    "gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash,gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash",
).split(",") if m.strip()]
GEMINI_TIMEOUT_MS = 45000
# Modelli Groq in ordine di preferenza; quelli in 404 vengono esclusi automaticamente.
# GROQ_MODEL (singolo) resta supportato e viene provato per primo.
GROQ_MODELS = [m.strip() for m in (os.getenv("GROQ_MODEL", "") + "," + os.getenv(
    "GROQ_MODELS",
    "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b,llama-3.3-70b-versatile",
)).split(",") if m.strip()]
GROQ_MODELS = list(dict.fromkeys(GROQ_MODELS))  # rimuove duplicati mantenendo l'ordine

# Contesto per i modelli di chat: senza, alcuni rifiutano le richieste di tipo finanziario
AI_SYSTEM_PROMPT = (
    "Sei il modulo decisionale di un bot di trading algoritmico che opera su un conto paper (simulato) Alpaca. "
    "Le tue risposte vengono lette da un programma: rispondi sempre iniziando con 'DECISIONE: BUY', 'DECISIONE: SELL' "
    "o 'DECISIONE: HOLD' (solo le opzioni ammesse dal prompt), seguita da una breve motivazione tecnica."
)

MIN_ORDER_USD = 10.0
HTTP_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Configurazione dinamica (config.json)
# ---------------------------------------------------------------------------
CONFIG_PATH = os.getenv("BOT_CONFIG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))

# Valore segnaposto: se presente viene sostituito da un token casuale
PLACEHOLDER_TOKEN = "default-secret-token"
# Segreti salvati in config.json, mai esposti né modificabili dalla dashboard.
# Se la variabile d'ambiente corrispondente è impostata, ha la precedenza.
SECRET_FIELDS = {
    "bot_api_token": "BOT_API_TOKEN",
    "dashboard_password": "DASHBOARD_PASSWORD",
    "flask_secret_key": "FLASK_SECRET_KEY",
}
AI_PROVIDERS = ("gemini", "groq", "hybrid", "quant")
# Valori di versioni precedenti, convertiti automaticamente
LEGACY_PROVIDERS = {"claude": "gemini"}
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")

DEFAULT_CONFIG = {
    "watchlist": ["BTC-USD", "ETH-USD", "SOL-USD", "NVDA", "AAPL", "TSLA", "MSFT", "AMD"],
    "max_allocation_pct": 15.0,
    "stop_loss_pct": -5.0,
    "scan_interval_min": 15,
    "auto_execute_trades": True,
    "ai_provider": "gemini",
    "keep_alive_enabled": True,
    "bot_api_token": PLACEHOLDER_TOKEN,
}

_config_lock = threading.Lock()
_config = None


def _validate_config(data, base):
    """Valida e normalizza i campi. Solleva ValueError con un messaggio leggibile."""
    cfg = dict(base)

    if "watchlist" in data:
        wl = data["watchlist"]
        if not isinstance(wl, list):
            raise ValueError("watchlist deve essere una lista di ticker")
        cleaned = []
        for t in wl:
            t = str(t).strip().upper()
            if not _TICKER_RE.match(t):
                raise ValueError(f"Ticker non valido: {t!r}")
            if t not in cleaned:
                cleaned.append(t)
        if not cleaned:
            raise ValueError("La watchlist non può essere vuota")
        if len(cleaned) > 30:
            raise ValueError("Massimo 30 ticker in watchlist")
        cfg["watchlist"] = cleaned

    def number(key, lo, hi, cast=float):
        if key in data:
            try:
                value = cast(data[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} deve essere un numero")
            if not lo <= value <= hi:
                raise ValueError(f"{key} deve essere tra {lo} e {hi}")
            cfg[key] = value

    number("max_allocation_pct", 0.5, 100.0)
    number("stop_loss_pct", -50.0, -0.5)
    number("scan_interval_min", 1, 1440, int)

    for key in ("auto_execute_trades", "keep_alive_enabled"):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError(f"{key} deve essere true/false")
            cfg[key] = data[key]

    if "ai_provider" in data:
        provider = str(data["ai_provider"]).lower()
        provider = LEGACY_PROVIDERS.get(provider, provider)
        if provider not in AI_PROVIDERS:
            raise ValueError(f"ai_provider deve essere uno tra {', '.join(AI_PROVIDERS)}")
        cfg["ai_provider"] = provider

    for key in SECRET_FIELDS:
        if data.get(key):
            cfg[key] = str(data[key])

    return cfg


def _save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)  # scrittura atomica


def _load_config():
    cfg = dict(DEFAULT_CONFIG)
    dirty = not os.path.exists(CONFIG_PATH)
    if not dirty:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = _validate_config(json.load(f), DEFAULT_CONFIG)
        except (OSError, ValueError) as e:
            print(f"[!] config.json non valido ({e}): uso i valori di default.")
    for key, env_name in SECRET_FIELDS.items():
        if not os.getenv(env_name) and cfg.get(key) in (None, "", PLACEHOLDER_TOKEN):
            cfg[key] = secrets.token_urlsafe(32 if key == "flask_secret_key" else 12 if key == "dashboard_password" else 24)
            dirty = True
            if key == "dashboard_password":
                print(f"[!] DASHBOARD_PASSWORD non impostata: generata password '{cfg[key]}' (salvata in {CONFIG_PATH}).", flush=True)
    if dirty:
        try:
            _save_config(cfg)
        except OSError as e:
            print(f"[!] Impossibile salvare config.json: {e}")
    return cfg


def get_config():
    """Copia della configurazione corrente (caricata da config.json al primo uso)."""
    global _config
    with _config_lock:
        if _config is None:
            _config = _load_config()
        return json.loads(json.dumps(_config))


def update_config(changes):
    """Valida, applica e salva le modifiche. Restituisce la nuova configurazione."""
    global _config
    changes = {k: v for k, v in changes.items() if k not in SECRET_FIELDS}  # i segreti non si cambiano da UI
    current = get_config()
    new_cfg = _validate_config(changes, current)
    with _config_lock:
        _save_config(new_cfg)
        _config = new_cfg
    return json.loads(json.dumps(new_cfg))


def public_config():
    """Configurazione senza segreti, per la dashboard."""
    cfg = get_config()
    for key in SECRET_FIELDS:
        cfg.pop(key, None)
    return cfg


def get_api_token():
    """Token degli endpoint di controllo: variabile d'ambiente, altrimenti config.json."""
    return _secret("bot_api_token")


def get_dashboard_password():
    """Password della dashboard: DASHBOARD_PASSWORD, altrimenti generata in config.json."""
    return _secret("dashboard_password")


def get_secret_key():
    """Chiave per firmare i cookie di sessione Flask."""
    return _secret("flask_secret_key")


def _secret(key):
    return os.getenv(SECRET_FIELDS[key]) or get_config()[key]

alpaca_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True) if ALPACA_KEY and ALPACA_SECRET else None

_gemini_client = None

_DECISION_RE = re.compile(r"DECISIONE\s*[:=\-]?\s*[*_`\"']*\s*(BUY|SELL|HOLD)\b", re.IGNORECASE)
_LEADING_DECISION_RE = re.compile(r"^\W*(BUY|SELL|HOLD)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Simboli
# ---------------------------------------------------------------------------
def is_crypto(symbol):
    """True per simboli crypto in qualsiasi formato (BTC-USD, BTC/USD, BTCUSD)."""
    s = symbol.upper()
    if "-" in s or "/" in s:
        return s.replace("/", "-").endswith("-USD")
    return s in {normalize_symbol(w) for w in get_config()["watchlist"] if "-" in w}


def normalize_symbol(symbol):
    """Chiave di confronto unica: BTC-USD, BTC/USD e BTCUSD -> BTCUSD."""
    return symbol.upper().replace("-", "").replace("/", "")


def to_alpaca_symbol(yf_symbol):
    """yfinance -> Alpaca: BTC-USD -> BTC/USD, NVDA -> NVDA."""
    return yf_symbol.upper().replace("-", "/")


def to_yf_symbol(alpaca_symbol, crypto=None):
    """Alpaca -> yfinance: BTCUSD o BTC/USD -> BTC-USD, NVDA -> NVDA."""
    s = alpaca_symbol.upper()
    if "/" in s:
        return s.replace("/", "-")
    if crypto is None:
        crypto = is_crypto(s)
    if crypto and s.endswith("USD") and len(s) > 3:
        return f"{s[:-3]}-USD"
    return s


# ---------------------------------------------------------------------------
# IA
# ---------------------------------------------------------------------------
def parse_decision(text, allowed=("BUY", "SELL", "HOLD")):
    """Estrae la decisione dal testo dell'IA. In caso di dubbio restituisce HOLD."""
    if not text:
        return "HOLD"
    match = _DECISION_RE.search(text) or _LEADING_DECISION_RE.search(text.strip())
    if match:
        decision = match.group(1).upper()
        if decision in allowed:
            return decision
    return "HOLD"


_warned_at = {}


def _warn_throttled(key, message, log, every=3600):
    """Scrive un'avvertenza al massimo una volta ogni `every` secondi."""
    now = time.time()
    if now - _warned_at.get(key, 0) >= every:
        _warned_at[key] = now
        log(message)


def _resolve_provider(provider, log):
    """Sceglie il provider effettivo in base alle chiavi configurate."""
    if provider == "quant":
        return provider
    has = {"gemini": bool(GEMINI_KEY), "groq": bool(GROQ_KEY)}
    if provider == "hybrid":
        if all(has.values()):
            return provider
        if any(has.values()):
            fallback = "gemini" if has["gemini"] else "groq"
            missing = "GROQ_API_KEY" if has["gemini"] else "GEMINI_API_KEY"
            _warn_throttled("hybrid", f"⚠️ Modalità Ibrida: {missing} non configurata, uso solo {fallback.capitalize()}.", log)
            return fallback
        return _no_ai_keys(log)
    if not has[provider]:
        other = "groq" if provider == "gemini" else "gemini"
        if has[other]:
            _warn_throttled(provider, f"⚠️ {provider.upper()}_API_KEY non configurata: uso {other.capitalize()}.", log)
            return other
        return _no_ai_keys(log)
    return provider


def _no_ai_keys(log):
    _warn_throttled("no-keys", "🧮 Nessuna chiave IA configurata (GEMINI_API_KEY / GROQ_API_KEY): uso l'analisi quantitativa di riserva.", log)
    return "quant"


def query_ai(prompt, log=print, symbol=None):
    """Come query_ai_with_source, ma restituisce solo il testo della decisione."""
    return query_ai_with_source(prompt, log=log, symbol=symbol)[0]


def query_ai_with_source(prompt, log=print, symbol=None):
    """Restituisce (testo, motore) dove motore indica chi ha deciso (es. "Groq openai/gpt-oss-120b").

    Interroga il motore scelto in config.json (gemini / groq / hybrid / quant).

    - gemini / groq: se il motore scelto non risponde si prova l'altra IA.
    - hybrid: si opera solo se Gemini e Groq sono d'accordo, altrimenti HOLD;
      se uno dei due non risponde si usa l'altro.
    - Se nessuna IA risponde (o non ci sono chiavi) e `symbol` è indicato,
      si usa il motore quantitativo di riserva (RSI + SMA20).
    """
    provider = _resolve_provider(get_config()["ai_provider"], log)

    if provider == "quant":
        if not symbol:
            return "DECISIONE: HOLD | MOTIVO: Nessun simbolo per l'analisi quantitativa", "Nessuno"
        return quant_decision(symbol, log), "Quant"

    if provider == "hybrid":
        gemini_res = _ask_gemini(prompt, log)
        groq_res = _ask_groq(prompt, log)
        if gemini_res and groq_res:
            d_gemini, d_groq = parse_decision(gemini_res), parse_decision(groq_res)
            decision = d_gemini if d_gemini == d_groq else "HOLD"
            return (f"DECISIONE: {decision} | IBRIDO (Gemini={d_gemini}, Groq={d_groq})\n"
                    f"[Gemini] {gemini_res}\n[Groq] {groq_res}"), "Ibrido Gemini+Groq"
        if gemini_res or groq_res:
            working, failed = ("Gemini", "Groq") if gemini_res else ("Groq", "Gemini")
            log(f"⚠️ Modalità Ibrida: {failed} non ha risposto, decisione basata solo su {working}.")
            return gemini_res or groq_res, _last_model[working.lower()]
        result = None
    else:
        # Motore scelto, poi l'altra IA (se ha la chiave) prima del motore quantitativo
        ask = {"gemini": (_ask_gemini, "Gemini", GEMINI_KEY), "groq": (_ask_groq, "Groq", GROQ_KEY)}
        primary_fn, primary_name, _ = ask[provider]
        backup_fn, backup_name, backup_key = ask["groq" if provider == "gemini" else "gemini"]
        result, source = primary_fn(prompt, log), primary_name
        if not result and backup_key:
            log(f"🔁 {primary_name} non ha risposto: provo {backup_name} come riserva.")
            result, source = backup_fn(prompt, log), backup_name
        if result:
            return result, _last_model[source.lower()]

    if symbol:
        log("🧮 Nessuna IA disponibile: uso l'analisi quantitativa di riserva (RSI + SMA20).")
        return quant_decision(symbol, log), "Quant"
    return "DECISIONE: HOLD | MOTIVO: Nessun motore IA ha risposto", "Nessuno"


# Ultimo modello che ha risposto per ciascun provider (per i log delle decisioni)
_last_model = {"gemini": "Gemini", "groq": "Groq"}


def summarize_reason(text, limit=160):
    """Motivazione compatta su una riga, senza il prefisso 'DECISIONE: X'."""
    if not text:
        return ""
    reason = _DECISION_RE.sub("", text, count=1)
    reason = re.sub(r"\s+", " ", reason).strip(" -–—|:*.\n")
    reason = re.sub(r"^(MOTIVO|MOTIVAZIONE)\s*:\s*", "", reason, flags=re.IGNORECASE)
    return reason[:limit] + "…" if len(reason) > limit else reason


_groq_client = None


def query_groq_ai(prompt, log=print):
    """Interroga Groq (Llama 3.3 70B). In caso di errore la decisione diventa HOLD."""
    return _ask_groq(prompt, log) or "DECISIONE: HOLD | MOTIVO: Risposta fallback per errore API Groq"


_unavailable_groq_models = set()


def _ask_groq(prompt, log):
    """Prova i modelli Groq in sequenza; restituisce il testo o None. Gli errori vengono loggati."""
    global _groq_client
    if not GROQ_KEY:
        log("⚠️ GROQ_API_KEY non configurata.")
        return None
    try:
        import groq
        if _groq_client is None:
            _groq_client = groq.Groq(api_key=GROQ_KEY, timeout=45, max_retries=1)
    except Exception as e:
        log(f"❌ Impossibile inizializzare il client Groq: {e}")
        return None

    models = [m for m in GROQ_MODELS if m not in _unavailable_groq_models]
    if not models:
        log("❌ Nessun modello Groq disponibile: aggiorna GROQ_MODELS.")
        return None

    for model in models:
        try:
            res = _groq_client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            text = res.choices[0].message.content if res.choices else None
            if text and _DECISION_RE.search(text):
                _last_model["groq"] = f"Groq {model}"
                return text
            log(f"⚠️ Groq {model}: risposta senza decisione, provo il modello successivo.")
        except groq.NotFoundError:
            _unavailable_groq_models.add(model)
            log(f"⚠️ Groq {model}: modello non disponibile (404), escluso. Provo il successivo.")
        except groq.RateLimitError:
            log(f"⚠️ Groq {model}: limite di richieste raggiunto (429), provo il modello successivo.")
        except groq.AuthenticationError:
            log("❌ Groq: GROQ_API_KEY non valida.")
            return None
        except Exception as e:
            log(f"❌ Errore Groq ({model}): {str(e)[:200]}")

    log("❌ Tutti i modelli Groq hanno fallito.")
    return None


# Modelli che hanno restituito 404 / deprecato: non vengono più riprovati
_unavailable_gemini_models = set()


def query_gemini_ai(prompt, log=print):
    """Interroga Gemini provando i modelli configurati. In caso di errore la decisione diventa HOLD."""
    return _ask_gemini(prompt, log) or "DECISIONE: HOLD | MOTIVO: Risposta fallback per errore API Gemini"


def _ask_gemini(prompt, log):
    """Prova i modelli Gemini in sequenza; restituisce il testo o None. Gli errori vengono loggati."""
    global _gemini_client
    if not GEMINI_KEY:
        log("⚠️ GEMINI_API_KEY non configurata.")
        return None

    try:
        from google import genai
        from google.genai import errors as genai_errors, types as genai_types
        if _gemini_client is None:
            _gemini_client = genai.Client(
                api_key=GEMINI_KEY,
                http_options=genai_types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
            )
    except Exception as e:
        log(f"❌ Impossibile inizializzare il client Gemini: {e}")
        return None

    models = [m for m in GEMINI_MODELS if m not in _unavailable_gemini_models]
    if not models:
        log("❌ Nessun modello Gemini disponibile: aggiorna GEMINI_MODELS.")
        return None

    for model in models:
        try:
            res = _gemini_client.models.generate_content(model=model, contents=prompt)
            if res and res.text:
                _last_model["gemini"] = f"Gemini {model}"
                return res.text
            log(f"⚠️ Gemini {model}: risposta vuota, provo il modello successivo.")
        except genai_errors.ClientError as e:
            message = str(e)
            if e.code == 404 or "deprecat" in message.lower() or "no longer available" in message.lower():
                _unavailable_gemini_models.add(model)
                log(f"⚠️ Gemini {model}: modello non disponibile (404/deprecato), escluso. Provo il successivo.")
            elif e.code == 429:
                log(f"⚠️ Gemini {model}: quota esaurita (429), provo il modello successivo.")
            else:
                log(f"❌ Errore Gemini ({model}): {message[:200]}")
        except genai_errors.ServerError as e:
            log(f"⚠️ Gemini {model}: servizio non disponibile ({e.code}), provo il modello successivo.")
        except Exception as e:
            log(f"❌ Errore Gemini ({model}): {str(e)[:200]}")

    log("❌ Tutti i modelli Gemini hanno fallito.")
    return None


# ---------------------------------------------------------------------------
# Dati di mercato
# ---------------------------------------------------------------------------
def get_recent_news(yf_symbol, limit=3):
    """Ultimi titoli di notizie tramite yfinance (compatibile con vecchio e nuovo formato)."""
    try:
        news = yf.Ticker(yf_symbol).news or []
        titles = []
        for item in news:
            title = item.get("title") or (item.get("content") or {}).get("title")
            if title:
                titles.append(title)
            if len(titles) >= limit:
                break
        if titles:
            return " | ".join(titles)
    except Exception:
        pass
    return "Nessuna notizia rilevante recente."


def get_indicators(yf_symbol):
    """RSI(14), SMA(20) e prezzo su candele 1h dell'ultimo mese, oppure None."""
    try:
        df = yf.Ticker(yf_symbol).history(period="1mo", interval="1h")
        if len(df) >= 20:
            close = df["Close"]
            return {
                "rsi": round(float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]), 2),
                "sma20": float(ta.trend.SMAIndicator(close, window=20).sma_indicator().iloc[-1]),
                "price": float(close.iloc[-1]),
            }
    except Exception:
        pass
    return None


def get_rsi_and_price(yf_symbol):
    """Restituisce (rsi, prezzo) su candele 1h dell'ultimo mese, oppure (None, None)."""
    ind = get_indicators(yf_symbol)
    return (ind["rsi"], ind["price"]) if ind else (None, None)


def quant_rule(rsi, price, sma20):
    """Regole del motore quantitativo: (decisione, motivo)."""
    if rsi < 30 and price > sma20:
        return "BUY", f"RSI {rsi:.1f} < 30 (ipervenduto) e prezzo sopra SMA20"
    if rsi > 70:
        return "SELL", f"RSI {rsi:.1f} > 70 (ipercomprato)"
    return "HOLD", f"RSI {rsi:.1f} neutrale"


def quant_decision(yf_symbol, log=print):
    """Analisi tecnica senza IA, nello stesso formato testuale delle risposte IA."""
    ind = get_indicators(yf_symbol)
    if not ind:
        log(f"🧮 [Quant] {yf_symbol}: dati insufficienti, HOLD.")
        return "DECISIONE: HOLD | MOTIVO: [Quant] dati di mercato insufficienti"
    decision, reason = quant_rule(ind["rsi"], ind["price"], ind["sma20"])
    detail = f"prezzo ${ind['price']:.2f}, SMA20 ${ind['sma20']:.2f}"
    log(f"🧮 [Quant] {yf_symbol}: {decision} ({reason}; {detail})")
    return f"DECISIONE: {decision} | MOTIVO: [Quant] {reason}; {detail}"


# ---------------------------------------------------------------------------
# Alpaca
# ---------------------------------------------------------------------------
def get_pending_order_symbols(log=print):
    """Simboli (normalizzati) con ordini ancora aperti su Alpaca."""
    if not alpaca_client:
        return set()
    try:
        orders = alpaca_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return {normalize_symbol(o.symbol) for o in orders}
    except Exception as e:
        log(f"Errore lettura ordini pendenti: {e}")
        return None  # None = stato sconosciuto: il chiamante non deve inviare ordini


def is_market_open(log=print):
    if not alpaca_client:
        return False
    try:
        return bool(alpaca_client.get_clock().is_open)
    except Exception as e:
        log(f"Errore lettura orari di mercato: {e}")
        return False


def submit_notional_buy(yf_symbol, amount_usd):
    """Acquisto a importo (notional), così non si compra mai più del budget.

    Le azioni frazionarie richiedono time_in_force=DAY, le crypto GTC.
    """
    crypto = is_crypto(yf_symbol)
    order_data = MarketOrderRequest(
        symbol=to_alpaca_symbol(yf_symbol),
        notional=round(amount_usd, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC if crypto else TimeInForce.DAY,
    )
    return alpaca_client.submit_order(order_data)


def close_position(alpaca_symbol):
    """Chiude l'intera posizione (gestisce anche le quantità frazionarie)."""
    return alpaca_client.close_position(alpaca_symbol)


def available_funds(account, crypto=False):
    """Fondi utilizzabili per nuovi acquisti, mai negativi.

    `cash` può essere negativo con margine o posizioni aperte, quindi si usa il buying power.
    Le crypto non possono essere comprate a margine: per loro vale non_marginable_buying_power.
    """
    key = "non_marginable_buying_power" if crypto else "buying_power"
    try:
        return max(0.0, float(account.get(key) or 0))
    except (TypeError, ValueError):
        return 0.0
