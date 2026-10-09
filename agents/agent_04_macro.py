"""AGENTE #4: Macro, News Radar & Catalyst Validator.

Due compiti:
1. Contesto macro (VIX / stress cross-asset, blackout eventi, banche centrali): veto di panico come prima.
2. Multi-Channel News Radar: titoli in tempo reale da Finnhub, Polygon, RSS (Yahoo Finance) e SEC EDGAR
   (8-K), valutati da Groq con un prompt a output JSON rigoroso:
       {"impact_score": -1.0..+1.0, "novelty_index_minutes": int,
        "catalyst_type": "EARNINGS" | "M&A" | "REGULATORY" | "PRODUCT" | "MACRO",
        "thesis_summary": "max 15 parole"}
   - notizie più vecchie di 30 minuti (novelty > 30) valgono Impact 0;
   - Groq fa da VALIDATORE e FILTRO DI VETO: spinta quantitativa alta ma notizia negativa, assente o
     speculativa -> VETO;
   - Groq in timeout (limite di 2.0 s imposto dall'Agente #7) -> News Score 0 (neutro), il ciclo non si blocca.
I fetcher HTTP e il client LLM sono iniettabili: i test offline girano senza rete.
"""
import email.utils
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

CATALYST_TYPES = ("EARNINGS", "M&A", "REGULATORY", "PRODUCT", "MACRO")
STRUCTURAL_CATALYSTS = ("EARNINGS", "M&A", "REGULATORY", "PRODUCT")
NEWS_MAX_NOVELTY_MIN = 30          # oltre 30 minuti la notizia è già nel prezzo: Impact 0
THESIS_MAX_WORDS = 15

NEWS_SYSTEM_PROMPT = (
    "You are a buy-side news analyst. You receive timestamped headlines about ONE ticker and judge whether they are "
    "a real, fresh price catalyst for a LONG position. Reply ONLY with one JSON object, no prose, exactly these keys: "
    '{"impact_score": float between -1.0 and 1.0 (negative = bearish for the stock, 0 = irrelevant/speculative, '
    'positive = bullish), "novelty_index_minutes": integer minutes since the headline that drives your score was '
    'published, "catalyst_type": one of "EARNINGS","M&A","REGULATORY","PRODUCT","MACRO", '
    '"thesis_summary": string, at most 15 words, in Italian}. '
    "Rumors, opinion pieces, price-recap articles and generic market wraps are speculative: impact near 0."
)


def build_news_prompt(symbol: str, headlines: List[Dict[str, Any]], now: float) -> str:
    lines = [f"- [{max(0, int((now - h['published']) / 60))} min fa · {h['source']}] {h['title']}" for h in headlines]
    return f"Ticker: {symbol}\nTitoli (dal più recente):\n" + "\n".join(lines)


