"""Dynamic Market Universe Screener: l'universo dello sciame costruito dal mercato, non da panieri statici.

Azioni USA (negoziabili su Alpaca, prezzo >= $5):
  - S&P 500 (CSV pubblico datasets/s-and-p-500-companies) e Nasdaq-100 (API di nasdaq.com);
  - titoli più attivi e in rialzo del giorno (screener Yahoo Finance e Market Movers di Alpaca).
Crypto (SOLO le coppie /USD negoziabili su Alpaca):
  - elenco degli asset crypto attivi e tradable di Alpaca, ordinati per volume 24h di Coinbase Exchange
    e Binance (ticker 24h, con Binance.US come riserva). Le crypto non negoziabili su Alpaca sono escluse
    dall'universo: gli Scout scansionano solo asset su cui il CIO può inviare ordini reali.

Ogni fonte ha la sua cadenza di aggiornamento; se una fonte non risponde si tiene l'ultimo elenco valido,
salvato su disco (universe_cache.json) così sopravvive anche ai riavvii.
Finviz non è usato: la sua API richiede un abbonamento a pagamento.
"""
import json
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

HTTP_TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (quant-desk universe screener)", "Accept": "application/json, text/plain, */*"}
STOCK_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
CRYPTO_BASE_RE = re.compile(r"^[A-Z0-9]{2,12}$")
# Stablecoin, valute fiat e token a leva: nessun segnale direzionale utile
CRYPTO_EXCLUDED = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDP", "PYUSD", "USDE", "USDS", "USDG", "GUSD", "EURC", "EUR", "GBP",
    "AUD", "TRY", "BRL", "UST", "BUSD", "USD1", "RLUSD", "XUSD", "AEUR", "EURI", "WBTC", "WETH", "CBETH", "STETH",
}
# Crypto negoziabili su Alpaca (coppie /USD): usate solo se l'elenco live degli asset Alpaca non è disponibile
ALPACA_CRYPTO_FALLBACK = {
    "AAVE", "ADA", "ARB", "AVAX", "BAT", "BCH", "BONK", "BTC", "CRV", "DOGE", "DOT", "ETH", "FIL", "GRT", "HYPE", "LDO",
    "LINK", "LTC", "ONDO", "PAXG", "PEPE", "POL", "RENDER", "SHIB", "SKY", "SOL", "SUSHI", "TRUMP", "UNI", "WIF", "XRP",
    "XTZ", "YFI",
}
USD_QUOTES = ("FDUSD", "BUSD", "TUSD", "USDT", "USDC", "USD")   # quote equivalenti al dollaro su Binance
YAHOO_SCREENS = ("most_actives", "day_gainers", "small_cap_gainers", "aggressive_small_caps", "growth_technology_stocks")

# Cadenze di aggiornamento delle fonti (secondi)
REFRESH = {"sp500": 12 * 3600, "nasdaq100": 12 * 3600, "yahoo": 15 * 60, "alpaca_movers": 15 * 60,
           "coinbase": 30 * 60, "binance": 30 * 60, "alpaca_assets": 6 * 3600}


class DynamicUniverseScreener:
    def __init__(self, cache_path: str, alpaca_client=None, alpaca_keys: Tuple[Optional[str], Optional[str]] = (None, None),
                 min_crypto_volume_usd: float = 1_000_000.0, min_price: float = 5.0, screen_count: int = 250,
                 log: Callable[[str], Any] = print):
        self.cache_path = cache_path
        self.alpaca_client = alpaca_client
        self.alpaca_keys = alpaca_keys
        self.min_crypto_volume_usd = min_crypto_volume_usd
        self.min_price = min_price
        self.screen_count = screen_count
        self.log = log
        self._lock = threading.Lock()
        self._sources: Dict[str, Dict[str, Any]] = self._load_cache()
        self.cursor = 0
        self.cycles = 0

    # ------------------------------------------------------------------ cache su disco
    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._sources, f)
            os.replace(tmp, self.cache_path)
        except OSError as e:
            self.log(f"⚠️ [UNIVERSE SCREENER] Cache non salvata: {e}")

    def _refresh_source(self, name: str, fetch: Callable[[], Any], force: bool) -> None:
        entry = self._sources.get(name) or {}
        if not force and entry.get("data") is not None and time.time() - entry.get("ts", 0) < REFRESH[name]:
            return
        started = time.time()
        try:
            data = fetch()
            if not data:
                raise ValueError("risposta vuota")
            self._sources[name] = {"ts": time.time(), "data": data, "error": None,
                                   "elapsed_s": round(time.time() - started, 1)}
        except Exception as e:
            # Fonte non disponibile: si tiene l'ultimo elenco valido (anche da un avvio precedente)
            self._sources[name] = {**entry, "error": f"{type(e).__name__}: {str(e)[:120]}", "ts_error": time.time()}
            self.log(f"⚠️ [UNIVERSE SCREENER] Fonte {name} non disponibile ({type(e).__name__}): "
                     + ("uso l'ultimo elenco valido" if entry.get("data") else "nessun elenco precedente"))

    # ------------------------------------------------------------------ fonti azionarie
    @staticmethod
    def _sp500() -> List[str]:
        csv = requests.get("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
                           timeout=HTTP_TIMEOUT, headers=HEADERS)
        csv.raise_for_status()
        return [line.split(",")[0].strip().upper() for line in csv.text.splitlines()[1:] if line.strip()]

    @staticmethod
    def _nasdaq100() -> List[str]:
        r = requests.get("https://api.nasdaq.com/api/quote/list-type/nasdaq100", timeout=HTTP_TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        return [row["symbol"].strip().upper() for row in r.json()["data"]["data"]["rows"]]

    def _yahoo(self) -> Dict[str, List[str]]:
        import yfinance as yf
        out = {}
        for screen in YAHOO_SCREENS:
            try:
                quotes = yf.screen(screen, count=self.screen_count).get("quotes", [])
            except Exception:
                continue
            out[screen] = [q["symbol"] for q in quotes
                           if STOCK_RE.match(q.get("symbol", "")) and (q.get("regularMarketPrice") or 0) >= self.min_price]
        return out

    def _alpaca_movers(self) -> List[str]:
        key, secret = self.alpaca_keys
        if not key or not secret:
            return []
        from alpaca.data.historical.screener import ScreenerClient
        from alpaca.data.requests import MarketMoversRequest
        movers = ScreenerClient(key, secret).get_market_movers(MarketMoversRequest(top=50))
        return [m.symbol for m in list(movers.gainers) + list(movers.losers)
                if STOCK_RE.match(m.symbol) and (m.price or 0) >= self.min_price]

    def _alpaca_assets(self) -> Dict[str, List[str]]:
        if not self.alpaca_client:
            return {}
        from alpaca.trading.enums import AssetClass, AssetStatus
        from alpaca.trading.requests import GetAssetsRequest
        eq = self.alpaca_client.get_all_assets(GetAssetsRequest(asset_class=AssetClass.US_EQUITY, status=AssetStatus.ACTIVE))
        cr = self.alpaca_client.get_all_assets(GetAssetsRequest(asset_class=AssetClass.CRYPTO, status=AssetStatus.ACTIVE))
        return {"equity": sorted(a.symbol for a in eq if a.tradable),
                "crypto": sorted(a.symbol.split("/")[0] for a in cr if a.tradable and a.symbol.endswith("/USD"))}

    # ------------------------------------------------------------------ fonti crypto
    def _coinbase(self) -> Dict[str, float]:
        products = requests.get("https://api.exchange.coinbase.com/products", timeout=HTTP_TIMEOUT, headers=HEADERS).json()
        stats = requests.get("https://api.exchange.coinbase.com/products/stats", timeout=HTTP_TIMEOUT, headers=HEADERS).json()
        out: Dict[str, float] = {}
        for p in products:
            if (p.get("quote_currency") not in ("USD", "USDT", "USDC") or p.get("trading_disabled")
                    or p.get("status") != "online" or p.get("fx_stablecoin")):
                continue
            day = (stats.get(p["id"]) or {}).get("stats_24hour") or {}
            try:
                usd = float(day.get("volume") or 0) * float(day.get("last") or 0)
            except (TypeError, ValueError):
                continue
            base = p["base_currency"].upper()
            out[base] = out.get(base, 0.0) + usd
        return out

    def _binance(self) -> Dict[str, float]:
        last_error = None
        for url in ("https://api.binance.com/api/v3/ticker/24hr", "https://api.binance.us/api/v3/ticker/24hr"):
            try:
                r = requests.get(url, timeout=HTTP_TIMEOUT, headers=HEADERS)
                r.raise_for_status()     # Binance.com risponde 451 dagli Stati Uniti: si prova Binance.US
                out: Dict[str, float] = {}
                for t in r.json():
                    sym = t.get("symbol", "")
                    # Le quote più lunghe per prime: "XYZFDUSD" non deve diventare base "XYZFD" con quote "USD"
                    for quote in USD_QUOTES:
                        if sym.endswith(quote):
                            base = sym[: -len(quote)]
                            if base.endswith(("UP", "DOWN", "BULL", "BEAR")) and len(base) > 4:
                                break   # token a leva
                            out[base] = out.get(base, 0.0) + float(t.get("quoteVolume") or 0)
                            break
                return out
            except Exception as e:
                last_error = e
        raise last_error or RuntimeError("Binance non raggiungibile")

    # ------------------------------------------------------------------ universo
    def refresh(self, force: bool = False) -> Dict[str, Any]:
        """Aggiorna le fonti scadute e restituisce lo snapshot dell'universo."""
        with self._lock:
            for name, fetch in (("alpaca_assets", self._alpaca_assets), ("sp500", self._sp500),
                                ("nasdaq100", self._nasdaq100), ("yahoo", self._yahoo),
                                ("alpaca_movers", self._alpaca_movers), ("coinbase", self._coinbase),
                                ("binance", self._binance)):
                self._refresh_source(name, fetch, force)
            self._save_cache()
            return self.snapshot()

    def _data(self, name: str, default):
        return (self._sources.get(name) or {}).get("data") or default

    def snapshot(self) -> Dict[str, Any]:
        assets = self._data("alpaca_assets", {})
        tradable_eq = set(assets.get("equity") or [])
        tradable_crypto = set(assets.get("crypto") or []) or ALPACA_CRYPTO_FALLBACK

        stocks: Dict[str, str] = {}
        def add(symbols, source):
            for s in symbols:
                s = s.upper().replace("-", ".")
                if STOCK_RE.match(s) and s not in stocks and (not tradable_eq or s in tradable_eq):
                    stocks[s] = source
        add(self._data("sp500", []), "S&P 500")
        add(self._data("nasdaq100", []), "Nasdaq-100")
        for screen, symbols in self._data("yahoo", {}).items():
            add(symbols, f"Yahoo {screen.replace('_', ' ')}")
        add(self._data("alpaca_movers", []), "Alpaca movers")

        volumes: Dict[str, float] = {}
        for name in ("coinbase", "binance"):
            for base, usd in self._data(name, {}).items():
                volumes[base] = max(volumes.get(base, 0.0), float(usd))
        # Solo crypto negoziabili su Alpaca (stablecoin escluse), ordinate per volume 24h sugli exchange:
        # restano nell'universo anche se gli exchange non rispondono o il volume è sotto soglia
        bases = [b for b in tradable_crypto - CRYPTO_EXCLUDED if not b.startswith("USD") and CRYPTO_BASE_RE.match(b)]
        crypto = [{"symbol": f"{b}-USD", "base": b, "volume_usd": round(volumes[b]) if b in volumes else None,
                   "tradable": True}
                  for b in sorted(bases, key=lambda b: (-volumes.get(b, 0.0), b))]
        return {
            "stocks": [{"symbol": s, "source": src} for s, src in stocks.items()],
            "crypto": crypto,
            "sources": {n: {"count": len(v.get("data") or []) if not isinstance(v.get("data"), dict)
                            else sum(len(x) for x in v["data"].values()) if n in ("yahoo", "alpaca_assets") else len(v["data"]),
                            "age_min": round((time.time() - v.get("ts", 0)) / 60, 1) if v.get("ts") else None,
                            "error": v.get("error")}
                        for n, v in self._sources.items()},
        }

    def tickers(self, snap: Dict[str, Any], market_open: bool) -> List[Tuple[str, str, bool]]:
        """[(ticker, fonte, negoziabile)] in ordine di scansione: a mercato chiuso solo crypto (24/7)."""
        crypto = [(c["symbol"], "Crypto (Alpaca)", True) for c in snap["crypto"] if c["tradable"]]
        if not market_open:
            return crypto
        stocks = [(s["symbol"], s["source"], True) for s in snap["stocks"]]
        # Alterna azioni e crypto: ogni blocco contiene entrambe le classi
        ratio = max(1, len(stocks) // max(1, len(crypto)))
        out, ci = [], 0
        for i, s in enumerate(stocks):
            out.append(s)
            if (i + 1) % ratio == 0 and ci < len(crypto):
                out.append(crypto[ci])
                ci += 1
        return out + crypto[ci:]

    def next_chunk(self, universe: List[Tuple[str, str, bool]], size: int) -> Tuple[List[Tuple[str, str, bool]], int, int]:
        """Blocco successivo della rotazione continua: (ticker, numero del blocco, blocchi per giro completo)."""
        if not universe:
            return [], 0, 0
        total_chunks = (len(universe) + size - 1) // size
        with self._lock:
            start = self.cursor % len(universe)
            self.cursor = start + size
            if self.cursor >= len(universe):
                self.cursor = 0
                self.cycles += 1
        chunk = universe[start:start + size]
        return chunk, start // size + 1, total_chunks
