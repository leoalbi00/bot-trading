"""Logica condivisa tra app.py e autonomous_market_scanner.py.

Contiene: conversione simboli Alpaca <-> yfinance, parsing robusto delle
decisioni IA, chiamate a Gemini, notizie e invio ordini con controlli di
sicurezza (ordini pendenti, mercato chiuso, ordini notional).
"""
import os
import re
import datetime as dt
from zoneinfo import ZoneInfo
import json
import secrets
import uuid
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
    "Le tue risposte vengono lette da un programma: rispondi sempre nel formato richiesto, iniziando con "
    "'DECISIONE: BUY', 'DECISIONE: SELL' o 'DECISIONE: HOLD' (solo le opzioni ammesse dal prompt), "
    "poi 'SCORE: <0-100>' e 'MOTIVO: <breve spiegazione tecnica>'."
)

# Fuso orario per log, orari e calcolo del giorno (Render usa UTC)
TIMEZONE = ZoneInfo(os.getenv("BOT_TIMEZONE", "Europe/Rome"))


def now_local():
    """Data e ora correnti nel fuso orario del bot (default Europe/Rome)."""
    return dt.datetime.now(TIMEZONE)


MIN_ORDER_USD = 10.0
ORDER_TAG_PREFIX = "brd-"  # prefisso del client_order_id degli acquisti del bot
_ORDER_STOP_RE = re.compile(r"^brd-s(\d+)-")
HTTP_TIMEOUT = 10

# Regole di uscita attiva e rotazione del capitale
STALL_ROC_PCT = 0.5            # |ROC(10)| sotto questa soglia = prezzo in stallo
STALL_MIN_CYCLES = 3           # cicli consecutivi in portafoglio prima di vendere per stallo
REVERSAL_ROC_PCT = -2.0        # ROC(10) sotto questa soglia con prezzo < SMA20 = inversione ribassista
ROTATION_FUNDS_THRESHOLD = 50  # sotto questi fondi si valuta la rotazione del capitale
ROTATION_MIN_SCORE = 80        # il nuovo asset deve avere score > di questo valore per la rotazione
ROTATION_MIN_EDGE = 10         # vantaggio minimo di score sul titolo venduto (evita compravendite inutili)

# Desk multi-agente: soglie dello Score di Forza (0-100)
SCORE_BUY = 75                 # > 75: candidato BUY
STRONG_BUY_SCORE = 85          # >= 85: STRONG BUY, allocazione maggiorata (25-30%)
SCORE_SELL = 45                # < 45: candidato SELL / debolezza
STALL_SCORE = 55               # stallo: ROC vicino a 0 e score < 55...
STALL_MIN_HOLD_MIN = 45        # ...con posizione aperta da almeno 45 minuti (3 cicli), letta da Alpaca

# ---------------------------------------------------------------------------
# Configurazione dinamica (config.json)
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# config.json (nel repository): default permanenti, senza segreti, letti a ogni avvio -> sopravvivono ai deploy.
REPO_CONFIG_PATH = os.getenv("BOT_REPO_CONFIG_PATH", os.path.join(_BASE_DIR, "config.json"))
# config.local.json (escluso da git): segreti generati e modifiche fatte dalla dashboard.
CONFIG_PATH = os.getenv("BOT_CONFIG_PATH", os.path.join(_BASE_DIR, "config.local.json"))
# Nomi brevi accettati nei file di configurazione
CONFIG_KEY_ALIASES = {
    "auto_execute": "auto_execute_trades",
    "anti_sleep": "keep_alive_enabled",
    "buy_allocation_pct": "base_allocation_pct",
}

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
    "watchlist": [
        "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
        "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "GOOGL", "AMZN", "META", "PLTR", "COIN", "SMCI",
    ],
    "base_allocation_pct": 15.0,
    "max_allocation_pct": 30.0,
    "max_exposure_pct": 100.0,
    "stop_loss_pct": -5.0,
    "scan_interval_min": 15,
    "auto_execute_trades": True,
    "ai_provider": "groq",
    "keep_alive_enabled": True,
    "bot_api_token": PLACEHOLDER_TOKEN,
}


# Variabili d'ambiente (es. su Render) con PRIORITÀ ASSOLUTA su config.json.
# Una chiave impostata da ambiente non può essere modificata dalla dashboard.
ENV_OVERRIDES = {
    "auto_execute_trades": "BOT_AUTO_EXECUTE",
    "ai_provider": "BOT_AI_PROVIDER",
    "watchlist": "BOT_WATCHLIST",
    "base_allocation_pct": "BOT_BASE_ALLOCATION_PCT",
    "max_allocation_pct": "BOT_MAX_ALLOCATION_PCT",
    "max_exposure_pct": "BOT_MAX_EXPOSURE_PCT",
    "stop_loss_pct": "BOT_STOP_LOSS_PCT",
    "scan_interval_min": "BOT_SCAN_INTERVAL_MIN",
    "keep_alive_enabled": "BOT_KEEP_ALIVE",
}
_TRUE = ("1", "true", "yes", "on", "si", "sì")
_FALSE = ("0", "false", "no", "off")


def config_sources():
    """Descrizione delle fonti di configurazione in ordine di priorità crescente (per i log)."""
    return [
        "default del codice",
        f"{os.path.basename(REPO_CONFIG_PATH)} ({'presente' if os.path.exists(REPO_CONFIG_PATH) else 'assente'})",
        f"{os.path.basename(CONFIG_PATH)} ({'presente' if os.path.exists(CONFIG_PATH) else 'assente'})",
        f"variabili d'ambiente ({', '.join(ENV_OVERRIDES[k] for k in env_overrides()) or 'nessuna'})",
    ]


def _parse_env_value(key, raw):
    raw = raw.strip()
    if isinstance(DEFAULT_CONFIG[key], bool):
        if raw.lower() in _TRUE:
            return True
        if raw.lower() in _FALSE:
            return False
        raise ValueError(f"valore booleano non valido: {raw!r}")
    if isinstance(DEFAULT_CONFIG[key], list):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return raw


_env_warned = set()


def env_overrides():
    """{chiave: valore validato} per le variabili d'ambiente presenti. Valori non validi vengono ignorati."""
    out = {}
    for key, env_name in ENV_OVERRIDES.items():
        raw = os.getenv(env_name)
        if raw is None or not raw.strip():
            continue
        try:
            out[key] = _validate_config({key: _parse_env_value(key, raw)}, DEFAULT_CONFIG)[key]
        except ValueError as e:
            if (env_name, raw) not in _env_warned:
                _env_warned.add((env_name, raw))
                print(f"[!] {env_name} ignorata: {e}", flush=True)
    return out

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

    number("base_allocation_pct", 0.5, 100.0)
    number("max_allocation_pct", 0.5, 100.0)
    if cfg.get("base_allocation_pct", 0) > cfg.get("max_allocation_pct", 100):
        raise ValueError("base_allocation_pct non può superare max_allocation_pct")
    number("max_exposure_pct", 10.0, 400.0)
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
    """Salva in config.local.json i segreti e solo i valori diversi dai default del repository."""
    base = repo_defaults()
    data = {k: v for k, v in cfg.items() if k in SECRET_FIELDS or v != base.get(k)}
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)  # scrittura atomica


def _read_config_file(path, label):
    """Legge un file di configurazione (dict). File mancante -> {}; file non valido -> {} con avviso."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"[!] {label} non valido ({e}): ignorato.", flush=True)
        return {}
    if not isinstance(data, dict):
        print(f"[!] {label} non contiene un oggetto JSON: ignorato.", flush=True)
        return {}
    return {CONFIG_KEY_ALIASES.get(k, k): v for k, v in data.items()}


def repo_defaults():
    """Default permanenti: codice + config.json del repository (i segreti nel repository vengono ignorati)."""
    repo = {k: v for k, v in _read_config_file(REPO_CONFIG_PATH, "config.json").items() if k not in SECRET_FIELDS}
    try:
        return _validate_config(repo, DEFAULT_CONFIG)
    except ValueError as e:
        print(f"[!] config.json non valido ({e}): uso i default del codice.", flush=True)
        return dict(DEFAULT_CONFIG)


def _load_config():
    """Configurazione salvata: default del repository + config.local.json (dashboard e segreti).

    Le variabili d'ambiente vengono applicate sopra a ogni lettura (vedi get_config).
    """
    base = repo_defaults()
    local = _read_config_file(CONFIG_PATH, os.path.basename(CONFIG_PATH))
    dirty = not os.path.exists(CONFIG_PATH)
    try:
        cfg = _validate_config(local, base)
    except ValueError as e:
        print(f"[!] {os.path.basename(CONFIG_PATH)} non valido ({e}): uso i default del repository.", flush=True)
        cfg = dict(base)
        dirty = True
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
            print(f"[!] Impossibile salvare {os.path.basename(CONFIG_PATH)}: {e}", flush=True)
    return cfg


def get_config():
    """Configurazione corrente: config.json (o default) + variabili d'ambiente con priorità assoluta."""
    global _config
    with _config_lock:
        if _config is None:
            _config = _load_config()
        cfg = json.loads(json.dumps(_config))
    cfg.update(env_overrides())
    return cfg


def update_config(changes):
    """Valida, applica e salva le modifiche. Restituisce la nuova configurazione.

    Le chiavi fissate da variabile d'ambiente non possono essere cambiate: la richiesta viene rifiutata.
    """
    global _config
    changes = {k: v for k, v in changes.items() if k not in SECRET_FIELDS}  # i segreti non si cambiano da UI
    locked = env_overrides()
    for key, value in changes.items():
        if key in locked and _validate_config({key: value}, DEFAULT_CONFIG)[key] != locked[key]:
            raise ValueError(f"{key} è fissato dalla variabile d'ambiente {ENV_OVERRIDES[key]}: modificala su Render")
    with _config_lock:
        if _config is None:
            _config = _load_config()
        new_cfg = _validate_config(changes, _config)
        _save_config(new_cfg)
        _config = new_cfg
    return get_config()