def parse_news_assessment(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """JSON di Groq validato campo per campo; None se manca qualcosa o i tipi sono sbagliati."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        impact = float(data["impact_score"])
        novelty = int(round(float(data["novelty_index_minutes"])))
        catalyst = str(data["catalyst_type"]).strip().upper()
        thesis = str(data["thesis_summary"]).strip()
    except (ValueError, TypeError, KeyError):
        return None
    if catalyst in ("M&A", "MA", "M_A", "MERGER", "ACQUISITION"):
        catalyst = "M&A"
    if catalyst not in CATALYST_TYPES or not np.isfinite(impact) or not thesis:
        return None
    return {"impact_score": float(np.clip(impact, -1.0, 1.0)), "novelty_index_minutes": max(0, novelty),
            "catalyst_type": catalyst, "thesis_summary": " ".join(thesis.split()[:THESIS_MAX_WORDS])}


def _epoch(value: Any) -> Optional[float]:
    """Timestamp UNIX da epoch, ISO 8601 o RFC 822 (RSS); None se illeggibile."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError):
        return None


class NewsRadar:
    """Ingestione news multi-canale: ogni canale restituisce [{"title", "published" (epoch), "source"}]."""

    CRYPTO_NAMES = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "AVAX": "avalanche", "ADA": "cardano",
                    "DOGE": "dogecoin", "XRP": "xrp", "LTC": "litecoin", "DOT": "polkadot", "LINK": "chainlink"}

    def __init__(self, finnhub_key: Optional[str] = None, polygon_key: Optional[str] = None,
                 sec_user_agent: Optional[str] = None, http_timeout: float = 3.0, lookback_hours: float = 24.0,
                 max_items: int = 8, fetchers: Optional[Dict[str, Callable[[str, bool], List[Dict[str, Any]]]]] = None):
        self.finnhub_key = finnhub_key
        self.polygon_key = polygon_key
        self.sec_user_agent = sec_user_agent or "QuantNewsRadar/1.0 research-bot"
        self.http_timeout = http_timeout
        self.lookback_hours = lookback_hours
        self.max_items = max_items
        self._crypto_cache = {"ts": 0.0, "items": []}
        self.fetchers = fetchers if fetchers is not None else {
            "finnhub": self.fetch_finnhub, "polygon": self.fetch_polygon, "rss": self.fetch_rss, "sec": self.fetch_sec}
        self.last_errors: Dict[str, str] = {}

    # ------------------------------------------------------------------ canali
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=self.http_timeout)
        r.raise_for_status()
        return r

    def fetch_finnhub(self, symbol: str, is_crypto: bool) -> List[Dict[str, Any]]:
        if not self.finnhub_key:
            return []
        if is_crypto:
            if time.time() - self._crypto_cache["ts"] > 300:
                items = self._get("https://finnhub.io/api/v1/news",
                                  {"category": "crypto", "token": self.finnhub_key}).json()
                self._crypto_cache.update(ts=time.time(), items=items if isinstance(items, list) else [])
            base = symbol.upper().split("-")[0]
            pattern = re.compile(rf"\b({re.escape(base)}|{re.escape(self.CRYPTO_NAMES.get(base, base.lower()))})\b",
                                 re.IGNORECASE)
            items = [a for a in self._crypto_cache["items"] if pattern.search(a.get("headline") or "")]
        else:
            today = datetime.now(timezone.utc).date()
            items = self._get("https://finnhub.io/api/v1/company-news", {
                "symbol": symbol, "from": today.fromordinal(today.toordinal() - 2).isoformat(),
                "to": today.isoformat(), "token": self.finnhub_key}).json()
        return [{"title": a["headline"], "published": _epoch(a.get("datetime")), "source": "Finnhub"}
                for a in (items or []) if isinstance(a, dict) and a.get("headline")]

    def fetch_polygon(self, symbol: str, is_crypto: bool) -> List[Dict[str, Any]]:
        if not self.polygon_key:
            return []
        ticker = f"X:{symbol.upper().replace('-', '')}" if is_crypto else symbol.upper()
        data = self._get("https://api.polygon.io/v2/reference/news", {
            "ticker": ticker, "order": "desc", "sort": "published_utc", "limit": 10, "apiKey": self.polygon_key}).json()
        return [{"title": a["title"], "published": _epoch(a.get("published_utc")), "source": "Polygon"}
                for a in (data or {}).get("results", []) if a.get("title")]

    def fetch_rss(self, symbol: str, is_crypto: bool) -> List[Dict[str, Any]]:
        r = self._get("https://feeds.finance.yahoo.com/rss/2.0/headline",
                      {"s": symbol.upper(), "region": "US", "lang": "en-US"}, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        return [{"title": (item.findtext("title") or "").strip(), "published": _epoch(item.findtext("pubDate")),
                 "source": "RSS Yahoo"} for item in root.iter("item") if (item.findtext("title") or "").strip()]

    def fetch_sec(self, symbol: str, is_crypto: bool) -> List[Dict[str, Any]]:
        if is_crypto:
            return []
        r = self._get("https://www.sec.gov/cgi-bin/browse-edgar", {
            "action": "getcompany", "CIK": symbol.upper(), "type": "8-K", "dateb": "", "owner": "include",
            "count": 10, "output": "atom"}, headers={"User-Agent": self.sec_user_agent})
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.content)
        return [{"title": f"SEC filing: {(e.findtext('a:title', default='', namespaces=ns) or '').strip()}",
                 "published": _epoch(e.findtext("a:updated", namespaces=ns)), "source": "SEC EDGAR"}
                for e in root.findall("a:entry", ns)]

    # ------------------------------------------------------------------ aggregazione
    def collect(self, symbol: str, is_crypto: bool, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Titoli di tutti i canali in parallelo: deduplicati, dal più recente, entro lookback_hours.

        Un canale in errore viene saltato (motivo in last_errors), gli altri restano validi.
        """
        now = now or time.time()
        out, errors = [], {}
        with ThreadPoolExecutor(max_workers=max(1, len(self.fetchers))) as pool:
            futures = {name: pool.submit(fn, symbol, is_crypto) for name, fn in self.fetchers.items()}
            for name, fut in futures.items():
                try:
                    out.extend(fut.result())
                except Exception as e:
                    errors[name] = f"{type(e).__name__}: {str(e)[:120]}"
        self.last_errors = errors
        seen, items = set(), []
        for h in sorted((h for h in out if h.get("published")), key=lambda h: h["published"], reverse=True):
            key = re.sub(r"\W+", " ", h["title"].lower()).strip()
            if key in seen or now - h["published"] > self.lookback_hours * 3600 or h["published"] > now + 300:
                continue
            seen.add(key)
            items.append(h)
        return items[: self.max_items]


class MacroSentimentAgent:
    """
    AGENTE #4: Macro, News Radar & Catalyst Validator
    - VIX & Cross-Asset Stress Matrix (Yield Curve 10Y-2Y, DXY), Event Blackout Window
    - Central Bank Hawkish/Dovish NLP Scoring, COT, Economic Surprise, Contrarian Sentiment
    - News Radar multi-canale + Groq (JSON): impact, novelty, catalizzatore, tesi in 15 parole
    - Veto: spinta quantitativa senza catalizzatore valido; Thesis Decay per le posizioni aperte
    """
    def __init__(
        self,
        vix_high_threshold: float = 28.0,
        vix_moderate_threshold: float = 20.0,
        hawkish_keywords: Optional[List[str]] = None,
        dovish_keywords: Optional[List[str]] = None,
        quant_push_threshold: float = 70.0,
        speculative_impact: float = 0.15,
        negative_impact: float = -0.15,
        thesis_decay_impact: float = -0.3,
        thesis_decay_drop: float = 0.6,
        swing_impact: float = 0.6,
    ):
        self.agent_id = "AGENT_04_MACRO_SENTIMENT"
        self.vix_high_threshold = vix_high_threshold
        self.vix_moderate_threshold = vix_moderate_threshold
        self.quant_push_threshold = quant_push_threshold
        self.speculative_impact = speculative_impact
        self.negative_impact = negative_impact
        self.thesis_decay_impact = thesis_decay_impact
        self.thesis_decay_drop = thesis_decay_drop
        self.swing_impact = swing_impact
        self.hawkish_keywords = hawkish_keywords or [
            "inflation", "rate hike", "tightening", "hawkish", "upside risk", "overheating", "restrictive"
        ]
        self.dovish_keywords = dovish_keywords or [
            "cut", "easing", "dovish", "slowdown", "recession risk", "accommodative", "cool down"
        ]

    def calculate_economic_surprise(self, actual: float, consensus: float, std_dev: float = 1.0) -> float:
        """
        Calcola l'Economic Surprise Index (Z-score dello scostamento rispetto al consenso).
        """
        if std_dev <= 0:
            std_dev = 1.0
        surprise_z = (actual - consensus) / std_dev
        return float(np.clip(surprise_z, -3.0, 3.0))

    def parse_central_bank_speech(self, speech_text: str) -> float:
        """
        Analisi semantica del testo di un discorso o comunicato stampa della Banca Centrale.
        Restituisce un valore tra -1.0 (Molto Dovish) e +1.0 (Molto Hawkish).
        """
        if not speech_text:
            return 0.0
            
        text_lower = speech_text.lower()
        hawk_count = sum(text_lower.count(word) for word in self.hawkish_keywords)
        dove_count = sum(text_lower.count(word) for word in self.dovish_keywords)
        
        total = hawk_count + dove_count
        if total == 0:
            return 0.0
            
        polarity = (hawk_count - dove_count) / total
        return float(np.clip(polarity, -1.0, 1.0))

    def evaluate_cross_asset_stress(
        self, 
        vix: float, 
        us10y_yield: Optional[float] = None, 
        us02y_yield: Optional[float] = None, 
        dxy_change_pct: float = 0.0
    ) -> Dict[str, Any]:
        """
        Valuta lo stress finanziario globale monitorando VIX, Inversione della Curva (10Y-2Y) e DXY.
        Senza i rendimenti reali la curva viene considerata neutra (nessuna penalità inventata).
        """
        if us10y_yield is None or us02y_yield is None:
            yield_curve_spread = 0.0
        else:
            yield_curve_spread = us10y_yield - us02y_yield  # Se < 0 -> Curva Invertita (Segnale Recessione)
        
        stress_level = "LOW"
        size_multiplier = 1.0
        
        if vix >= self.vix_high_threshold:
            stress_level = "EXTREME_PANIC"
            size_multiplier = 0.0  # Veto
        elif vix >= self.vix_moderate_threshold or yield_curve_spread < -0.5:
            stress_level = "HIGH_STRESS"
            size_multiplier = 0.4
        elif yield_curve_spread < -0.05 or dxy_change_pct > 0.015:
            stress_level = "MODERATE_HEADWIND"
            size_multiplier = 0.75

        return {
            "stress_level": stress_level,
            "size_multiplier": size_multiplier,
            "yield_curve_spread": round(yield_curve_spread, 3),
            "vix": vix
        }

    def evaluate_cot_positioning(self, institutional_net_contracts: int, historical_max: int = 100000) -> float:
        """
        Analizza le posizioni nette dei grandi fondi (CFTC COT Report).
        Restituisce uno score tra -1.0 (Forte posizionamento Short) e +1.0 (Forte posizionamento Long).
        """
        if historical_max <= 0:
            return 0.0
        score = institutional_net_contracts / float(historical_max)
        return float(np.clip(score, -1.0, 1.0))

    def calculate_contrarian_sentiment_signal(self, fear_greed_index: float) -> Dict[str, Any]:
        """
        Rileva estremi irrazionali nel sentiment retail per generare segnali Contrarian.
        """
        if fear_greed_index >= 88.0:
            return {"signal": "CONTRARIAN_BEARISH_WARNING", "bias": -0.3, "reason": "EXTREME_RETAIL_FOMO"}
        elif fear_greed_index <= 12.0:
            return {"signal": "CONTRARIAN_BULLISH_WARNING", "bias": 0.3, "reason": "EXTREME_RETAIL_PANIC"}
        return {"signal": "NEUTRAL", "bias": 0.0, "reason": "BALANCED"}

    def check_event_blackout(self, upcoming_events: List[Dict[str, Any]], window_minutes: int = 30) -> Dict[str, Any]:
        """Verifica se il mercato è in prossimità di rilasci macro o trimestrali."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for event in upcoming_events:
            try:
                event_time = datetime.fromisoformat(event.get("timestamp", ""))
                time_diff_minutes = (event_time - now).total_seconds() / 60.0
                if -15 <= time_diff_minutes <= window_minutes:
                    return {
                        "is_blackout": True,
                        "event_name": event.get("event_name", "HIGH_IMPACT_EVENT"),
                        "minutes_to_event": round(time_diff_minutes, 1)
                    }
            except Exception:
                continue
        return {"is_blackout": False, "event_name": "NONE", "minutes_to_event": 999.0}


    # ------------------------------------------------------------------ News Radar + Groq
    @staticmethod
    def news_score(impact: float) -> float:
        """Impact -1..+1 -> Groq News Score 0-100 (50 = neutro), la scala dell'Ensemble del CIO."""
        return round((float(np.clip(impact, -1.0, 1.0)) + 1.0) * 50.0, 2)

    def assess_news(self, symbol: str, headlines: List[Dict[str, Any]],
                    llm: Optional[Callable[[str, str], Optional[str]]], now: Optional[float] = None) -> Dict[str, Any]:
        """Valutazione Groq dei titoli. llm(system, prompt) -> testo JSON, oppure None se in timeout/non disponibile.

        status: OK | NO_NEWS (nessun titolo) | STALE (novelty > 30 min) | TIMEOUT (Groq oltre 2 s o non configurato)
                | INVALID (JSON non conforme). Solo OK può avere Impact diverso da 0.
        """
        now = now or time.time()
        base = {"impact_score": 0.0, "novelty_index_minutes": None, "catalyst_type": None, "thesis_summary": "",
                "headlines": len(headlines), "top_headline": headlines[0]["title"] if headlines else "",
                "sources": sorted({h["source"] for h in headlines}), "assessed_at": now}
        if not headlines:
            return {**base, "status": "NO_NEWS", "thesis_summary": "nessuna notizia recente", "news_score": 50.0}
        freshest = max(0, int((now - headlines[0]["published"]) / 60))
        if freshest > NEWS_MAX_NOVELTY_MIN:
            # Nessun titolo negli ultimi 30 minuti: inutile interrogare Groq, la notizia è già nel prezzo
            return {**base, "status": "STALE", "novelty_index_minutes": freshest, "news_score": 50.0,
                    "thesis_summary": f"ultima notizia {freshest} min fa (> {NEWS_MAX_NOVELTY_MIN})"}
        text = None
        if llm is not None:
            try:
                text = llm(NEWS_SYSTEM_PROMPT, build_news_prompt(symbol, headlines, now))
            except Exception:
                text = None
        if text is None:
            return {**base, "status": "TIMEOUT", "novelty_index_minutes": freshest, "news_score": 50.0,
                    "thesis_summary": "Groq non disponibile: News Score neutro"}
        parsed = parse_news_assessment(text)
        if parsed is None:
            return {**base, "status": "INVALID", "novelty_index_minutes": freshest, "news_score": 50.0,
                    "thesis_summary": "risposta Groq non conforme allo schema JSON"}
        # La notizia che guida il giudizio non può essere più fresca del titolo più recente
        novelty = max(parsed["novelty_index_minutes"], freshest)
        out = {**base, **parsed, "novelty_index_minutes": novelty, "status": "OK"}
        if novelty > NEWS_MAX_NOVELTY_MIN:
            out.update(status="STALE", impact_score=0.0, groq_impact_raw=parsed["impact_score"])
        out["news_score"] = self.news_score(out["impact_score"])
        return out

    def news_veto(self, assessment: Optional[Dict[str, Any]], quant_score: Optional[float]) -> Optional[str]:
        """Filtro di veto di Groq (None = nessun veto).

        - notizia negativa (impact <= negative_impact): sempre veto per un long;
        - spinta quantitativa alta (quant >= quant_push_threshold) senza catalizzatore: notizia assente,
          più vecchia di 30 minuti o speculativa (impact < speculative_impact) -> veto;
        - TIMEOUT / INVALID: News Score neutro e nessun veto (il ciclo non si blocca per Groq).
        """
        if not assessment:
            return None
        status, impact = assessment.get("status"), float(assessment.get("impact_score") or 0.0)
        if status == "OK" and impact <= self.negative_impact:
            return f"notizia negativa (impact {impact:+.2f}: {assessment.get('thesis_summary')})"
        if quant_score is None or quant_score < self.quant_push_threshold or status in ("TIMEOUT", "INVALID"):
            return None
        if status == "NO_NEWS":
            return f"spinta quantitativa {quant_score:.0f} senza notizie a supporto"
        if status == "STALE":
            return (f"spinta quantitativa {quant_score:.0f} con notizie vecchie "
                    f"({assessment.get('novelty_index_minutes')} min > {NEWS_MAX_NOVELTY_MIN})")
        if impact < self.speculative_impact:
            return f"notizia speculativa (impact {impact:+.2f} < {self.speculative_impact:+.2f})"
        return None

    def thesis_decay(self, entry_impact: Optional[float], assessment: Optional[Dict[str, Any]]) -> Optional[str]:
        """Thesis Decay su una posizione aperta: solo notizie FRESCHE che smentiscono il catalizzatore.

        Il semplice invecchiamento della notizia (STALE / NO_NEWS) non è decadimento: sarebbe un time-stop.
        """
        if not assessment or assessment.get("status") != "OK":
            return None
        impact = float(assessment.get("impact_score") or 0.0)
        if impact <= self.thesis_decay_impact:
            return f"smentita / notizia contraria (impact {impact:+.2f}: {assessment.get('thesis_summary')})"
        if entry_impact is not None and impact <= 0 and entry_impact - impact >= self.thesis_decay_drop:
            return (f"catalizzatore decaduto (impact {entry_impact:+.2f} → {impact:+.2f}: "
                    f"{assessment.get('thesis_summary')})")
        return None

    def is_swing_catalyst(self, assessment: Optional[Dict[str, Any]]) -> bool:
        """Catalizzatore strutturale ad alto impatto (EARNINGS, M&A, REGULATORY, PRODUCT con impact >= swing_impact)."""
        return bool(assessment and assessment.get("status") == "OK"
                    and assessment.get("catalyst_type") in STRUCTURAL_CATALYSTS
                    and float(assessment.get("impact_score") or 0) >= self.swing_impact)

    def analyze(
        self,
        df: pd.DataFrame,
        vix_level: float = 16.5,
        fear_greed_index: float = 55.0,
        news_sentiment: float = 0.0,
        central_bank_speech: str = "",
        economic_data: Optional[Dict[str, float]] = None,
        cot_net_contracts: int = 25000,
        upcoming_events: Optional[List[Dict[str, Any]]] = None,
        news_assessment: Optional[Dict[str, Any]] = None,
        quant_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Pipeline Esecutiva completa dell'Agente #4.
        news_assessment: esito di assess_news (Groq); senza, il News Score è neutro (50) e vale news_sentiment.
        quant_score: score dell'Agente #1, serve al filtro di veto (spinta alta senza catalizzatore).
        """
        if upcoming_events is None:
            upcoming_events = []
        news = news_assessment or {"status": "NO_ASSESSMENT", "impact_score": float(news_sentiment or 0.0),
                                   "novelty_index_minutes": None, "catalyst_type": None, "thesis_summary": "",
                                   "headlines": 0}
        impact = float(news.get("impact_score") or 0.0)
        news_fields = {
            "news_score": self.news_score(impact),
            "news": {k: news.get(k) for k in ("status", "impact_score", "novelty_index_minutes", "catalyst_type",
                                              "thesis_summary", "headlines", "top_headline", "sources")},
            "swing_catalyst": self.is_swing_catalyst(news),
        }

        # 1. Event Blackout Filter
        blackout_info = self.check_event_blackout(upcoming_events)
        if blackout_info["is_blackout"]:
            return {
                "agent_id": self.agent_id,
                "macro_approved": False,
                "macro_score": 0.0,
                "stress_level": "EVENT_BLACKOUT",
                "trade_signal": "EVENT_BLACKOUT_VETO",
                "reason": f"BLACKOUT: {blackout_info['event_name']} in {blackout_info['minutes_to_event']}m",
                **news_fields,
            }

        # 2. Stress Cross-Asset
        stress_info = self.evaluate_cross_asset_stress(vix_level)
        if stress_info["size_multiplier"] == 0.0:
            return {
                "agent_id": self.agent_id,
                "macro_approved": False,
                "macro_score": 10.0,
                "stress_level": stress_info["stress_level"],
                "trade_signal": "CROSS_ASSET_PANIC_VETO",
                "reason": f"EXTREME_STRESS ({stress_info['stress_level']}, VIX {vix_level})",
                **news_fields,
            }

        # 3. Filtro di veto di Groq sul catalizzatore informativo
        veto = self.news_veto(news_assessment, quant_score)

        # 4. Sentiment & NLP Central Bank
        cb_hawkishness = self.parse_central_bank_speech(central_bank_speech)
        cot_score = self.evaluate_cot_positioning(cot_net_contracts)
        contrarian_info = self.calculate_contrarian_sentiment_signal(fear_greed_index)

        # 5. Economic Surprise Index
        surprise_score = 0.0
        if economic_data and 'actual' in economic_data and 'consensus' in economic_data:
            surprise_score = self.calculate_economic_surprise(
                economic_data['actual'], economic_data['consensus']
            )

        # 6. Score Macro Composito (contesto; il voto delle notizie per il CIO è news_score)
        base_sentiment = (impact + 1.0) * 50.0
        macro_score = (0.35 * base_sentiment) + (0.25 * fear_greed_index) + (0.2 * (cot_score + 1.0) * 50.0)
        macro_score -= cb_hawkishness * 15.0
        macro_score += surprise_score * 5.0
        macro_score += contrarian_info["bias"] * 20.0
        macro_score = float(np.clip(macro_score * stress_info["size_multiplier"], 0.0, 100.0))

        if veto:
            signal = "NEWS_VETO"
        elif macro_score >= 70.0:
            signal = "BULLISH_MACRO_TAILWIND"
        elif macro_score <= 35.0:
            signal = "BEARISH_MACRO_HEADWIND"
        else:
            signal = "NEUTRAL_MACRO"

        out = {
            "agent_id": self.agent_id,
            "macro_approved": veto is None,
            "macro_score": round(macro_score, 2),
            "stress_level": stress_info["stress_level"],
            "trade_signal": signal,
            **news_fields,
            "metrics": {
                "cross_asset_stress": stress_info,
                "central_bank_hawkishness": round(cb_hawkishness, 3),
                "cot_institutional_score": round(cot_score, 3),
                "economic_surprise_z": round(surprise_score, 3),
                "contrarian_info": contrarian_info,
                "suggested_size_multiplier": stress_info["size_multiplier"]
            }
        }
        if veto:
            out["reason"] = f"NEWS VETO (Groq): {veto}"
        return out
