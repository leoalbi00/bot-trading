"""COO del desk: agente IA autonomo con strumenti (dati del sistema + ricerca sul web).

Logica a sé stante, separata dalla pipeline di trading:
- ragiona con un LLM Groq in un ciclo "pensa -> usa uno strumento -> leggi il risultato -> rispondi" (tool calling),
  fino a COO_MAX_STEPS passi ed entro un budget di tempo;
- legge il sistema SOLO tramite strumenti in sola lettura (diagnosi della pipeline, conto, ticker, log, ...):
  non invia ordini e non modifica nulla; le azioni del Centro di Comando le può solo PROPORRE (conferma dell'utente);
- quando serve cerca sul web (WebResearch) e cita le fonti.

Modelli: COO_MODELS (default qwen/qwen3.8-27b, poi gpt-oss-20b e per ultimo gpt-oss-120b). I primi hanno quote Groq separate
dal modello usato dalla pipeline (gpt-oss-120b): la chat non consuma i token delle decisioni di trading.
Su errore 429/404/timeout si passa al modello successivo, nello stesso passo.

Ricerca web (dal più economico/affidabile; tutti opzionali tranne i gratuiti):
1. Tavily (TAVILY_API_KEY) o Brave Search (BRAVE_SEARCH_API_KEY), se configurati;
2. notizie: Google News RSS (gratuito, nessuna chiave);
3. definizioni e concetti: DuckDuckGo Instant Answer (gratuito);
4. ultima risorsa: browser_search integrato di Groq su gpt-oss (molti token: tetto giornaliero COO_WEB_BROWSER_DAILY);
5. lettura di una pagina: leggi_pagina(url), con protezione contro indirizzi interni (SSRF).
"""
import datetime as dt
import html
import ipaddress
import json
import os
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests

COO_MODELS = [m.strip() for m in os.getenv("COO_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-20b,openai/gpt-oss-120b").split(",")
              if m.strip()]
COO_MAX_STEPS = int(os.getenv("COO_MAX_STEPS", "6"))          # chiamate all'LLM per risposta (strumenti compresi)
COO_BUDGET_S = float(os.getenv("COO_BUDGET_S", "45"))         # tempo massimo di una risposta (ricerche comprese)
COO_CALL_TIMEOUT_S = 20.0                                      # singola chiamata all'LLM
TOOL_OUTPUT_MAX = 1800                                         # caratteri per risultato di strumento (limite di token)
WEB_TIMEOUT_S = 8.0
WEB_BROWSER_DAILY = int(os.getenv("COO_WEB_BROWSER_DAILY", "15"))
WEB_BROWSER_MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
UA_BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
UA_BOT = "QuantDeskCOO/1.0 (assistente di ricerca di un bot di trading)"


def _clip(text: str, limit: int = TOOL_OUTPUT_MAX) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "… [troncato]"


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav|form)[^>]*>.*?</\1>", " ", raw or "")
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()