def public_config():
    """Configurazione senza segreti, per la dashboard, con l'elenco delle chiavi fissate da ambiente."""
    cfg = get_config()
    for key in SECRET_FIELDS:
        cfg.pop(key, None)
    cfg["env_locked"] = {key: ENV_OVERRIDES[key] for key in env_overrides()}
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
_SCORE_RE = re.compile(r"SCORE[\s*_`]*[:=][\s*_`\[]*(\d{1,3})", re.IGNORECASE)


def parse_score(text):
    """Estrae SCORE: 0-100 dalla risposta, oppure None."""
    match = _SCORE_RE.search(text or "")
    return max(0, min(100, int(match.group(1)))) if match else None


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
    reason = _DECISION_RE.sub("", text.replace("**", ""), count=1)
    reason = re.sub(r"\s+", " ", reason).strip(" -–—|:*.\n")
    reason = _SCORE_RE.sub("", reason, count=1)
    reason = re.sub(r"^[\s|:\-–—*\]]*", "", reason)
    reason = re.sub(r"^(MOTIVO|MOTIVAZIONE)\s*:\s*", "", reason, flags=re.IGNORECASE)
    return reason[:limit] + "…" if len(reason) > limit else reason


_groq_client = None


def query_groq_ai(prompt, log=print):
    """Interroga Groq (Llama 3.3 70B). In caso di errore la decisione diventa HOLD."""
    return _ask_groq(prompt, log) or "DECISIONE: HOLD | MOTIVO: Risposta fallback per errore API Groq"


_unavailable_groq_models = set()


def _has_decision(text):
    return bool(_DECISION_RE.search(text))


def _ask_groq(prompt, log, system=None, validate=_has_decision, max_tokens=1024):
    """Prova i modelli Groq in sequenza; restituisce il testo o None. Gli errori vengono loggati.

    `validate` scarta le risposte nel formato sbagliato (es. rifiuti) e passa al modello successivo.
    """
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
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system or AI_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            text = res.choices[0].message.content if res.choices else None
            if text and validate(text):
                _last_model["groq"] = f"Groq {model}"
                return text
            log(f"⚠️ Groq {model}: risposta nel formato errato, provo il modello successivo.")
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


def _ask_gemini(prompt, log, system=None, validate=_has_decision):
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
            res = _gemini_client.models.generate_content(model=model, contents=f"{system or AI_SYSTEM_PROMPT}\n\n{prompt}")
            if res and res.text and validate(res.text):
                _last_model["gemini"] = f"Gemini {model}"
                return res.text
            if res and res.text:
                log(f"⚠️ Gemini {model}: risposta nel formato errato, provo il modello successivo.")
                continue
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
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
CRYPTO_NAMES = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "AVAX": "avalanche",
                "ADA": "cardano", "DOGE": "dogecoin", "XRP": "xrp", "LTC": "litecoin", "DOT": "polkadot"}
_crypto_news_cache = {"ts": 0.0, "items": []}


def get_recent_news(yf_symbol, limit=3):
    """Ultimi titoli di notizie: yfinance, poi Finnhub come riserva (azioni e crypto)."""
    titles = []
    try:
        for item in yf.Ticker(yf_symbol).news or []:
            title = item.get("title") or (item.get("content") or {}).get("title")
            if title:
                titles.append(title)
            if len(titles) >= limit:
                break
    except Exception:
        pass
    if not titles:
        titles = _finnhub_headlines(yf_symbol, limit)
    return " | ".join(titles) if titles else "Nessuna notizia rilevante recente."


def _finnhub_headlines(yf_symbol, limit):
    if not FINNHUB_KEY:
        return []
    import requests
    from datetime import date, timedelta
    try:
        if is_crypto(yf_symbol):
            # Notizie crypto generali (cache 10 minuti) filtrate per ticker o nome della moneta
            if time.time() - _crypto_news_cache["ts"] > 600:
                r = requests.get("https://finnhub.io/api/v1/news", params={"category": "crypto", "token": FINNHUB_KEY},
                                 timeout=HTTP_TIMEOUT)
                _crypto_news_cache.update(ts=time.time(), items=r.json() if r.ok else [])
            base = yf_symbol.upper().split("-")[0]
            name = CRYPTO_NAMES.get(base, base.lower())
            pattern = re.compile(rf"\b({re.escape(base)}|{re.escape(name)})\b", re.IGNORECASE)
            return [a["headline"] for a in _crypto_news_cache["items"]
                    if a.get("headline") and pattern.search(a["headline"])][:limit]
        today = date.today()
        r = requests.get("https://finnhub.io/api/v1/company-news", timeout=HTTP_TIMEOUT, params={
            "symbol": yf_symbol, "from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat(),
            "token": FINNHUB_KEY})
        items = r.json() if r.ok else []
        return [a["headline"] for a in items if isinstance(a, dict) and a.get("headline")][:limit]
    except Exception:
        return []


def get_indicators(yf_symbol):
    """Indicatori su candele 1h degli ultimi 3 mesi, oppure None se i dati sono insufficienti.

    RSI(14), MACD(12,26,9) con istogramma e incroci recenti, ROC(10), SMA20, SMA50.
    """
    try:
        df = yf.Ticker(yf_symbol).history(period="3mo", interval="1h")
        if len(df) < 60:
            return None
        return compute_indicators(df["Close"], volume=df["Volume"])
    except Exception:
        return None


def compute_indicators(close, volume=None):
    """Calcola gli indicatori da una serie di prezzi di chiusura (almeno 60 valori).

    Con `volume` calcola anche vol_ratio: volume dell'ultima candela COMPLETA
    (la più recente di yfinance è ancora in corso) diviso la media dei 20 periodi precedenti.
    """
    macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    hist = macd.macd_diff()
    # Incrocio MACD/segnale nelle ultime 3 candele
    recent = hist.iloc[-4:]
    cross = None
    for prev, cur in zip(recent.iloc[:-1], recent.iloc[1:]):
        if prev <= 0 < cur:
            cross = "rialzista"
        elif prev >= 0 > cur:
            cross = "ribassista"
    return {
        "price": float(close.iloc[-1]),
        "rsi": round(float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]), 2),
        "macd": float(macd.macd().iloc[-1]),
        "macd_signal": float(macd.macd_signal().iloc[-1]),
        "macd_hist": float(hist.iloc[-1]),
        "macd_cross": cross,
        "roc": round(float(ta.momentum.ROCIndicator(close, window=10).roc().iloc[-1]), 2),
        "sma20": float(ta.trend.SMAIndicator(close, window=20).sma_indicator().iloc[-1]),
        "sma50": float(ta.trend.SMAIndicator(close, window=50).sma_indicator().iloc[-1]),
        "vol_ratio": _volume_ratio(volume),
    }


def _volume_ratio(volume):
    """Volume dell'ultima candela completa rispetto alla media della STESSA ORA nei giorni precedenti.

    Il volume intraday ha un andamento a U (alto in apertura e chiusura): confrontarlo con la media
    delle ultime 20 ore segnalerebbe ogni ora centrale come "bassa liquidità". Senza abbastanza
    campioni orari si usa la media dei 20 periodi precedenti.
    """
    if volume is None or len(volume) < 22:
        return None
    last = float(volume.iloc[-2])
    history = volume.iloc[:-2]
    try:
        same_hour = history[history.index.hour == volume.index[-2].hour].iloc[-20:]
    except AttributeError:
        same_hour = history.iloc[:0]
    sample = same_hour if len(same_hour) >= 5 else history.iloc[-20:]
    avg = float(sample.mean())
    return round(last / avg, 2) if avg > 0 else None


def ta_score(ind):
    """Punteggio tecnico 0-100: >50 rialzista, <50 ribassista."""
    score = 50.0
    rsi = ind["rsi"]
    if rsi < 30:
        score += 15
    elif rsi > 70:
        score -= 15
    score += 10 if ind["macd_hist"] > 0 else -10
    score += 5 if ind["macd"] > 0 else -5
    if ind["macd_cross"] == "rialzista":
        score += 10
    elif ind["macd_cross"] == "ribassista":
        score -= 10
    score += max(-15.0, min(15.0, ind["roc"] * 3))
    score += 10 if ind["sma20"] > ind["sma50"] else -10
    score += 5 if ind["price"] > ind["sma20"] else -5
    return int(max(0, min(100, round(score))))


def ta_exit_signal(ind):
    """Segnali tecnici di uscita: ('ribassista' | 'stallo' | None, motivo)."""
    bearish_cross = ind["macd_cross"] == "ribassista"
    if bearish_cross and ind["price"] < ind["sma20"]:
        return "ribassista", "incrocio MACD ribassista con prezzo sotto SMA20"
    if ind["sma20"] < ind["sma50"] and ind["macd"] < 0 and ind["roc"] < -STALL_ROC_PCT:
        return "ribassista", f"SMA20 sotto SMA50, MACD negativo e ROC {ind['roc']:.2f}%"
    if ind["price"] < ind["sma20"] and ind["macd_hist"] < 0 and ind["roc"] <= REVERSAL_ROC_PCT:
        return "ribassista", f"inversione: prezzo sotto SMA20, MACD in calo e ROC {ind['roc']:.2f}%"
    if abs(ind["roc"]) <= STALL_ROC_PCT and (ind["macd_hist"] < 0 or bearish_cross):
        return "stallo", f"ROC {ind['roc']:.2f}% piatto e MACD {'in incrocio ribassista' if bearish_cross else 'negativo'}"
    return None, ""


def format_indicators(ind):
    trend = "rialzista (SMA20 > SMA50)" if ind["sma20"] > ind["sma50"] else "ribassista (SMA20 < SMA50)"
    cross = f", incrocio {ind['macd_cross']} recente" if ind["macd_cross"] else ""
    return (
        f"- Prezzo: ${ind['price']:.4f}\n"
        f"- RSI(14, 1h): {ind['rsi']:.1f}\n"
        f"- MACD(12,26,9): {ind['macd']:.4f}, segnale {ind['macd_signal']:.4f}, istogramma {ind['macd_hist']:.4f}{cross}\n"
        f"- ROC(10): {ind['roc']:.2f}%\n"
        f"- SMA20: ${ind['sma20']:.4f} | SMA50: ${ind['sma50']:.4f} → trend {trend}\n"
        f"- Score tecnico: {ta_score(ind)}/100"
    )


def build_analysis_prompt(symbol, ind, news, position=None):
    """Prompt per l'IA. Con `position` valuta SELL/HOLD, altrimenti BUY/HOLD."""
    if position:
        context = (
            f"- Posizione aperta: {position['qty']} quote, valore ${position['market_value']:.2f}, "
            f"PnL ${position['unrealized_pl']:.2f} ({position['unrealized_plpc']:.2f}%)\n"
        )
        options, task = "SELL|HOLD", (
            "Decidi se VENDERE ora (trend ribassista, inversione, perdita di momentum o stallo che immobilizza capitale) "
            "oppure MANTENERE la posizione."
        )
    else:
        context = "- Posizione: non in portafoglio\n"
        options, task = "BUY|HOLD", "Decidi se ACQUISTARE ora oppure attendere."
    return (
        f"Sei un trader quantitativo di Wall Street orientato alla rotazione del capitale. Analizza i dati per {symbol}.\n"
        f"{context}{format_indicators(ind)}\n"
        f"- Notizie recenti: {news}\n\n"
        f"{task}\n"
        f"Restituisci la decisione nel formato esatto:\n"
        f"DECISIONE: [{options}]\n"
        f"SCORE: [0-100] (forza del segnale rialzista: 100 = acquisto molto forte, 0 = forte ribasso)\n"
        f"MOTIVO: [Breve spiegazione focalizzata su momentum, trend e rischio stallo]"
    )


def wait_for_fill(order_id, timeout=20, log=print):
    """Attende l'esecuzione di un ordine. Restituisce l'ordine eseguito oppure None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            order = alpaca_client.get_order_by_id(order_id)
            status = str(getattr(order.status, "value", order.status)).lower()
            if status == "filled":
                return order
            if status in ("canceled", "expired", "rejected"):
                log(f"Ordine {order_id} non eseguito: {status}")
                return None
        except Exception as e:
            log(f"Errore controllo ordine {order_id}: {e}")
        time.sleep(2)
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
    score = ta_score(ind)
    log(f"🧮 [Quant] {yf_symbol}: {decision} ({reason}; {detail}; score {score})")
    return f"DECISIONE: {decision} | SCORE: {score} | MOTIVO: [Quant] {reason}; {detail}"


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


def submit_notional_buy(yf_symbol, amount_usd, stop_pct=None):
    """Acquisto a importo (notional), così non si compra mai più del budget.

    Le azioni frazionarie richiedono time_in_force=DAY, le crypto GTC.
    Lo stop assegnato dal CIO viene salvato nel client_order_id dell'ordine (es. "brd-s450-…" = -4.50%):
    così sopravvive ai deploy e viene riletto dallo storico ordini di Alpaca.
    """
    crypto = is_crypto(yf_symbol)
    tag = f"s{int(round(abs(stop_pct) * 100))}" if stop_pct else "s0"
    order_data = MarketOrderRequest(
        symbol=to_alpaca_symbol(yf_symbol),
        notional=round(amount_usd, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC if crypto else TimeInForce.DAY,
        client_order_id=f"{ORDER_TAG_PREFIX}{tag}-{uuid.uuid4().hex[:16]}",
    )
    return alpaca_client.submit_order(order_data)


def close_position(alpaca_symbol):
    """Chiude l'intera posizione (gestisce anche le quantità frazionarie)."""
    return alpaca_client.close_position(alpaca_symbol)


def allocation_pct_for_score(score, cfg):
    """Percentuale del capitale per ordine in base alla confidenza (score 0-100).

    - score < 85 (BUY standard): base_allocation_pct (default 15%)
    - score 85-100 (STRONG BUY): da 25% a 30% in proporzione allo score,
      senza superare max_allocation_pct
    """
    base, cap = cfg["base_allocation_pct"], cfg["max_allocation_pct"]
    if score is None or score < STRONG_BUY_SCORE:
        return min(base, cap)
    strong = 25.0 + (min(score, 100) - STRONG_BUY_SCORE) / (100 - STRONG_BUY_SCORE) * 5.0
    return max(min(base, cap), min(strong, cap))


def buy_budget(account, exposure, cfg, crypto=False, score=None, pct=None, factor=1.0):
    """(fondi disponibili, importo del prossimo ordine) rispettando i limiti di rischio.

    - L'ordine è una percentuale del CAPITALE (equity) che cresce con lo score
      (vedi allocation_pct_for_score), non del buying power a margine.
    - L'esposizione totale (valore delle posizioni + nuovi ordini) non supera max_exposure_pct
      del capitale: con 100% il bot non usa mai il margine.
    """
    try:
        equity = max(0.0, float(account.get("portfolio", account.get("equity", 0)) or 0))
    except (TypeError, ValueError):
        equity = 0.0
    room = equity * cfg["max_exposure_pct"] / 100 - exposure
    funds = max(0.0, min(available_funds(account, crypto), room))
    pct = allocation_pct_for_score(score, cfg) if pct is None else pct
    allocation = min(equity * pct * factor / 100, funds)
    return funds, allocation


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


# ===========================================================================
# DESK FINANZIARIO MULTI-AGENTE
#   Fase 1 - Analista di mercato: indicatori e Score di Forza per ogni asset
#   Fase 2 - Risk Manager: stato delle posizioni, stallo, fondi ed esposizione
#   Fase 3 - Portfolio Broker: decisione operativa (IA in JSON o regole quant)
# ===========================================================================
def classify_score(score):
    if score > SCORE_BUY:
        return "BUY"
    if score < SCORE_SELL:
        return "SELL"
    return "NEUTRO"


def market_analyst(symbols, log=print):
    """FASE 1: calcola indicatori e Score di Forza per ogni simbolo (formato yfinance)."""
    analysis = {}
    for sym in dict.fromkeys(symbols):
        ind = get_indicators(sym)
        if not ind:
            log(f"📊 [Analista] {sym}: dati insufficienti, escluso.")
            continue
        score = ta_score(ind)
        analysis[normalize_symbol(sym)] = {"symbol": sym, "ind": ind, "score": score, "class": classify_score(score)}

    groups = {"BUY": [], "NEUTRO": [], "SELL": []}
    for a in sorted(analysis.values(), key=lambda a: a["score"], reverse=True):
        groups[a["class"]].append(f"{a['symbol']} {a['score']}")
    log(f"📊 [Analista] BUY (>{SCORE_BUY}): {', '.join(groups['BUY']) or '-'}")
    log(f"📊 [Analista] Neutrali/Stallo: {', '.join(groups['NEUTRO']) or '-'}")
    log(f"📊 [Analista] SELL (<{SCORE_SELL}): {', '.join(groups['SELL']) or '-'}")
    return analysis


def risk_manager(positions, analysis, account, cfg, log=print, stops=None, trailing=None, ledger=None):
    """FASE 2: classifica ogni posizione e calcola fondi ed esposizione.

    Senza stato in memoria: il tempo di permanenza in posizione viene dalla data del primo acquisto
    ancora aperto negli ordini Alpaca (ledger["open"]), non da contatori di cicli.
    Stati: STOP_LOSS, TRAILING_STOP, RIBASSISTA, STALLO -> vendita obbligatoria;
           IN_STALLO (in osservazione), OK, NO_DATA -> mantenute.
    """
    open_info = (ledger or {}).get("open", {})
    now = now_local()
    report = []
    for pos in positions:
        key = normalize_symbol(pos["symbol"])
        a = analysis.get(normalize_symbol(pos["yf_symbol"]))
        pl = pos["unrealized_plpc"]
        score = a["score"] if a else None
        opened = open_info.get(key, {}).get("opened_at")
        held_min = (now - opened).total_seconds() / 60 if opened else None  # None = oltre lo storico (90 gg)
        stalled_now = bool(a) and abs(a["ind"]["roc"]) <= STALL_ROC_PCT and a["score"] < STALL_SCORE
        held_long = held_min is None or held_min >= STALL_MIN_HOLD_MIN
        held_txt = "da oltre 90 giorni" if held_min is None else f"da {held_min:.0f} min"

        stop = (stops or {}).get(key, cfg["stop_loss_pct"])
        trail = (trailing or {}).get(key)
        if pl <= stop:
            status, reason = "STOP_LOSS", f"PnL {pl:.2f}% ≤ stop loss {stop:.1f}%"
        elif trail and trail.get("hit"):
            status, reason = "TRAILING_STOP", trail["reason"]
        elif not a:
            status, reason = "NO_DATA", "indicatori non disponibili"
        else:
            kind, why = ta_exit_signal(a["ind"])
            if kind == "ribassista":
                status, reason = "RIBASSISTA", why
            elif a["score"] < SCORE_SELL:
                status, reason = "RIBASSISTA", f"Score di Forza {a['score']} < {SCORE_SELL}"
            elif stalled_now and held_long:
                status, reason = "STALLO", f"ROC {a['ind']['roc']:.2f}% e score {a['score']}, in posizione {held_txt}"
            elif stalled_now:
                status, reason = "IN_STALLO", f"ROC {a['ind']['roc']:.2f}% e score {a['score']}, in posizione {held_txt} (minimo {STALL_MIN_HOLD_MIN})"
            else:
                status, reason = "OK", f"ROC {a['ind']['roc']:.2f}%, in posizione {held_txt}"
        report.append({"pos": pos, "analysis": a, "score": score, "status": status, "reason": reason,
                       "held_min": held_min})
        log(f"🛡️ [Risk] {pos['symbol']}: {status} | score {score if score is not None else 'N/D'} | "
            f"PnL {pl:.2f}% | stop {stop:.1f}% | {reason}")

    exposure = sum(abs(p["market_value"]) for p in positions)
    equity = float(account.get("portfolio", account.get("equity", 0)) or 0)
    funds = {
        "stock": buy_budget(account, exposure, cfg, crypto=False),
        "crypto": buy_budget(account, exposure, cfg, crypto=True),
    }
    pct = exposure / equity * 100 if equity else 0
    log(f"🛡️ [Risk] Capitale ${equity:,.0f} | esposizione ${exposure:,.0f} ({pct:.0f}%, limite {cfg['max_exposure_pct']:.0f}%) | "
        f"fondi disponibili azioni ${funds['stock'][0]:,.0f}, crypto ${funds['crypto'][0]:,.0f} | "
        f"buying power Alpaca ${float(account.get('buying_power', 0) or 0):,.0f}")
    return {"positions": report, "exposure": exposure, "equity": equity, "funds": funds}