def _public_url(url: str) -> bool:
    """Solo http(s) verso indirizzi pubblici: niente localhost, reti private o metadati del cloud (SSRF)."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except (ValueError, OSError):
        return False


class WebResearch:
    """Ricerca sul web e lettura di pagine per il COO, con più fornitori e un tetto alle ricerche costose."""

    def __init__(self, groq_client_factory: Optional[Callable[[], Any]] = None):
        self.groq_client_factory = groq_client_factory
        self.tavily_key = os.getenv("TAVILY_API_KEY")
        self.brave_key = os.getenv("BRAVE_SEARCH_API_KEY")
        self._lock = threading.Lock()
        self._browser_day, self._browser_used = None, 0

    # ------------------------------------------------------------------ fornitori
    def _tavily(self, query: str, news: bool) -> Optional[Dict[str, Any]]:
        if not self.tavily_key:
            return None
        r = requests.post("https://api.tavily.com/search", timeout=WEB_TIMEOUT_S, json={
            "api_key": self.tavily_key, "query": query, "max_results": 6, "include_answer": True,
            "topic": "news" if news else "general"})
        r.raise_for_status()
        d = r.json()
        return {"fonte": "Tavily", "sintesi": d.get("answer"),
                "risultati": [{"titolo": x.get("title"), "url": x.get("url"), "estratto": _clip(x.get("content"), 300)}
                              for x in d.get("results") or []]}

    def _brave(self, query: str, news: bool) -> Optional[Dict[str, Any]]:
        if not self.brave_key:
            return None
        r = requests.get("https://api.search.brave.com/res/v1/" + ("news" if news else "web") + "/search",
                         params={"q": query, "count": 6}, timeout=WEB_TIMEOUT_S,
                         headers={"X-Subscription-Token": self.brave_key, "Accept": "application/json"})
        r.raise_for_status()
        d = r.json()
        items = d.get("results") if news else (d.get("web") or {}).get("results")
        return {"fonte": "Brave Search",
                "risultati": [{"titolo": x.get("title"), "url": x.get("url"), "estratto": _clip(_strip_html(x.get("description")), 300),
                               "data": x.get("age")} for x in items or []][:6]}

    @staticmethod
    def _google_news(query: str) -> Optional[Dict[str, Any]]:
        lang_it = bool(re.search(r"[àèéìòù]|\b(il|la|di|che|per|perché|notizie|oggi)\b", query.lower()))
        params = {"q": query, "hl": "it" if lang_it else "en-US", "gl": "IT" if lang_it else "US",
                  "ceid": "IT:it" if lang_it else "US:en"}
        r = requests.get("https://news.google.com/rss/search", params=params, timeout=WEB_TIMEOUT_S,
                         headers={"User-Agent": UA_BROWSER})
        r.raise_for_status()
        items = ET.fromstring(r.content).findall("./channel/item")[:8]
        if not items:
            return None
        return {"fonte": "Google News", "risultati": [
            {"titolo": it.findtext("title"), "url": it.findtext("link"), "data": it.findtext("pubDate"),
             "editore": it.findtext("source")} for it in items]}

    @staticmethod
    def _ddg_instant(query: str) -> Optional[Dict[str, Any]]:
        r = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1,
                                                                "skip_disambig": 1},
                         timeout=WEB_TIMEOUT_S, headers={"User-Agent": UA_BOT})
        r.raise_for_status()
        d = r.json()
        if not d.get("AbstractText") and not d.get("Answer"):
            return None
        related = [t for t in d.get("RelatedTopics") or [] if isinstance(t, dict) and t.get("FirstURL")][:4]
        return {"fonte": "DuckDuckGo", "sintesi": d.get("Answer") or d.get("AbstractText"),
                "risultati": [{"titolo": d.get("Heading"), "url": d.get("AbstractURL")}]
                + [{"titolo": _clip(t.get("Text"), 120), "url": t.get("FirstURL")} for t in related]}

    def _groq_browser(self, query: str, deadline: float) -> Optional[Dict[str, Any]]:
        """Ricerca integrata di Groq (gpt-oss): buona qualità ma molti token, quindi tetto giornaliero."""
        if not self.groq_client_factory:
            return None
        today = dt.date.today().isoformat()
        with self._lock:
            if self._browser_day != today:
                self._browser_day, self._browser_used = today, 0
            if self._browser_used >= WEB_BROWSER_DAILY:
                return {"fonte": "Groq browser_search", "errore": f"tetto giornaliero di {WEB_BROWSER_DAILY} ricerche raggiunto"}
            self._browser_used += 1
        last_error = None
        for model in WEB_BROWSER_MODELS:
            remaining = deadline - time.monotonic()
            if remaining < 5:
                break
            try:
                res = self.groq_client_factory().chat.completions.create(
                    model=model, max_tokens=900, temperature=0.2, timeout=min(remaining, 30),
                    tools=[{"type": "browser_search"}],
                    messages=[{"role": "system", "content": "Sei un ricercatore finanziario. Usa la ricerca web e rispondi "
                                                            "in italiano, in modo conciso e fattuale, con date precise."},
                              {"role": "user", "content": query}])
                msg = res.choices[0].message
                urls = []
                for t in getattr(msg, "executed_tools", None) or []:
                    urls += re.findall(r"https?://[^\s\)\]】\"'<>]+", getattr(t, "output", "") or "")
                urls = [u for u in dict.fromkeys(urls) if "exa.ai/search" not in u][:6]
                text = re.sub(r"【[^】]*】", "", msg.content or "").strip()
                return {"fonte": f"Groq browser_search ({model})", "sintesi": _clip(text, 1500),
                        "risultati": [{"url": u} for u in urls]}
            except Exception as e:
                last_error = e
        return {"fonte": "Groq browser_search", "errore": f"{type(last_error).__name__}: {str(last_error)[:120]}"} \
            if last_error else None

    # ------------------------------------------------------------------ strumenti esposti al COO
    def search(self, query: str, kind: str = "web", deadline: Optional[float] = None) -> Dict[str, Any]:
        """kind: "notizie" (fatti recenti, mercati) o "web" (concetti, documentazione, dati generali)."""
        deadline = deadline or time.monotonic() + 30
        news = kind == "notizie"
        chain = [self._tavily, self._brave] + ([lambda q, n: self._google_news(q)] if news else
                                               [lambda q, n: self._ddg_instant(q)])
        errors = []
        for fn in chain:
            if deadline - time.monotonic() < 2:
                break
            try:
                out = fn(query, news)
                if out and (out.get("risultati") or out.get("sintesi")):
                    return {"query": query, **out}
            except Exception as e:
                errors.append(f"{type(e).__name__}: {str(e)[:80]}")
        if not news:
            # Senza fornitori con chiave e senza risposta immediata: notizie (gratis) e poi ricerca Groq
            try:
                out = self._google_news(query)
            except Exception as e:
                out = None
                errors.append(f"Google News: {type(e).__name__}")
            browser = self._groq_browser(query, deadline)
            if browser and not browser.get("errore"):
                return {"query": query, **browser, "notizie_correlate": (out or {}).get("risultati", [])[:4]}
            if out:
                return {"query": query, **out, "nota": (browser or {}).get("errore")}
        return {"query": query, "risultati": [], "errore": "; ".join(errors) or "nessun risultato"}

    @staticmethod
    def read_page(url: str, max_chars: int = 3500) -> Dict[str, Any]:
        if not _public_url(url):
            return {"url": url, "errore": "indirizzo non consentito (solo pagine web pubbliche http/https)"}
        try:
            r = requests.get(url, timeout=WEB_TIMEOUT_S, headers={"User-Agent": UA_BROWSER}, stream=True,
                             allow_redirects=True)
            if not _public_url(r.url):
                return {"url": url, "errore": "redirect verso un indirizzo non consentito"}
            raw = r.raw.read(1_500_000, decode_content=True).decode(r.encoding or "utf-8", errors="replace")
            title = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
            return {"url": r.url, "stato": r.status_code, "titolo": _strip_html(title.group(1)) if title else None,
                    "testo": _clip(_strip_html(raw), max_chars)}
        except Exception as e:
            return {"url": url, "errore": f"{type(e).__name__}: {str(e)[:120]}"}


RATE_LIMIT_MAX_WAIT_S = 20.0     # attesa massima su un 429 "riprova tra N secondi" prima di cambiare modello
RATE_LIMIT_RETRIES = 2           # attese consecutive sullo stesso modello


def _retry_after(error) -> Optional[float]:
    """Secondi suggeriti da Groq in un errore 429 ("try again in 8.4s" o header retry-after), se presenti."""
    try:
        header = getattr(getattr(error, "response", None), "headers", {}).get("retry-after")
        if header:
            return float(header)
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(error))
    return (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else None


class COOAgent:
    """Ciclo agentico del COO: LLM con strumenti, cambio modello sugli errori, budget di tempo e passi."""

    def __init__(self, client_factory: Callable[[], Any], models: Optional[List[str]] = None,
                 max_steps: int = COO_MAX_STEPS):
        self.client_factory = client_factory
        self.models = list(models or COO_MODELS)
        self.max_steps = max_steps
        self.unavailable: set = set()

    @staticmethod
    def _assistant_msg(msg) -> Dict[str, Any]:
        out = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [{"id": tc.id, "type": "function",
                                  "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                                 for tc in msg.tool_calls]
        return out

    def _call(self, messages, tools, deadline, allow_tools=True):
        """Una chiamata all'LLM, provando i modelli in ordine finché uno risponde. -> (messaggio, modello)."""
        last_error = None
        for model in [m for m in self.models if m not in self.unavailable]:
            remaining = deadline - time.monotonic()
            if remaining < 1.5:
                break
            kwargs = {"model": model, "messages": messages, "max_tokens": 1200, "temperature": 0.3,
                      "timeout": min(remaining, COO_CALL_TIMEOUT_S)}
            if tools and allow_tools:
                kwargs.update(tools=tools, tool_choice="auto")
            for attempt in range(RATE_LIMIT_RETRIES + 1):
                try:
                    res = self.client_factory().chat.completions.create(**kwargs)
                    return res.choices[0].message, model
                except Exception as e:
                    last_error = e
                    status = getattr(e, "status_code", None)
                    if status == 404:
                        self.unavailable.add(model)
                        break
                    # Limite di token al minuto (piano gratuito Groq): se il modello torna libero tra pochi secondi
                    # conviene aspettare invece di passare a gpt-oss-120b, che è il modello della pipeline di trading
                    wait = _retry_after(e)
                    if status == 429 and attempt < RATE_LIMIT_RETRIES and wait is not None and wait <= RATE_LIMIT_MAX_WAIT_S \
                            and deadline - time.monotonic() > wait + 6:
                        time.sleep(wait + 0.3)
                        kwargs["timeout"] = min(deadline - time.monotonic(), COO_CALL_TIMEOUT_S)
                        continue
                    break
        raise last_error or TimeoutError("budget di tempo esaurito")

    def run(self, system_prompt: str, history: List[Dict[str, str]], message: str,
            tools: Dict[str, Dict[str, Any]], deadline: float) -> Dict[str, Any]:
        """tools: {nome: {"schema": {...function schema...}, "fn": callable(**args) -> dict|str}}.

        Restituisce {"reply", "model", "steps", "tools_used"}; solleva un'eccezione se nessun modello risponde.
        """
        schemas = [{"type": "function", "function": t["schema"]} for t in tools.values()]
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": message}]
        used, model = [], None
        for step in range(self.max_steps):
            last = step == self.max_steps - 1 or deadline - time.monotonic() < 6
            msg, model = self._call(messages, schemas, deadline, allow_tools=not last)
            if not msg.tool_calls:
                reply = re.sub(r"(?s)<think>.*?</think>", "", msg.content or "").strip()
                if reply:
                    return {"reply": reply, "model": model, "steps": step + 1, "tools_used": used}
                messages.append({"role": "user", "content": "Rispondi ora all'utente con quello che sai."})
                continue
            messages.append(self._assistant_msg(msg))
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}") or {}
                except ValueError:
                    args = {}
                tool = tools.get(name)
                started = time.monotonic()
                try:
                    result = tool["fn"](**args) if tool else {"errore": f"strumento {name} inesistente"}
                except TypeError as e:
                    result = {"errore": f"argomenti non validi per {name}: {e}"}
                except Exception as e:
                    result = {"errore": f"{type(e).__name__}: {str(e)[:160]}"}
                used.append({"tool": name, "args": args, "ms": round((time.monotonic() - started) * 1000)})
                content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": _clip(content)})
        # Passi esauriti: risposta finale senza strumenti
        msg, model = self._call(messages + [{"role": "user", "content": "Basta strumenti: rispondi ora all'utente."}],
                                schemas, deadline, allow_tools=False)
        return {"reply": re.sub(r"(?s)<think>.*?</think>", "", msg.content or "").strip() or
                "Non sono riuscito a completare l'analisi nel tempo disponibile.",
                "model": model, "steps": self.max_steps + 1, "tools_used": used}