BROKER_ACTIONS = ("BUY", "SELL", "ROTATE", "HOLD")

BROKER_SYSTEM_PROMPT = (
    "Sei un Senior Portfolio Manager & Quant Broker di un bot di trading algoritmico che opera su un conto paper "
    "(simulato) Alpaca. Le tue risposte vengono lette da un programma: rispondi SOLO con un oggetto JSON valido, "
    "senza testo prima o dopo."
)


def broker_candidates(analysis, held_keys, pending, market_open):
    """Asset della watchlist acquistabili ora con Score > SCORE_BUY, dal più forte."""
    out = []
    for key, a in analysis.items():
        if key in held_keys or key in pending or a["class"] != "BUY":
            continue
        if not is_crypto(a["symbol"]) and not market_open:
            continue
        out.append(a)
    return sorted(out, key=lambda a: a["score"], reverse=True)


def build_broker_prompt(risk, candidates, cfg, news=None):
    news = news or {}
    lines = []
    for r in risk["positions"]:
        p, a = r["pos"], r["analysis"]
        ind = (f"RSI {a['ind']['rsi']:.1f}, ROC {a['ind']['roc']:.2f}%, MACD hist {a['ind']['macd_hist']:.4f}, "
               f"SMA20 {'>' if a['ind']['sma20'] > a['ind']['sma50'] else '<'} SMA50") if a else "indicatori N/D"
        lines.append(f"  - {p['yf_symbol']}: valore ${p['market_value']:,.0f}, PnL {p['unrealized_plpc']:.2f}%, "
                     f"score {r['score']}, stato {r['status']} ({r['reason']}); {ind}")
    positions_txt = "\n".join(lines) or "  (nessuna posizione aperta)"
    cand_txt = "\n".join(
        f"  - {a['symbol']}: score {a['score']}, prezzo ${a['ind']['price']:.4f}, RSI {a['ind']['rsi']:.1f}, "
        f"ROC {a['ind']['roc']:.2f}%, MACD hist {a['ind']['macd_hist']:.4f}, "
        f"SMA20 {'>' if a['ind']['sma20'] > a['ind']['sma50'] else '<'} SMA50"
        + (f"; notizie: {news[a['symbol']]}" if news.get(a['symbol']) else "")
        for a in candidates[:5]
    ) or "  (nessun candidato con score > %d)" % SCORE_BUY
    f_stock, f_crypto = risk["funds"]["stock"][0], risk["funds"]["crypto"][0]
    return (
        "Sei un Quantitative Portfolio Broker. Ricevi l'elenco degli asset e delle posizioni correnti.\n"
        "Analizza l'opportunità di rotazione del capitale: se trovi un asset più promettente di quelli attuali "
        "e non c'è liquidità, indica quale vendere e quale acquistare. Il confronto con le posizioni attuali "
        "serve SOLO per la rotazione, quando la liquidità è esaurita.\n\n"
        f"Capitale: ${risk['equity']:,.0f} | esposizione: ${risk['exposure']:,.0f} | "
        f"liquidità disponibile: azioni ${f_stock:,.0f}, crypto ${f_crypto:,.0f}\n"
        f"Posizioni aperte:\n{positions_txt}\n"
        f"Candidati all'acquisto (Score di Forza > {SCORE_BUY}):\n{cand_txt}\n\n"
        "Regole del desk:\n"
        "- Se c'è liquidità disponibile (almeno $10) e c'è almeno un candidato, scegli BUY del candidato migliore: "
        "il capitale libero va investito. Non confrontare i candidati con le posizioni già aperte: "
        f"un candidato con score > {SCORE_BUY} è un acquisto valido anche se una posizione esistente ha score più alto. "
        "Usa HOLD solo se nessun candidato è convincente per motivi concreti (es. RSI in ipercomprato estremo, "
        "notizie negative).\n"
        "- buy_symbol deve essere tra i candidati elencati.\n"
        f"- ROTATE solo se la liquidità è insufficiente (< ${ROTATION_FUNDS_THRESHOLD}), buy_symbol ha score > "
        f"{ROTATION_MIN_SCORE} e almeno {ROTATION_MIN_EDGE} punti più di sell_symbol (preferisci posizioni in stallo o deboli).\n"
        "- SELL per chiudere una posizione debole o in stallo; HOLD se nessuna azione è vantaggiosa.\n"
        "- Le vendite per stop loss, trend ribassista e stallo prolungato sono già gestite dal Risk Manager.\n\n"
        "Restituisci la risposta in formato JSON pulito:\n"
        '{\n  "action": "BUY" | "SELL" | "ROTATE" | "HOLD",\n  "sell_symbol": "TICKER_DA_VENDERE",\n'
        '  "buy_symbol": "TICKER_DA_COMPRARE",\n  "score": 0-100,\n'
        '  "reason": "Spiegazione focalizzata su rotazione capitale e stallo"\n}\n'
        "score = tua confidenza nell'operazione (85-100 = STRONG BUY, aumenta il capitale investito).\n"
        "Usa i ticker esattamente come scritti sopra e stringa vuota per i campi non usati."
    )


def parse_broker_json(text):
    """Estrae e normalizza la decisione JSON del Broker, oppure None."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    action = str(data.get("action", "")).strip().upper()
    if action not in BROKER_ACTIONS:
        return None
    return {
        "action": action,
        "sell_symbol": str(data.get("sell_symbol") or "").strip().upper(),
        "buy_symbol": str(data.get("buy_symbol") or "").strip().upper(),
        "reason": str(data.get("reason") or "").strip(),
        "score": _clean_score(data.get("score")),
        "allocation_pct": _clean_number(data.get("allocation_pct")),
        "dynamic_stop_loss_pct": _clean_number(data.get("dynamic_stop_loss_pct")),
        "scout_discovery_approved": str(data.get("scout_discovery_approved", "")).strip().lower() in ("true", "1", "yes", "si", "sì"),
    }


def _clean_number(value):
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _clean_score(value):
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return None


def ask_broker_ai(prompt, log=print, system=None):
    """Interroga l'IA del Broker secondo ai_provider. Restituisce (decisione, motore) o (None, None)."""
    provider = _resolve_provider(get_config()["ai_provider"], log)
    if provider == "quant":
        return None, None
    ask = lambda fn: parse_broker_json(fn(prompt, log, system=system or BROKER_SYSTEM_PROMPT,
                                          validate=lambda t: parse_broker_json(t) is not None,
                                          **({"max_tokens": 2048} if fn is _ask_groq else {})))
    if provider == "hybrid":
        d_gemini, d_groq = ask(_ask_gemini), ask(_ask_groq)
        if d_gemini and d_groq:
            same = all(d_gemini[k] == d_groq[k] for k in ("action", "sell_symbol", "buy_symbol"))
            if same:
                return d_groq, "Ibrido Gemini+Groq"
            return ({"action": "HOLD", "sell_symbol": "", "buy_symbol": "",
                     "reason": f"Gemini ({d_gemini['action']}) e Groq ({d_groq['action']}) non concordano"},
                    "Ibrido Gemini+Groq")
        if d_gemini or d_groq:
            return (d_gemini, _last_model["gemini"]) if d_gemini else (d_groq, _last_model["groq"])
        return None, None

    order = [_ask_gemini, _ask_groq] if provider == "gemini" else [_ask_groq, _ask_gemini]
    keys = {_ask_gemini: GEMINI_KEY, _ask_groq: GROQ_KEY}
    for i, fn in enumerate(order):
        if i and not keys[fn]:
            continue
        if i:
            log(f"🔁 {'Gemini' if order[0] is _ask_gemini else 'Groq'} non ha risposto: provo "
                f"{'Groq' if fn is _ask_groq else 'Gemini'} come riserva.")
        decision = ask(fn)
        if decision:
            return decision, _last_model["groq" if fn is _ask_groq else "gemini"]
    return None, None


def weakest_holding(risk, exclude=()):
    """Posizione più debole vendibile: prima quelle in stallo, poi score e PnL più bassi."""
    choices = [r for r in risk["positions"]
               if r["status"] in ("OK", "IN_STALLO") and r["score"] is not None
               and normalize_symbol(r["pos"]["symbol"]) not in exclude]
    if not choices:
        return None
    return min(choices, key=lambda r: (r["status"] != "IN_STALLO", r["score"], r["pos"]["unrealized_plpc"]))


def ta_broker(risk, candidates):
    """Broker quantitativo di riserva (senza IA), con le stesse regole del desk."""
    if not candidates:
        return {"action": "HOLD", "sell_symbol": "", "buy_symbol": "", "reason": f"[Quant] Nessun asset con score > {SCORE_BUY}"}
    best = candidates[0]
    funds = risk["funds"]["crypto" if is_crypto(best["symbol"]) else "stock"]
    if funds[1] >= MIN_ORDER_USD:
        return {"action": "BUY", "sell_symbol": "", "buy_symbol": best["symbol"],
                "reason": f"[Quant] {best['symbol']} ha lo Score di Forza più alto ({best['score']})"}
    weak = weakest_holding(risk)
    if (funds[0] < ROTATION_FUNDS_THRESHOLD and best["score"] > ROTATION_MIN_SCORE and weak
            and best["score"] - weak["score"] >= ROTATION_MIN_EDGE):
        return {"action": "ROTATE", "sell_symbol": weak["pos"]["yf_symbol"], "buy_symbol": best["symbol"],
                "reason": f"[Quant] Rotazione: {weak['pos']['yf_symbol']} (score {weak['score']}, {weak['status']}) → "
                          f"{best['symbol']} (score {best['score']})"}
    return {"action": "HOLD", "sell_symbol": "", "buy_symbol": "",
            "reason": f"[Quant] Liquidità insufficiente e nessuna rotazione conveniente per {best['symbol']} (score {best['score']})"}


def validate_broker_decision(decision, risk, candidates, sold_keys=(), log=print):
    """Applica le regole del desk alla decisione del Broker; se non le rispetta la corregge o la annulla."""
    hold = lambda why: {"action": "HOLD", "sell_symbol": "", "buy_symbol": "", "reason": why}
    action = decision["action"]
    cand = {normalize_symbol(a["symbol"]): a for a in candidates}
    holdings = {normalize_symbol(r["pos"]["yf_symbol"]): r for r in risk["positions"]
                if normalize_symbol(r["pos"]["symbol"]) not in sold_keys}
    buy = cand.get(normalize_symbol(decision["buy_symbol"])) if decision["buy_symbol"] else None
    sell = holdings.get(normalize_symbol(decision["sell_symbol"])) if decision["sell_symbol"] else None

    if action == "HOLD":
        return decision
    if action == "SELL":
        if not sell:
            return hold(f"SELL scartato: {decision['sell_symbol'] or '?'} non è una posizione vendibile")
        return {**decision, "sell_symbol": sell["pos"]["yf_symbol"]}
    if not buy:
        return hold(f"{action} scartato: {decision['buy_symbol'] or '?'} non è tra i candidati acquistabili")

    funds = risk["funds"]["crypto" if is_crypto(buy["symbol"]) else "stock"]
    if action == "BUY":
        if funds[1] >= MIN_ORDER_USD:
            return {**decision, "buy_symbol": buy["symbol"]}
        # BUY senza liquidità: diventa una rotazione se il segnale è abbastanza forte
        sell = weakest_holding(risk, exclude=sold_keys)
        action = "ROTATE"
        log(f"💼 [Broker] Liquidità insufficiente per {buy['symbol']}: valuto la rotazione.")

    # ROTATE
    if funds[1] >= MIN_ORDER_USD:
        return {**decision, "action": "BUY", "sell_symbol": "", "buy_symbol": buy["symbol"],
                "reason": decision["reason"] + " (c'è liquidità: acquisto senza vendere)"}
    if not sell:
        sell = weakest_holding(risk, exclude=sold_keys)
    if not sell:
        return hold(f"Rotazione verso {buy['symbol']} impossibile: nessuna posizione vendibile")
    if buy["score"] <= ROTATION_MIN_SCORE:
        return hold(f"Rotazione scartata: {buy['symbol']} ha score {buy['score']} (serve > {ROTATION_MIN_SCORE})")
    if sell["score"] is not None and buy["score"] - sell["score"] < ROTATION_MIN_EDGE:
        return hold(f"Rotazione scartata: vantaggio {buy['symbol']} {buy['score']} vs {sell['pos']['yf_symbol']} "
                    f"{sell['score']} inferiore a {ROTATION_MIN_EDGE} punti")
    return {**decision, "action": "ROTATE", "sell_symbol": sell["pos"]["yf_symbol"], "buy_symbol": buy["symbol"]}


# ===========================================================================
# VIRTUAL BOARDROOM: 8 agenti quantitativi
#   1 Market Analyst        -> market_analyst (RSI, MACD, SMA20/50, ROC, Score di Forza)
#   2 Sentiment Intelligence-> sentiment_agent (veto BUY se sentiment < -40)
#   3 Volatility Manager    -> volatility_agent (ATR giornaliero, stop dinamico, trailing stop)
#   4 Macro Regime Analyst  -> macro_regime (SPY / BTC sotto SMA50 -> budget -50%)
#   5 Volume & Liquidity    -> volume_agent (vol_ratio < 0.8 con prezzo in salita = falso breakout)
#   6 Drawdown Controller   -> drawdown_controller (perdita giornaliera > 5% -> stop acquisti 24h)
#   7 Post-Trade Auditor    -> post_trade_auditor (trade_history.json, win rate per ticker)
#   8 CIO / Portfolio Broker-> build_cio_prompt + ask_broker_ai (una chiamata JSON)
# ===========================================================================
DATA_DIR = os.getenv("BOT_DATA_DIR", os.path.dirname(CONFIG_PATH))
TRADE_HISTORY_PATH = os.path.join(DATA_DIR, "trade_history.json")
BOARDROOM_STATE_PATH = os.path.join(DATA_DIR, "boardroom_state.json")

SENTIMENT_VETO = -40
ATR_MULT_STOCK = 1.5
ATR_MULT_CRYPTO = 2.0
STOP_TIGHTEST_PCT = -2.0       # limiti dello stop dinamico
STOP_WIDEST_PCT = -15.0
MACRO_RISK_OFF_FACTOR = 0.5
VOLUME_LOW_RATIO = 0.8
DAILY_DRAWDOWN_LIMIT = -5.0
DRAWDOWN_BLOCK_HOURS = 24
AUDIT_MIN_TRADES = 3
AUDIT_LOW_WINRATE = 30.0
AUDIT_PENALTY = 15

_state_lock = threading.Lock()


def read_json_file(path, default):
    """Legge un file JSON di stato. Se manca o è corrotto (es. dopo un deploy) lo rigenera con `default`."""
    with _state_lock:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, type(default)):
                return data
            print(f"[!] {os.path.basename(path)} con struttura inattesa: rigenerato.", flush=True)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            print(f"[!] {os.path.basename(path)} illeggibile ({e}): rigenerato.", flush=True)
    write_json_file(path, default)
    return json.loads(json.dumps(default))


def write_json_file(path, data):
    """Scrittura atomica; gli errori vengono stampati ma non interrompono il bot."""
    with _state_lock:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp, path)
            return True
        except OSError as e:
            print(f"[!] Impossibile salvare {os.path.basename(path)}: {e}", flush=True)
            return False


def load_state():
    """Stato accessorio del boardroom (solo blocco da drawdown). Tutto il resto viene da Alpaca."""
    return read_json_file(BOARDROOM_STATE_PATH, {"drawdown": {}})


def save_state(state):
    write_json_file(BOARDROOM_STATE_PATH, state)


# ---------------- Agente 2: Sentiment Intelligence ----------------
_POSITIVE_STEMS = (
    "beat", "surge", "soar", "rall", "upgrad", "record", "growth", "gain", "bullish", "outperform", "raise",
    "strong", "jump", "rise", "rising", "profit", "boost", "expan", "partnership", "approv", "breakthrough",
    "optimis", "top", "win", "accelerat", "buyback", "dividend",
)
_NEGATIVE_STEMS = (
    "miss", "plung", "drop", "fall", "downgrad", "lawsuit", "sue", "probe", "investigat", "fraud", "bearish",
    "cut", "weak", "loss", "declin", "selloff", "sell-off", "slump", "recall", "bankrupt", "warn", "layoff",
    "tumbl", "crash", "sink", "fear", "concern", "halt", "ban", "fine", "hack", "breach", "delay", "slow",
    "underperform", "risk", "short",
)


def sentiment_score(text):
    """Sentiment dei titoli da -100 a +100 (dizionario di parole chiave finanziarie).

    Restituisce (score, parole rilevanti trovate). Con poche parole lo score viene attenuato.
    """
    if not text or text.startswith("Nessuna notizia"):
        return 0, 0
    words = re.findall(r"[a-z][a-z\-]+", text.lower())
    pos = sum(1 for w in words if w.startswith(_POSITIVE_STEMS))
    neg = sum(1 for w in words if w.startswith(_NEGATIVE_STEMS))
    total = pos + neg
    if not total:
        return 0, 0
    return int(round((pos - neg) / total * 100 * min(1.0, total / 3))), total


def sentiment_agent(symbols, log=print):
    """Notizie e sentiment per i simboli indicati. Veto agli acquisti se sentiment < SENTIMENT_VETO."""
    out = {}
    for sym in symbols:
        news = get_recent_news(sym)
        score, hits = sentiment_score(news)
        out[normalize_symbol(sym)] = {"symbol": sym, "news": news, "sentiment": score, "hits": hits,
                                      "veto": score < SENTIMENT_VETO}
    vetoed = [f"{v['symbol']} ({v['sentiment']})" for v in out.values() if v["veto"]]
    summary = ", ".join(f"{v['symbol']} {v['sentiment']:+d}" for v in out.values())
    log(f"📰 [Sentiment] {summary or '-'}" + (f" | VETO BUY: {', '.join(vetoed)}" if vetoed else ""))
    return out


# ---------------- Agente 3: Volatility Manager ----------------
def get_daily_bars(yf_symbol, period="6mo"):
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval="1d")
        return df if len(df) >= 55 else None
    except Exception:
        return None


def atr_pct(df):
    """ATR(14) giornaliero in percentuale del prezzo."""
    atr = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=14).average_true_range()
    return round(float(atr.iloc[-1]) / float(df["Close"].iloc[-1]) * 100, 2)


def dynamic_stop_pct(atr_percent, crypto):
    mult = ATR_MULT_CRYPTO if crypto else ATR_MULT_STOCK
    return round(max(STOP_WIDEST_PCT, min(STOP_TIGHTEST_PCT, -mult * atr_percent)), 2)


def _peak_since(yf_symbol, opened_at):
    """Prezzo massimo (chiusure orarie) dall'apertura della posizione, letto da yfinance."""
    if not opened_at:
        return None
    try:
        df = yf.Ticker(yf_symbol).history(start=opened_at.astimezone(dt.timezone.utc), interval="1h")
        return float(df["Close"].max()) if len(df) else None
    except Exception:
        return None


def volatility_agent(symbols, positions, cfg, log=print, ledger=None):
    """ATR, stop dinamico per ogni simbolo e trailing stop per le posizioni aperte (senza stato locale).

    - stop di una posizione: quello del CIO salvato nel client_order_id dell'acquisto, altrimenti da ATR;
    - picco per il trailing: massimo dei prezzi dall'apertura (data letta dagli ordini Alpaca).
    Restituisce (vol, stops, trailing).
    """
    vol = {}
    for sym in symbols:
        df = get_daily_bars(sym)
        if df is None:
            continue
        a = atr_pct(df)
        vol[normalize_symbol(sym)] = {"atr_pct": a, "stop_pct": dynamic_stop_pct(a, is_crypto(sym))}

    open_info = (ledger or {}).get("open", {})
    held = {normalize_symbol(p["symbol"]) for p in positions}
    stops, trailing, parts = {}, {}, []
    for p in positions:
        key = normalize_symbol(p["symbol"])
        v = vol.get(normalize_symbol(p["yf_symbol"]))
        info = open_info.get(key, {})
        stop = info.get("stop_pct") or (v["stop_pct"] if v else cfg["stop_loss_pct"])
        stops[key] = stop
        price, entry = p["current_price"], p.get("avg_entry_price") or p["current_price"]
        peak = max([x for x in (_peak_since(p["yf_symbol"], info.get("opened_at")), price, entry) if x] or [0.0])
        if v:
            trail_pct = (ATR_MULT_CRYPTO if p["is_crypto"] else ATR_MULT_STOCK) * v["atr_pct"]
            active = peak >= entry * (1 + trail_pct / 100)
            trigger = peak * (1 - trail_pct / 100)
            hit = active and price <= trigger
            trailing[key] = {
                "active": active, "hit": hit, "trigger": trigger,
                "reason": f"prezzo ${price:.2f} sotto il trailing stop ${trigger:.2f} (picco ${peak:.2f} - {trail_pct:.1f}%)",
            }
            parts.append(f"{p['symbol']} ATR {v['atr_pct']:.1f}% stop {stop:.1f}%"
                         + (" (CIO)" if info.get("stop_pct") else "")
                         + (f" trailing ${trigger:.2f}" if active else ""))
        else:
            parts.append(f"{p['symbol']} stop {stop:.1f}% (ATR N/D)")
    cands = [f"{v_sym} stop {v['stop_pct']:.1f}%" for v_sym, v in vol.items() if v_sym not in held]
    log(f"📏 [Volatilità] Posizioni: {'; '.join(parts) or '-'}" + (f" | Candidati: {', '.join(cands)}" if cands else ""))
    return vol, stops, trailing


# ---------------- Agente 4: Macro Regime Analyst ----------------
def macro_regime(log=print):
    """Regime di mercato: SPY (azioni) e BTC (crypto) rispetto alla SMA50 giornaliera."""
    out = {}
    for cls, sym in (("stock", "SPY"), ("crypto", "BTC-USD")):
        df = get_daily_bars(sym)
        if df is None:
            out[cls] = {"symbol": sym, "regime": "N/D", "factor": 1.0, "detail": "dati non disponibili"}
            continue
        price = float(df["Close"].iloc[-1])
        sma50 = float(df["Close"].rolling(50).mean().iloc[-1])
        risk_off = price < sma50
        out[cls] = {
            "symbol": sym, "regime": "RISK-OFF" if risk_off else "RISK-ON",
            "factor": MACRO_RISK_OFF_FACTOR if risk_off else 1.0,
            "detail": f"{sym} ${price:,.2f} {'<' if risk_off else '>'} SMA50 ${sma50:,.2f}",
        }
    log("🌍 [Macro] " + " | ".join(
        f"{'Azioni' if c == 'stock' else 'Crypto'}: {m['regime']} ({m['detail']})"
        + (" → budget -50%" if m["factor"] < 1 else "") for c, m in out.items()))
    return out


# ---------------- Agente 5: Volume & Liquidity ----------------
def volume_agent(analysis, log=print):
    """Segnala i falsi breakout: prezzo in salita (ROC > 0) con volume < 0.8x la media."""
    flags = {}
    for key, a in analysis.items():
        ratio, roc = a["ind"].get("vol_ratio"), a["ind"]["roc"]
        if ratio is None:
            status = "N/D"
        elif roc > 0 and ratio < VOLUME_LOW_RATIO:
            status = "FALSO_BREAKOUT"
        elif ratio >= 1.5:
            status = "VOLUMI_FORTI"
        else:
            status = "OK"
        flags[key] = {"ratio": ratio, "status": status}
    fake = [a["symbol"] for k, a in analysis.items() if flags[k]["status"] == "FALSO_BREAKOUT" and a["class"] == "BUY"]
    strong = [a["symbol"] for k, a in analysis.items() if flags[k]["status"] == "VOLUMI_FORTI"]
    log(f"📶 [Volumi] Falso breakout/bassa liquidità: {', '.join(fake) or '-'} | Volumi forti: {', '.join(strong) or '-'}")
    return flags


# ---------------- Agente 6: Drawdown & Risk Controller ----------------
def _intraday_equity_peak():
    """Massimo dell'equity di oggi dallo storico del portafoglio Alpaca (None se non disponibile)."""
    if not alpaca_client:
        return None
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        hist = alpaca_client.get_portfolio_history(GetPortfolioHistoryRequest(period="1D", timeframe="15Min"))
        values = [float(e) for e in (hist.equity or []) if e]
        return max(values) if values else None
    except Exception:
        return None


def drawdown_controller(account, state, log=print):
    """Perdita del giorno rispetto al massimo tra chiusura precedente e picco intraday (letto da Alpaca).

    Oltre DAILY_DRAWDOWN_LIMIT blocca i nuovi acquisti per DRAWDOWN_BLOCK_HOURS (solo vendite difensive).
    Il blocco vale comunque finché la perdita del giorno resta oltre il limite, anche dopo un deploy.
    """
    now = time.time()
    equity = float(account.get("portfolio", 0) or 0)
    last_equity = float(account.get("last_equity", 0) or 0) or equity
    peak = max([x for x in (last_equity, _intraday_equity_peak(), equity) if x] or [0.0])
    drawdown = (equity / peak - 1) * 100 if peak else 0.0
    dd_state = state.setdefault("drawdown", {})
    if drawdown <= DAILY_DRAWDOWN_LIMIT and now >= float(dd_state.get("block_until", 0)):
        dd_state["block_until"] = now + DRAWDOWN_BLOCK_HOURS * 3600
        log(f"🚫 [Drawdown] Perdita giornaliera {drawdown:.2f}% oltre {DAILY_DRAWDOWN_LIMIT:.0f}%: "
            f"acquisti bloccati per {DRAWDOWN_BLOCK_HOURS} ore.")
    remaining = max(0, float(dd_state.get("block_until", 0)) - now) / 3600
    blocked = remaining > 0 or drawdown <= DAILY_DRAWDOWN_LIMIT
    log(f"📉 [Drawdown] Oggi {drawdown:+.2f}% (capitale ${equity:,.0f}, riferimento ${peak:,.0f})"
        + (f" | ACQUISTI BLOCCATI ancora per {max(remaining, 0):.1f}h" if blocked else " | acquisti consentiti"))
    return {"drawdown_pct": round(drawdown, 2), "blocked": blocked, "hours_left": round(remaining, 1)}


# ---------------- Agente 7: Post-Trade Auditor ----------------
def sync_ledger(days=90, log=print):
    """Ricostruisce dagli ordini Alpaca eseguiti (FIFO) i trade chiusi e le posizioni aperte.

    Restituisce {"trades": [...], "open": {simbolo: {"opened_at", "stop_pct"}}} oppure None se Alpaca
    non risponde. I trade vengono salvati in trade_history.json (solo come copia: la fonte è Alpaca).
    """
    if not alpaca_client:
        return None
    from datetime import datetime, timedelta, timezone
    try:
        orders = alpaca_client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, limit=500, direction="asc",
            after=datetime.now(timezone.utc) - timedelta(days=days)))
    except Exception as e:
        log(f"Errore lettura storico ordini: {e}")
        return None

    lots, trades = {}, []
    for o in orders:
        qty = float(o.filled_qty or 0)
        price = float(o.filled_avg_price or 0)
        if qty <= 0 or price <= 0:
            continue
        key = normalize_symbol(o.symbol)
        side = str(getattr(o.side, "value", o.side)).lower()
        filled_at = o.filled_at.astimezone(TIMEZONE) if hasattr(o.filled_at, "astimezone") else None
        if side == "buy":
            m = _ORDER_STOP_RE.match(o.client_order_id or "")
            stop = -int(m.group(1)) / 100 if m and int(m.group(1)) > 0 else None
            lots.setdefault(key, []).append([qty, price, filled_at, stop])
            continue
        remaining, cost, matched = qty, 0.0, 0.0
        queue = lots.get(key, [])
        while remaining > 1e-9 and queue:
            take = min(remaining, queue[0][0])
            cost += take * queue[0][1]
            matched += take
            remaining -= take
            queue[0][0] -= take
            if queue[0][0] <= 1e-9:
                queue.pop(0)
        # Residui dovuti alle commissioni crypto (trattenute nella moneta): se dopo la vendita resta
        # meno dell'1% di quanto venduto, la posizione è chiusa e i lotti vengono azzerati
        if queue and sum(lot[0] for lot in queue) <= qty * 0.01:
            queue.clear()
        if matched > 0:
            entry = cost / matched
            trades.append({
                "symbol": o.symbol, "qty": round(matched, 8), "entry": round(entry, 6), "exit": round(price, 6),
                "pnl": round((price - entry) * matched, 2), "pnl_pct": round((price / entry - 1) * 100, 2),
                "closed_at": filled_at.strftime("%Y-%m-%d %H:%M:%S") if filled_at else str(o.filled_at)[:19],
            })
    open_info = {}
    for key, queue in lots.items():
        if queue:
            stops = [lot[3] for lot in queue if lot[3]]
            open_info[key] = {"opened_at": queue[0][2], "stop_pct": stops[-1] if stops else None}
    write_json_file(TRADE_HISTORY_PATH, trades)
    return {"trades": trades, "open": open_info}


def rebuild_trade_history(days=90, log=print):
    """Compatibilità: solo l'elenco dei trade chiusi."""
    ledger = sync_ledger(days, log)
    return ledger["trades"] if ledger else None


def win_rates(trades):
    stats = {}
    for t in trades or []:
        if not isinstance(t, dict) or "symbol" not in t or "pnl" not in t:
            continue
        s = stats.setdefault(normalize_symbol(t["symbol"]), {"trades": 0, "wins": 0, "pnl": 0.0})
        s["trades"] += 1
        s["wins"] += 1 if t["pnl"] > 0 else 0
        s["pnl"] = round(s["pnl"] + t["pnl"], 2)
    for s in stats.values():
        s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1)
    return stats


def post_trade_auditor(analysis, log=print, ledger=None):
    """Penalizza lo score dei ticker con win rate < 30% (almeno 3 trade chiusi)."""
    trades = ledger["trades"] if ledger else read_json_file(TRADE_HISTORY_PATH, [])
    if not ledger:
        log("🧾 [Auditor] Alpaca non disponibile: uso la copia locale di trade_history.json.")
    stats = win_rates(trades)
    penalized = []
    for key, a in analysis.items():
        s = stats.get(key)
        if s and s["trades"] >= AUDIT_MIN_TRADES and s["win_rate"] < AUDIT_LOW_WINRATE:
            a["score"] = max(0, a["score"] - AUDIT_PENALTY)
            a["class"] = classify_score(a["score"])
            a["audit_penalty"] = AUDIT_PENALTY
            penalized.append(f"{a['symbol']} (win rate {s['win_rate']:.0f}% su {s['trades']})")
    total = len(trades)
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    pnl = sum(t.get("pnl", 0) for t in trades)
    log(f"🧾 [Auditor] {total} trade chiusi (90gg), win rate {wins / total * 100 if total else 0:.0f}%, "
        f"PnL realizzato ${pnl:,.2f}" + (f" | Penalità -{AUDIT_PENALTY}: {', '.join(penalized)}" if penalized else ""))
    return stats


# ---------------- Agente 8: Chief Investment Officer ----------------
CIO_SYSTEM_PROMPT = (
    "Sei il Chief Investment Officer dell'Ufficio Virtuale e del Virtual Boardroom Finanziario di un bot di trading algoritmico "
    "che opera su un conto paper (simulato) Alpaca. Le tue risposte vengono lette da un programma: "
    "rispondi SOLO con un oggetto JSON valido, senza testo prima o dopo. Scrivi il campo reason in italiano."
)


def build_cio_prompt(board, cfg):
    """Matrice dei report dei 7 agenti per il CIO."""
    risk, macro, dd = board["risk"], board["macro"], board["drawdown"]
    vol, sent, volume, stats = board["volatility"], board["sentiment"], board["volume"], board["audit"]

    def row(key, a):
        v, s, vf, st = vol.get(key), sent.get(key), volume.get(key, {}), stats.get(key)
        ind = a["ind"]
        return (
            f"score {a['score']}{' (penalità auditor)' if a.get('audit_penalty') else ''}, "
            f"RSI {ind['rsi']:.1f}, MACD hist {ind['macd_hist']:.4f}, ROC {ind['roc']:.2f}%, "
            f"SMA20 {'>' if ind['sma20'] > ind['sma50'] else '<'} SMA50 | "
            f"sentiment {s['sentiment']:+d}{' VETO' if s['veto'] else ''} | " if s else
            f"score {a['score']}, RSI {ind['rsi']:.1f}, ROC {ind['roc']:.2f}% | sentiment N/D | "
        ) + (
            f"ATR {v['atr_pct']:.1f}% (stop {v['stop_pct']:.1f}%) | " if v else "ATR N/D | "
        ) + (
            f"volume {vf.get('ratio')}x {vf.get('status')} | "
        ) + (
            f"win rate {st['win_rate']:.0f}% su {st['trades']} trade" if st else "nessuno storico"
        )

    pos_lines = []
    for r in risk["positions"]:
        p, a = r["pos"], r["analysis"]
        key = normalize_symbol(p["yf_symbol"])
        detail = row(key, a) if a else "indicatori N/D"
        pos_lines.append(f"  - {p['yf_symbol']}: valore ${p['market_value']:,.0f}, PnL {p['unrealized_plpc']:.2f}%, "
                         f"stato {r['status']} ({r['reason']}) | {detail}")
    cand_lines = [f"  - {a['symbol']}{' [ESPLORATORE #1]' if a.get('scout') else ''}: {row(normalize_symbol(a['symbol']), a)}"
                  for a in board["candidates"][:8]]
    scout = board.get("scout") or {}
    scout_lines = [
        f"  - {d['symbol']}: score {d['score']}, anomalie: {', '.join(d['anomalies'])} → Reparto Revisione: "
        f"{(board.get('review') or {}).get(normalize_symbol(d['symbol']), {}).get('verdict', 'N/D')} "
        f"({(board.get('review') or {}).get(normalize_symbol(d['symbol']), {}).get('detail', '')})"
        for d in scout.get("discoveries", [])
    ]
    excluded = [f"{sym} ({why})" for sym, why in board["excluded"]]
    f_stock, f_crypto = risk["funds"]["stock"][0], risk["funds"]["crypto"][0]
    return (
        "Sei il CIO dell'Ufficio Virtuale. Ricevi dal tuo Agente Esploratore #1 nuove proposte scovate sui mercati "
        "globali (metalli, obbligazioni, ETF) filtrate dal Reparto Revisione.\n"
        "Valuta se fare una ROTAZIONE DEL CAPITALE liquidando una posizione in stallo per investire nella scoperta "
        "dell'Esploratore.\n\n"
        f"[Esploratore #1] Settore perlustrato: {scout.get('sector_scanned', 'N/D')} | ticker ispezionati: "
        f"{', '.join(scout.get('tickers_inspected', [])) or '-'}\n"
        f"Scoperte:\n{chr(10).join(scout_lines) or '  (nessuna anomalia eccezionale)'}\n\n"
        "Hai ricevuto anche le analisi dettagliate dei 7 agenti del tuo comitato:\n"
        "1. Tecnico (RSI/MACD)\n2. Sentiment News (Veto attivo?)\n3. ATR (Stop Loss %)\n4. Macro (Regime Mercato)\n"
        "5. Volume (Conferma Volumi)\n6. Drawdown (Rischio Globale)\n7. Auditor (Win Rate Storico)\n\n"
        f"[Macro] Azioni: {macro['stock']['regime']} ({macro['stock']['detail']}); "
        f"Crypto: {macro['crypto']['regime']} ({macro['crypto']['detail']})\n"
        f"[Drawdown] Oggi {dd['drawdown_pct']:+.2f}%, acquisti {'BLOCCATI' if dd['blocked'] else 'consentiti'}\n"
        f"[Conto] Capitale ${risk['equity']:,.0f}, esposizione ${risk['exposure']:,.0f}, "
        f"liquidità disponibile azioni ${f_stock:,.0f}, crypto ${f_crypto:,.0f}\n"
        f"Posizioni aperte:\n{chr(10).join(pos_lines) or '  (nessuna)'}\n"
        f"Candidati all'acquisto ammessi dal comitato:\n{chr(10).join(cand_lines) or '  (nessuno)'}\n"
        f"Esclusi dal comitato: {', '.join(excluded) or 'nessuno'}\n\n"
        "Regole del boardroom:\n"
        "- Se c'è liquidità disponibile (almeno $10) e c'è almeno un candidato ammesso, scegli BUY del migliore: "
        "il capitale libero va investito. Non confrontare i candidati con le posizioni già aperte. "
        "Usa HOLD solo per motivi concreti citati dagli agenti.\n"
        f"- ROTATE solo se la liquidità è insufficiente (< ${ROTATION_FUNDS_THRESHOLD}), buy_symbol ha score > "
        f"{ROTATION_MIN_SCORE} e almeno {ROTATION_MIN_EDGE} punti più di sell_symbol (preferisci posizioni deboli o in stallo).\n"
        "- SELL per chiudere una posizione debole; le vendite per stop loss, trailing stop, trend ribassista "
        "e stallo sono già eseguite dal Risk Manager.\n"
        f"- allocation_pct tra {cfg['base_allocation_pct']:.0f} e {cfg['max_allocation_pct']:.0f} in base alla confidenza "
        "(il regime macro RISK-OFF dimezza automaticamente il budget).\n"
        f"- dynamic_stop_loss_pct negativo, coerente con l'ATR (tra {STOP_WIDEST_PCT:.0f} e {STOP_TIGHTEST_PCT:.0f}).\n\n"
        "- Le scoperte dell'Esploratore sono acquistabili solo se compaiono tra i candidati ammessi "
        "(approvate dal Reparto Revisione).\n\n"
        "Restituisci la risposta in formato JSON pulito:\n"
        '{\n  "action": "BUY" | "SELL" | "ROTATE" | "HOLD",\n  "sell_symbol": "TICKER_DA_VENDERE",\n'
        '  "buy_symbol": "TICKER_PROPOSTO_DA_COMPRARE",\n  "allocation_pct": 15_a_30,\n'
        '  "dynamic_stop_loss_pct": valore_numerico_negativo,\n'
        '  "scout_discovery_approved": true|false,\n'
        '  "reason": "Motivazione esecutiva della decisione dell\'Ufficio Virtuale"\n}\n'
        "scout_discovery_approved = true solo se buy_symbol è una scoperta dell'Esploratore #1.\n"
        "Usa i ticker esattamente come scritti sopra e stringa vuota per i campi non usati."
    )


def cio_allocation(decision, analysis_score, cfg, macro_factor):
    """Percentuale del capitale per il BUY: quella del CIO (limitata a base..max) o quella da score."""
    pct = decision.get("allocation_pct")
    if pct is None:
        pct = allocation_pct_for_score(decision.get("score") or analysis_score, cfg)
    pct = max(cfg["base_allocation_pct"], min(cfg["max_allocation_pct"], pct))
    return pct, pct * macro_factor


def cio_stop(decision, vol_info):
    """Stop per la nuova posizione: quello del CIO entro i limiti, altrimenti da ATR."""
    stop = decision.get("dynamic_stop_loss_pct")
    if stop is not None and stop > 0:
        stop = -stop
    if stop is None or stop == 0:
        return vol_info["stop_pct"] if vol_info else None
    return round(max(STOP_WIDEST_PCT, min(STOP_TIGHTEST_PCT, stop)), 2)


# ===========================================================================
# AVVIO: sincronizzazione con Alpaca (unica fonte di verità)
# ===========================================================================
STARTUP_GRACE_SECONDS = 10


def startup_system_sync(log=print):
    """Eseguita all'avvio del server, dopo il grace period e prima del primo ciclo.

    - legge da Alpaca conto, posizioni e ordini aperti (nessuno stato locale viene considerato);
    - annulla gli ordini di ACQUISTO rimasti aperti dal deploy precedente (il ciclo di avvio non compra);
    - mantiene gli ordini di VENDITA aperti (vendite difensive, es. stop loss in attesa dell'apertura).
    """
    if not alpaca_client:
        log("🔄 [Sync] Credenziali Alpaca non configurate: sincronizzazione saltata.")
        return None
    summary = {"cancelled": [], "kept": []}
    try:
        acc = alpaca_client.get_account()
        positions = alpaca_client.get_all_positions()
        orders = alpaca_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    except Exception as e:
        log(f"🔄 [Sync] Alpaca non raggiungibile all'avvio: {e}. Riprovo al primo ciclo.")
        return None
    for o in orders:
        side = str(getattr(o.side, "value", o.side)).lower()
        label = f"{side.upper()} {o.symbol} ({o.notional and f'${float(o.notional):,.2f}' or o.qty})"
        if side == "buy":
            try:
                alpaca_client.cancel_order_by_id(o.id)
                summary["cancelled"].append(label)
            except Exception as e:
                log(f"🔄 [Sync] Impossibile annullare {label}: {e}")
        else:
            summary["kept"].append(label)
    exposure = sum(abs(float(p.market_value)) for p in positions)
    log(f"🔄 [Sync] Stato Alpaca: capitale ${float(acc.equity):,.0f}, cash ${float(acc.cash):,.0f}, "
        f"{len(positions)} posizioni (${exposure:,.0f}), {len(orders)} ordini aperti")
    if summary["cancelled"]:
        log(f"🔄 [Sync] Annullati acquisti pendenti dal deploy precedente: {', '.join(summary['cancelled'])}")
    if summary["kept"]:
        log(f"🔄 [Sync] Vendite pendenti mantenute: {', '.join(summary['kept'])}")
    return summary


# ===========================================================================
# UFFICIO VIRTUALE: Agente Esploratore #1 e registro di coordinamento
# ===========================================================================
SCOUT_ID = "Esploratore_1"
SCOUT_REGISTRY_PATH = os.path.join(DATA_DIR, "scout_registry.json")
SCOUT_SECTORS = {
    "Metalli preziosi & Materie prime": ["GLD", "SLV", "USO", "COPX"],
    "Obbligazioni & T-Bills": ["TLT", "BND"],
    "ETF settoriali ad alta crescita": ["SMH", "XLE", "ARKK"],
    "Crypto (top gainer e breakout di volume)": ["LINK-USD", "DOGE-USD", "LTC-USD", "XRP-USD", "ADA-USD",
                                                  "DOT-USD", "AAVE-USD", "BCH-USD"],
}
SCOUT_MAX_PICKS = 2
SCOUT_VOLUME_ANOMALY = 1.5      # volume >= 1.5x la media della stessa ora
SCOUT_EXPLOSIVE_ROC = 3.0       # ROC(10) >= 3% = trend esplosivo
SCOUT_SECTOR_LOCK_MIN = 30      # un settore ispezionato da un altro esploratore è riservato per 30 minuti
SCOUT_HISTORY_MAX = 50
_SCOUT_REGISTRY_DEFAULT = {"scouts": {}, "history": []}


def load_scout_registry():
    """Registro degli esploratori; se manca o è corrotto viene rigenerato con la struttura di default."""
    reg = read_json_file(SCOUT_REGISTRY_PATH, _SCOUT_REGISTRY_DEFAULT)
    if not isinstance(reg.get("scouts"), dict) or not isinstance(reg.get("history"), list):
        reg = json.loads(json.dumps(_SCOUT_REGISTRY_DEFAULT))
        write_json_file(SCOUT_REGISTRY_PATH, reg)
    return reg


def _parse_ts(value):
    try:
        return dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def choose_scout_sector(registry, scout_id, market_open):
    """Settore ispezionato meno di recente, escludendo quelli riservati da altri esploratori.

    A mercato azionario chiuso solo le crypto (le uniche acquistabili).
    """
    now = now_local()
    last_scan, claimed = {}, set()
    for entry in registry["history"]:
        ts = _parse_ts(entry.get("timestamp"))
        sector = entry.get("sector_scanned")
        if not ts or sector not in SCOUT_SECTORS:
            continue
        last_scan[sector] = max(last_scan.get(sector, ts), ts)
        if entry.get("scout_id") != scout_id and (now - ts).total_seconds() < SCOUT_SECTOR_LOCK_MIN * 60:
            claimed.add(sector)
    sectors = [s for s in SCOUT_SECTORS if s not in claimed]
    if not market_open:
        sectors = [s for s in sectors if all(is_crypto(t) for t in SCOUT_SECTORS[s])]
    if not sectors:
        return None
    oldest = dt.datetime.min.replace(tzinfo=TIMEZONE)
    return min(sectors, key=lambda s: last_scan.get(s, oldest))


def run_esploratore_scout(exclude_keys=(), market_open=True, log=print, scout_id=SCOUT_ID):
    """Agente Esploratore #1: perlustra un settore fuori dalla watchlist e propone fino a 2 anomalie.

    Un ticker è una scoperta se ha Score di Forza > SCORE_BUY e almeno un'anomalia: volume >= 1.5x
    (stessa ora) o trend esplosivo (ROC >= 3%). Ricerca e scoperte vengono scritte in scout_registry.json.
    Restituisce (voce del registro, scoperte con indicatori).
    """
    registry = load_scout_registry()
    sector = choose_scout_sector(registry, scout_id, market_open)
    if not sector:
        log(f"🔍 [{scout_id}] Nessun settore disponibile (riservati da altri esploratori o mercato chiuso).")
        return None, []

    inspected, picks = [], []
    for ticker in SCOUT_SECTORS[sector]:
        if normalize_symbol(ticker) in exclude_keys:
            continue
        ind = get_indicators(ticker)
        if not ind:
            continue
        score = ta_score(ind)
        inspected.append(ticker)
        anomalies = []
        if ind.get("vol_ratio") is not None and ind["vol_ratio"] >= SCOUT_VOLUME_ANOMALY:
            anomalies.append(f"volume {ind['vol_ratio']}x")
        if ind["roc"] >= SCOUT_EXPLOSIVE_ROC:
            anomalies.append(f"trend esplosivo ROC {ind['roc']:+.2f}%")
        if anomalies and score > SCORE_BUY:
            picks.append({"symbol": ticker, "ind": ind, "score": score, "class": classify_score(score),
                          "anomalies": anomalies, "scout": True})
    picks = sorted(picks, key=lambda p: p["score"], reverse=True)[:SCOUT_MAX_PICKS]

    entry = {
        "scout_id": scout_id,
        "sector_scanned": sector,
        "tickers_inspected": inspected,
        "timestamp": now_local().isoformat(timespec="seconds"),
        "discoveries": [{"symbol": p["symbol"], "score": p["score"], "roc": p["ind"]["roc"],
                         "vol_ratio": p["ind"].get("vol_ratio"), "anomalies": p["anomalies"]} for p in picks],
        "status": "Inviato al Reparto Revisione" if picks else "Nessuna anomalia eccezionale",
        "review": {},
        "cio": None,
    }
    registry["scouts"][scout_id] = entry
    registry["history"] = (registry["history"] + [entry])[-SCOUT_HISTORY_MAX:]
    write_json_file(SCOUT_REGISTRY_PATH, registry)

    found = ", ".join(f"{p['symbol']} (score {p['score']}, {' + '.join(p['anomalies'])})" for p in picks)
    log(f"🔍 [{scout_id}] Settore: {sector} | ispezionati: {', '.join(inspected) or '-'} | "
        + (f"scoperte → Reparto Revisione: {found}" if picks else "nessuna anomalia eccezionale"))
    return entry, picks


def update_scout_registry(scout_id, review, cio):
    """Registra nel registro l'esito del Reparto Revisione e la decisione del CIO sull'ultima ricerca."""
    registry = load_scout_registry()
    entry = registry["scouts"].get(scout_id)
    if not entry:
        return
    entry["review"] = review
    entry["cio"] = cio
    if not entry["discoveries"]:
        pass
    elif cio and cio.get("approved"):
        entry["status"] = "Approvato dal CIO"
    elif not any(v.get("verdict") == "APPROVATO" for v in review.values()):
        entry["status"] = "Respinto dal Reparto Revisione"
    else:
        entry["status"] = "Respinto dal CIO"
    for i in range(len(registry["history"]) - 1, -1, -1):
        h = registry["history"][i]
        if h.get("scout_id") == scout_id and h.get("timestamp") == entry["timestamp"]:
            registry["history"][i] = entry
            break
    write_json_file(SCOUT_REGISTRY_PATH, registry)


# ===========================================================================
# P&L del conto
# ===========================================================================
_initial_capital_cache = {"ts": 0.0, "value": None}


def initial_capital():
    """Capitale iniziale del conto: BOT_INITIAL_CAPITAL, altrimenti base_value dello storico Alpaca (cache 1h)."""
    env = os.getenv("BOT_INITIAL_CAPITAL")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    if time.time() - _initial_capital_cache["ts"] < 3600 and _initial_capital_cache["value"]:
        return _initial_capital_cache["value"]
    if not alpaca_client:
        return None
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        hist = alpaca_client.get_portfolio_history(GetPortfolioHistoryRequest(period="all", timeframe="1D"))
        value = float(hist.base_value) if hist.base_value else None
    except Exception:
        value = None
    _initial_capital_cache.update(ts=time.time(), value=value)
    return value


def pnl_summary(equity, last_equity):
    """P&L netto dall'inizio e P&L del giorno, in $ e %."""
    base = initial_capital()
    out = {"initial_capital": base, "net_pnl_usd": None, "net_pnl_pct": None,
           "daily_pnl_usd": None, "daily_pnl_pct": None}
    if base:
        out["net_pnl_usd"] = round(equity - base, 2)
        out["net_pnl_pct"] = round((equity / base - 1) * 100, 3)
    if last_equity:
        out["daily_pnl_usd"] = round(equity - last_equity, 2)
        out["daily_pnl_pct"] = round((equity / last_equity - 1) * 100, 3)
    return out
