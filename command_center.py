"""Centro di Comando J.A.R.V.I.S.: controlli runtime degli agenti e Stanza dei Dipendenti AI.

- Agent Matrix: pausa/attivazione e sensibilità dei 7 agenti, persistite in command_center.json.
  Gli effetti sono reali e applicati da app.py:
    #1 Quant, #2 Micro, #4 Macro in pausa  -> lo sciame non genera nuove schede (l'Ensemble richiede tutti e tre)
    #5 CIO in pausa                        -> nessun nuovo acquisto/rotazione (le uscite difensive restano attive)
    #6 Guardian in pausa                   -> loop indipendente fermo (restano gli stop del Radar e del CIO)
    #7 CHOP in pausa                       -> audit/auto-healing dello sciame fermo
    #3 Risk                                -> non sospendibile: è il cancello di sicurezza del sistema
  La sensibilità (Standard / Selettivo / Rigoroso) alza il punteggio minimo dell'agente richiesto alle schede
  APPROVED_BY_RISK prima che il CIO le valuti.
- Blocchi operativi: asset class (crypto/azioni), settori e singoli ticker esclusi dai nuovi acquisti.
- Chat con i dirigenti (COO e Risk Manager): l'ordine viene interpretato (Groq in JSON, altrimenti regole),
  valutato sui dati live e applicato solo se vantaggioso; altrimenti viene spiegato perché no.
"""
import itertools
import json
import os
import re
import threading
import time
from collections import deque

import trading_core as core

STATE_PATH = os.path.join(core.DATA_DIR, "command_center.json")
CHAT_TIMEOUT_S = 8.0
CHAT_HISTORY_MAX = 80

AGENTS = {
    "01": {"name": "Quant", "title": "Agente #1 · Quant", "icon": "sigma",
           "role": "Studia i grafici con la statistica (tendenza, volatilità, anomalie) e dà un voto a ogni titolo.",
           "pausable": True, "tunable": True,
           "pattern": r"Quant|Agente #1|AGENTE #1|Hurst|GARCH|Stage 1|Scout|SCOUT|Pipeline"},
    "02": {"name": "Micro", "title": "Agente #2 · Microstruttura", "icon": "activity",
           "role": "Osserva chi compra e chi vende in tempo reale (flusso ordini) per capire se entrano i grandi investitori.",
           "pausable": True, "tunable": True,
           "pattern": r"Micro|Agente #2|AGENTE #2|OFI|VPIN|[Oo]rder ?flow|Technical & Liquidity|Orderbook"},
    "03": {"name": "Risk", "title": "Agente #3 · Risk Manager", "icon": "shield",
           "role": "Decide quanto rischiare: mette gli stop di protezione e blocca le operazioni troppo pericolose.",
           "pausable": False, "tunable": False,
           "pattern": r"Risk|Rischi|RISK|AGENTE #3|Agente #3|VETO|Drawdown|Sentiment & Compliance"},
    "04": {"name": "Macro/News", "title": "Agente #4 · Macro & News", "icon": "globe",
           "role": "Legge le notizie e il clima dei mercati mondiali (VIX, indici) per evitare le tempeste.",
           "pausable": True, "tunable": True,
           "pattern": r"Macro|MACRO|AGENTE #4|Agente #4|NEWS|NewsRadar|VIX|Pulse|Sentiment"},
    "05": {"name": "CIO", "title": "Agente #5 · CIO", "icon": "crown",
           "role": "Il direttore: riceve le proposte approvate e decide se e quanto investire.",
           "pausable": True, "tunable": True,
           "pattern": r"CIO|Agente #5|AGENTE #5|Chief of Staff|Execution Desk|Advisor|Mandato"},
    "06": {"name": "Guardian", "title": "Agente #6 · Sentinel/Guardian", "icon": "eye",
           "role": "Sorveglia ogni 20 secondi le posizioni aperte: incassa i profitti e chiude subito se qualcosa va storto.",
           "pausable": True, "tunable": False,
           "pattern": r"Guardian|GUARDIAN|Agente #6|AGENTE #6|Scheda di (uscita|ingresso)|stop"},
    "07": {"name": "CHOP", "title": "Agente #7 · CHOP Watchdog", "icon": "cpu",
           "role": "Il tecnico di sistema: controlla che lo sciame di scout funzioni ed evita blocchi e rallentamenti.",
           "pausable": True, "tunable": False,
           "pattern": r"CHOP|ChopWatchdog|Sciame|SWARM|UNIVERSE|Universo|universo"},
}
SCORE_KEYS = {"01": "agent_01_quant", "02": "agent_02_micro", "04": "agent_04_macro"}
SENSITIVITY_LABELS = {0: "Standard", 1: "Selettivo", 2: "Rigoroso"}
# Punteggio minimo dell'agente richiesto a una scheda APPROVED_BY_RISK per livello di sensibilità
SENSITIVITY_MIN = {"01": {1: 60, 2: 70}, "02": {1: 55, 2: 65}, "04": {1: 55, 2: 65}, "05": {1: 80, 2: 88}}
SWARM_AGENTS = ("01", "02", "04")   # l'Ensemble del Fusion Engine richiede tutti e tre

SECTORS = {
    "tech": {"label": "Tecnologia",
             "keywords": ("tech",),
             "symbols": {"NVDA", "AAPL", "MSFT", "TSLA", "AMD", "GOOGL", "GOOG", "AMZN", "META", "PLTR", "SMCI",
                         "SMH", "ARKK", "QQQ", "AVGO", "INTC", "ORCL", "CRM", "ADBE", "NFLX", "MU", "TSM"}},
    "commodities": {"label": "Materie prime", "keywords": ("metall", "commodit"),
                    "symbols": {"GLD", "SLV", "USO", "COPX", "UNG"}},
    "bonds": {"label": "Obbligazioni", "keywords": ("obbligaz", "treasur"), "symbols": {"TLT", "BND", "HYG"}},
    "energy": {"label": "Energia", "keywords": ("energ",), "symbols": {"XLE", "USO", "UNG", "XOM", "CVX"}},
    "finance": {"label": "Finanza", "keywords": ("finanz", "financ"), "symbols": {"XLF", "JPM", "GS", "COIN"}},
    "biotech": {"label": "Biotech", "keywords": ("biotech",), "symbols": {"XBI"}},
}
ASSET_CLASSES = {"crypto": "Crypto", "stocks": "Azioni"}

PERSONAS = {
    "coo": {"name": "COO · Capo delle Operazioni", "short": "COO", "vix_max": 25.0},
    "risk": {"name": "Risk Manager", "short": "Risk Manager", "vix_max": 20.0},
}
CONFIRM_RE = re.compile(r"\b(forza|forzalo|insisto|conferm\w*|procedi comunque|override|ordine diretto)\b", re.I)

_lock = threading.Lock()
_state = None
_chat = deque(maxlen=CHAT_HISTORY_MAX)
_chat_ids = itertools.count(1)


# --------------------------------------------------------------------------- stato persistente

def _default_state():
    return {"agents": {aid: {"paused": False, "sensitivity": 0, "updated_at": None} for aid in AGENTS},
            "blocks": {"asset_classes": [], "sectors": [], "symbols": []}}


def _load():
    global _state
    if _state is None:
        data = core.read_json_file(STATE_PATH, {}) or {}
        st = _default_state()
        for aid, a in (data.get("agents") or {}).items():
            if aid in st["agents"] and isinstance(a, dict):
                st["agents"][aid].update({k: a[k] for k in ("paused", "sensitivity", "updated_at") if k in a})
        for k in st["blocks"]:
            st["blocks"][k] = [str(x) for x in (data.get("blocks") or {}).get(k, [])]
        st["agents"]["03"]["paused"] = False      # mai sospeso, anche se il file è stato modificato a mano
        _state = st
    return _state


def _save():
    try:
        core.write_json_file(STATE_PATH, _state)
    except Exception as e:
        print(f"[!] command_center.json non salvato: {e}", flush=True)


def snapshot_state():
    with _lock:
        return json.loads(json.dumps(_load()))


def is_paused(aid):
    with _lock:
        return bool(_load()["agents"][aid]["paused"])


def swarm_paused():
    """Agenti della pipeline in pausa: con uno solo di essi fermo lo sciame non genera nuove schede."""
    with _lock:
        st = _load()
        return [aid for aid in SWARM_AGENTS if st["agents"][aid]["paused"]]


def set_agent(aid, paused=None, sensitivity=None):
    """Applica pausa/sensibilità. Solleva ValueError con un messaggio leggibile se non ammesso."""
    meta = AGENTS.get(aid)
    if not meta:
        raise ValueError(f"Agente {aid} inesistente")
    if paused and not meta["pausable"]:
        raise ValueError(f"{meta['title']} non può essere sospeso: è il cancello di sicurezza del sistema.")
    if sensitivity is not None:
        if not meta["tunable"]:
            raise ValueError(f"{meta['title']} non ha una sensibilità regolabile (parametri di sicurezza fissi).")
        if sensitivity not in SENSITIVITY_LABELS:
            raise ValueError("Sensibilità ammessa: 0 (Standard), 1 (Selettivo), 2 (Rigoroso)")
    with _lock:
        a = _load()["agents"][aid]
        if paused is not None:
            a["paused"] = bool(paused)
        if sensitivity is not None:
            a["sensitivity"] = int(sensitivity)
        a["updated_at"] = core.now_local().isoformat(timespec="seconds")
        _save()
        return dict(a)


def set_block(kind, value, blocked=True):
    key = {"asset": "asset_classes", "sector": "sectors", "symbol": "symbols"}[kind]
    with _lock:
        items = _load()["blocks"][key]
        if blocked and value not in items:
            items.append(value)
        elif not blocked and value in items:
            items.remove(value)
        _save()


def clear_blocks():
    with _lock:
        _load()["blocks"] = {"asset_classes": [], "sectors": [], "symbols": []}
        _save()


# --------------------------------------------------------------------------- filtri sul CIO

def sector_of(symbol, sector_name=""):
    """Settori (chiavi di SECTORS) a cui appartiene un ticker o un paniere."""
    sym = str(symbol).upper()
    name = (sector_name or "").lower()
    return {k for k, s in SECTORS.items() if sym in s["symbols"] or any(w in name for w in s["keywords"])}


def segment_matches(symbol, sector_name, kind, value):
    if kind == "asset":
        return core.is_crypto(symbol) == (value == "crypto")
    if kind == "sector":
        return value in sector_of(symbol, sector_name)
    return core.normalize_symbol(symbol) == core.normalize_symbol(value)


def block_reason(symbol, sector_name=""):
    """Motivo per cui un nuovo acquisto su symbol è bloccato dal Comandante (None se ammesso)."""
    st = snapshot_state()["blocks"]
    for v in st["asset_classes"]:
        if segment_matches(symbol, sector_name, "asset", v):
            return f"asset class {ASSET_CLASSES.get(v, v)} bloccata dal Comandante"
    for v in st["sectors"]:
        if segment_matches(symbol, sector_name, "sector", v):
            return f"settore {SECTORS.get(v, {}).get('label', v)} bloccato dal Comandante"
    for v in st["symbols"]:
        if segment_matches(symbol, sector_name, "symbol", v):
            return f"ticker {v} bloccato dal Comandante"
    return None


def filter_inbox(inbox):
    """Schede APPROVED_BY_RISK ammesse dai controlli runtime -> (ammesse, note sulle escluse)."""
    st = snapshot_state()
    if st["agents"]["05"]["paused"]:
        return [], [f"CIO in pausa: {len(inbox)} schede non valutate"] if inbox else []
    allowed, notes = [], []
    for p in inbox:
        sym = p["symbol"]
        why = block_reason(sym, p.get("sector", ""))
        if not why:
            q = None
            for aid, key in SCORE_KEYS.items():
                level = st["agents"][aid]["sensitivity"]
                if not level:
                    continue
                q = q if q is not None else (core.quant_rationale(sym) or {})
                score = (q.get(key) or {}).get("score")
                need = SENSITIVITY_MIN[aid][level]
                if score is not None and score < need:
                    why = f"{AGENTS[aid]['title']} {SENSITIVITY_LABELS[level]}: score {score:.0f} < {need}"
                    break
            level = st["agents"]["05"]["sensitivity"]
            if not why and level and core.pitch_conviction(p) < SENSITIVITY_MIN["05"][level]:
                why = (f"CIO {SENSITIVITY_LABELS[level]}: convinzione {core.pitch_conviction(p)} "
                       f"< {SENSITIVITY_MIN['05'][level]}")
        if why:
            notes.append(f"{sym} escluso ({why})")
        else:
            allowed.append(p)
    return allowed, notes


# --------------------------------------------------------------------------- Agent Matrix

def _clean(text):
    text = re.sub(r"^\[\d\d:\d\d:\d\d\]\s*", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def thoughts_for(aid, logs, dialogue, limit=60):
    """Flusso di pensiero di un agente: righe di log e di dialogo che lo riguardano, dalla più recente."""
    rx = re.compile(AGENTS[aid]["pattern"])
    items = [{"ts": l["ts"], "source": "log", "agent": "", "text": _clean(l["text"])} for l in logs if rx.search(l["text"])]
    items += [{"ts": d["ts"], "source": "dialogue", "agent": d["agent"], "text": d["text"], "level": d.get("level")}
              for d in dialogue if rx.search(d["agent"]) or rx.search(d["text"])]
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


def agents_snapshot(bot_active, cio_running, logs, dialogue):
    st = snapshot_state()
    now = time.time()
    out = []
    for aid, meta in AGENTS.items():
        a = st["agents"][aid]
        recent = thoughts_for(aid, logs, dialogue, limit=1)
        last = recent[0] if recent else None
        if a["paused"]:
            status = "PAUSED"
        elif not bot_active:
            status = "STANDBY"
        elif (aid == "05" and cio_running) or (last and now - last["ts"] < 25):
            status = "PROCESSING"
        else:
            status = "ACTIVE"
        if a["paused"]:
            summary = "In pausa per ordine del Comandante."
            if aid in SWARM_AGENTS:
                summary += " Lo sciame non genera nuove schede finché non viene riattivato."
        elif not bot_active:
            summary = "Sistema in pausa: in attesa di riattivazione."
        else:
            summary = last["text"] if last else "In ascolto: nessuna attività recente."
        out.append({"id": aid, **{k: meta[k] for k in ("name", "title", "icon", "role", "pausable", "tunable")},
                    "paused": a["paused"], "sensitivity": a["sensitivity"],
                    "sensitivity_label": SENSITIVITY_LABELS[a["sensitivity"]], "status": status,
                    "summary": summary[:220], "last_ts": last["ts"] if last else None})
    return {"agents": out, "blocks": st["blocks"], "block_labels": blocks_text(st["blocks"])}


def blocks_text(blocks):
    return ([ASSET_CLASSES.get(v, v) for v in blocks["asset_classes"]]
            + [SECTORS.get(v, {}).get("label", v) for v in blocks["sectors"]] + list(blocks["symbols"]))


# --------------------------------------------------------------------------- Stanza dei Dipendenti AI

INTENTS = ("pause_agent", "resume_agent", "set_sensitivity", "block", "unblock", "clear_blocks",
           "aggressiveness_up", "aggressiveness_down", "pause_bot", "resume_bot", "advisor_mode", "auto_mode",
           "status", "unknown")

_INTENT_SYSTEM = (
    "Sei il parser dei comandi di un desk di trading. Converti il messaggio dell'utente (italiano) in JSON con le chiavi: "
    "intent (uno tra: " + ", ".join(INTENTS) + "), agent (\"01\"..\"07\" o null; 01 Quant, 02 Micro/microstruttura, "
    "03 Risk, 04 Macro/News, 05 CIO, 06 Guardian/Sentinel, 07 CHOP), level (0 standard, 1 selettivo, 2 rigoroso o null), "
    "kind (\"asset\", \"sector\", \"symbol\" o null), value (asset: crypto|stocks; sector: tech|commodities|bonds|energy|"
    "finance|biotech; symbol: ticker maiuscolo, crypto come BTC-USD; altrimenti null), sector_hint (settore citato in una "
    "richiesta di aggressività, o null). 'Ferma/blocca gli acquisti su X' = block; 'riprendi/sblocca X' = unblock; "
    "'più aggressivo/più rischio' = aggressiveness_up; 'più prudente/meno rischio' = aggressiveness_down; "
    "'solo consigli/non eseguire ordini' = advisor_mode; domande sullo stato = status. Rispondi SOLO con il JSON."
)
_groq = None


def _llm_parse(message):
    global _groq
    if not core.GROQ_KEY:
        return None
    try:
        import groq
        if _groq is None:
            _groq = groq.Groq(api_key=core.GROQ_KEY, timeout=CHAT_TIMEOUT_S, max_retries=0)
        res = _groq.chat.completions.create(
            model=core.GROQ_MODELS[0], max_tokens=150, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _INTENT_SYSTEM}, {"role": "user", "content": message[:500]}])
        data = json.loads(res.choices[0].message.content)
        return data if data.get("intent") in INTENTS else None
    except Exception as e:
        print(f"[chat] Groq non disponibile, uso il parser a regole: {str(e)[:120]}", flush=True)
        return None


_AGENT_WORDS = [("01", r"quant"), ("02", r"micro"), ("03", r"risk|rischi"), ("04", r"macro|news|notizi"),
                ("05", r"\bcio\b|direttor"), ("06", r"guardian|sentinel|sentinella"), ("07", r"chop|watchdog")]
_SECTOR_WORDS = [("tech", r"tech|tecnolog"), ("commodities", r"materie prime|commodit|metall|oro"),
                 ("bonds", r"obbligaz|bond|treasur"), ("energy", r"energ|petrol"), ("finance", r"finanz|banc"),
                 ("biotech", r"biotech")]


def _rule_parse(message):
    m = message.lower()
    agent = next((aid for aid, rx in _AGENT_WORDS if re.search(rf"(agente\s*#?\s*{int(aid)}\b)|{rx}", m)), None)
    asset = "crypto" if re.search(r"crypto|cripto|bitcoin|btc", m) else ("stocks" if re.search(r"\bazion", m) else None)
    sector = next((k for k, rx in _SECTOR_WORDS if re.search(rx, m)), None)
    ticker = None
    for t in re.findall(r"\b[A-Z]{2,5}(?:-USD)?\b", message):
        if t not in {"CIO", "COO", "CHOP", "ETF", "USD", "VIX", "AI", "PNL", "OK", "IA", "NO", "SI", "TUTTO"}:
            ticker = t
            break
    stop_words = r"ferm|blocc|stop|sospend|escludi|evita|non compr|smetti|vieta"
    go_words = r"riprend|sblocc|riattiv|attiva|riavvia|consenti|ricomincia|riparti"
    level = 2 if re.search(r"rigoros|massim", m) else 1 if re.search(r"selettiv|più sensibil|alza", m) else \
        0 if re.search(r"standard|normale|default|abbass", m) else None
    out = {"intent": "unknown", "agent": agent, "level": level, "kind": None, "value": None, "sector_hint": sector}
    if re.search(r"sensibil", m) and agent:
        out["intent"] = "set_sensitivity"
    elif re.search(r"aggressiv|più rischio|osa|spingi|aumenta (l'|la )?esposizion", m):
        out["intent"] = "aggressiveness_down" if re.search(r"meno|riduc|abbass|diminu", m) else "aggressiveness_up"
    elif re.search(r"prudent|meno rischio|riduc\w* (il )?rischio|difensiv|cautel", m):
        out["intent"] = "aggressiveness_down"
    elif re.search(r"advisor|solo consigli|non eseguire|niente ordini", m):
        out["intent"] = "advisor_mode"
    elif re.search(r"auto.?trading|esegui gli ordini|modalità automatica", m):
        out["intent"] = "auto_mode"
    elif re.search(r"(togli|rimuovi|cancella|azzera) (tutti )?i blocchi|sblocca tutto", m):
        out["intent"] = "clear_blocks"
    elif asset or sector or (ticker and not agent):
        kind, value = (("sector", sector) if sector else ("asset", asset) if asset else ("symbol", ticker))
        out.update(kind=kind, value=value)
        out["intent"] = "unblock" if re.search(go_words, m) else "block" if re.search(stop_words, m) else "status"
    elif agent:
        out["intent"] = "resume_agent" if re.search(go_words, m) else "pause_agent" if re.search(stop_words + r"|pausa", m) \
            else "status"
    elif re.search(r"(metti|tutto) in pausa|ferma (tutto|il bot|il sistema)|spegni", m):
        out["intent"] = "pause_bot"
    elif re.search(r"riprendi|riattiva|riavvia|accendi", m):
        out["intent"] = "resume_bot"
    elif re.search(r"come (va|stiamo|sta)|stato|situazione|report|riepilogo|quanto|profitt|saldo|\?", m):
        out["intent"] = "status"
    return out


def parse_command(message):
    parsed = _llm_parse(message)
    source = "Groq"
    if not parsed:
        parsed, source = _rule_parse(message), "regole"
    for key in ("agent", "level", "kind", "value", "sector_hint"):
        parsed.setdefault(key, None)
    if parsed["agent"] is not None:
        parsed["agent"] = str(parsed["agent"]).zfill(2)[-2:]
        if parsed["agent"] not in AGENTS:
            parsed["agent"] = None
    if parsed["value"] and parsed["kind"] == "symbol":
        value = str(parsed["value"]).upper()
        parsed["value"] = value + "-USD" if value + "-USD" in core.CRYPTO_EXTENDED else value
    try:
        parsed["level"] = int(parsed["level"]) if parsed["level"] is not None else None
    except (TypeError, ValueError):
        parsed["level"] = None
    return parsed, source


def _segment_label(kind, value):
    if kind == "asset":
        return ASSET_CLASSES.get(value, value)
    if kind == "sector":
        return SECTORS.get(value, {}).get("label", value)
    return value


def _segment_impact(ctx, kind, value):
    """Peso del segmento sulle opportunità correnti (schede attive e migliori score dello sciame) e sul PnL aperto."""
    queue = [q for q in ctx["radar"].get("queue", []) if q.get("status") in ("SUBMITTED_PITCH", "UNDER_REVIEW", "APPROVED_BY_RISK")]
    top = [t for t in (ctx["radar"].get("channels", {}) or {}).get("top", []) if (t.get("score") or 0) >= core.SCORE_BUY - 10]
    pool = [(q["symbol"], q.get("sector"), q.get("score") or 0) for q in queue] + \
           [(t["symbol"], t.get("sector"), t.get("score") or 0) for t in top]
    weight = sum(max(s, 1) for _, _, s in pool)
    seg = sum(max(s, 1) for sym, sec, s in pool if segment_matches(sym, sec or "", kind, value))
    approved = [q["symbol"] for q in queue if q.get("status") == "APPROVED_BY_RISK"
                and segment_matches(q["symbol"], q.get("sector") or "", kind, value)]
    gains = sum(max(p["unrealized_pl"], 0) for p in ctx["positions"])
    seg_gain = sum(max(p["unrealized_pl"], 0) for p in ctx["positions"]
                   if segment_matches(p["yf_symbol"], "", kind, value))
    return {"opp_share": round(seg / weight * 100) if weight else 0, "opp_count": len(pool), "approved": approved,
            "gain_share": round(seg_gain / gains * 100) if gains else 0}


def _decide(cmd, ctx, persona, force):
    """Valuta e (se ammesso) applica l'ordine. -> (verdetto, testo, modifiche applicate)."""
    p = PERSONAS[persona]
    intent, aid = cmd["intent"], cmd["agent"]
    cfg = core.get_config()
    locked = core.env_overrides()
    vix = ctx.get("vix")
    dd_blocked = ctx.get("drawdown_blocked")
    open_pos = len(ctx["positions"])

    if intent in ("pause_agent", "resume_agent", "set_sensitivity") and not aid:
        return "CHIARIMENTO", "A quale agente si riferisce? Posso agire su #1 Quant, #2 Micro, #3 Risk, #4 Macro/News, #5 CIO, #6 Guardian e #7 CHOP.", None

    if intent == "pause_agent":
        meta = AGENTS[aid]
        if not meta["pausable"]:
            return "IMPOSSIBILE", (f"Comandante, {meta['title']} non può essere sospeso: è il cancello che applica stop "
                                   "loss e limiti di esposizione. Senza di lui ogni ordine partirebbe senza protezione. "
                                   "Se vuole ridurre l'attività, posso rendere più selettivi il Quant o il CIO."), None
        if aid == "06" and open_pos and not force:
            return "SCONSIGLIATO", (f"Comandante, il Guardian sta proteggendo {open_pos} posizioni aperte: incassa i profitti "
                                    "al Target 2R e chiude subito in caso di inversione. Sospenderlo lascerebbe solo gli "
                                    "stop di riserva del Radar. Consiglio di mantenerlo attivo (scriva \"conferma\" per "
                                    "forzare l'ordine)."), None
        if aid == "05" and not force:
            imp = len([q for q in ctx["radar"].get("queue", []) if q.get("status") == "APPROVED_BY_RISK"])
            if imp:
                return "SCONSIGLIATO", (f"Comandante, il CIO ha {imp} schede già approvate dal Comitato Rischi in attesa "
                                        "di decisione: metterlo in pausa ora le lascerebbe scadere. Le uscite difensive "
                                        "resterebbero comunque attive. Scriva \"conferma\" se vuole procedere."), None
        set_agent(aid, paused=True)
        extra = {"01": " Lo sciame smette di generare nuove schede: l'Ensemble richiede il suo voto.",
                 "02": " Lo sciame smette di generare nuove schede: l'Ensemble richiede il suo voto.",
                 "04": " Lo sciame smette di generare nuove schede: l'Ensemble richiede il suo voto.",
                 "05": " Nessun nuovo acquisto; le uscite difensive restano operative.",
                 "06": " Restano attivi gli stop di riserva del Radar e del CIO.",
                 "07": " L'auto-healing dello sciame è sospeso."}[aid]
        return "ESEGUITO", f"Ricevuto. {meta['title']} è in pausa.{extra}", {"agent": aid, "paused": True}

    if intent == "resume_agent":
        if not is_paused(aid):
            return "INFO", f"{AGENTS[aid]['title']} è già operativo, Comandante.", None
        set_agent(aid, paused=False)
        return "ESEGUITO", f"{AGENTS[aid]['title']} è di nuovo operativo.", {"agent": aid, "paused": False}

    if intent == "set_sensitivity":
        meta = AGENTS[aid]
        level = cmd["level"] if cmd["level"] is not None else 1
        if not meta["tunable"]:
            return "IMPOSSIBILE", (f"{meta['title']} lavora con parametri di sicurezza fissi (stop -1.5% / -2.5%, Target 2R) "
                                   "che non conviene toccare. Posso invece regolare la sensibilità di Quant, Micro, "
                                   "Macro/News o CIO."), None
        set_agent(aid, sensitivity=level)
        need = SENSITIVITY_MIN.get(aid, {}).get(level)
        return "ESEGUITO", (f"Sensibilità di {meta['title']} impostata su {SENSITIVITY_LABELS[level]}"
                            + (f": il CIO valuterà solo schede con punteggio dell'agente ≥ {need}." if need
                               else ": nessun filtro aggiuntivo.")), {"agent": aid, "sensitivity": level}

    if intent in ("block", "unblock"):
        kind, value = cmd["kind"], cmd["value"]
        valid = (kind == "asset" and value in ASSET_CLASSES) or (kind == "sector" and value in SECTORS) or \
                (kind == "symbol" and value and re.match(r"^[A-Z0-9.\-]{1,15}$", value))
        if not valid:
            return "CHIARIMENTO", ("Non ho capito su quale mercato intervenire. Posso bloccare Crypto o Azioni, un settore "
                                   "(Tecnologia, Materie prime, Obbligazioni, Energia, Finanza, Biotech) o un ticker."), None
        label = _segment_label(kind, value)
        if intent == "unblock":
            set_block(kind, value, blocked=False)
            return "ESEGUITO", f"{label} di nuovo disponibile per i nuovi acquisti.", {"unblock": label}
        imp = _segment_impact(ctx, kind, value)
        if not force and (imp["approved"] or (imp["opp_count"] >= 2 and imp["opp_share"] >= 40)):
            why = []
            if imp["opp_share"]:
                why.append(f"vale il {imp['opp_share']}% delle opportunità che lo sciame sta seguendo")
            if imp["approved"]:
                why.append(f"ci sono schede già approvate dal Comitato Rischi ({', '.join(imp['approved'][:4])})")
            return "SCONSIGLIATO", (f"Comandante, bloccare {label} ora taglierebbe una parte rilevante dei profitti attesi: "
                                    + " e ".join(why) + ". Il Risk Manager ha già validato quei rischi. Consiglio di "
                                    "mantenere l'operatività attuale; se preferisce procedere scriva \"conferma\"."), None
        set_block(kind, value, blocked=True)
        note = (f" Le posizioni già aperte restano sotto la protezione del Guardian"
                f"{' (contribuiscono al ' + str(imp['gain_share']) + '% dei guadagni aperti)' if imp['gain_share'] else ''}.")
        return "ESEGUITO", f"Fatto: nessun nuovo acquisto su {label}.{note}", {"block": label}

    if intent == "clear_blocks":
        clear_blocks()
        return "ESEGUITO", "Tutti i blocchi rimossi: il CIO può di nuovo valutare ogni mercato.", {"blocks": "cleared"}

    if intent == "aggressiveness_up":
        cur = float(cfg["max_exposure_pct"])
        hint = f" su {SECTORS.get(cmd['sector_hint'], {}).get('label', cmd['sector_hint'])}" if cmd.get("sector_hint") else ""
        if "max_exposure_pct" in locked:
            return "IMPOSSIBILE", ("L'esposizione massima è fissata da una variabile d'ambiente su Render "
                                   f"({core.ENV_OVERRIDES['max_exposure_pct']}): va modificata lì."), None
        if dd_blocked:
            return "SCONSIGLIATO", ("Comandante, il Drawdown Controller ha bloccato gli acquisti per la perdita giornaliera: "
                                    "aumentare l'aggressività ora significherebbe inseguire le perdite. Consiglio di "
                                    "attendere la fine del blocco."), None
        if vix is not None and vix > p["vix_max"] and not force:
            return "SCONSIGLIATO", (f"Comandante, il VIX è a {vix}: i mercati sono nervosi (soglia {p['vix_max']:.0f} per il "
                                    f"{p['short']}). Alzare l'aggressività{hint} ora aumenterebbe le perdite potenziali più "
                                    "dei guadagni attesi. Consiglio di mantenere la soglia attuale."), None
        if cur >= 50:
            return "IMPOSSIBILE", ("Siamo già al massimo consentito dalla Safety Net: 50% del capitale investito e 50% "
                                   "di cassa protetta. Oltre questa soglia una sola giornata negativa potrebbe intaccare "
                                   "seriamente il capitale."
                                   + (f" Non esiste una leva di aggressività per singolo settore{hint}: posso però "
                                      "bloccare gli altri settori per concentrare il capitale." if hint else "")), None
        new = min(50.0, cur + 10)
        core.update_config({"max_exposure_pct": new})
        return "ESEGUITO", (f"Aggressività aumentata: esposizione massima da {cur:.0f}% a {new:.0f}% del capitale."
                            + (f" Nota: la leva è globale, non solo{hint}." if hint else "")), {"max_exposure_pct": new}

    if intent == "aggressiveness_down":
        cur = float(cfg["max_exposure_pct"])
        if "max_exposure_pct" in locked:
            return "IMPOSSIBILE", f"L'esposizione massima è fissata da {core.ENV_OVERRIDES['max_exposure_pct']} su Render.", None
        if cur <= 10:
            return "INFO", "Siamo già al livello più prudente: 10% investito, 90% di cassa protetta.", None
        new = max(10.0, cur - 10)
        core.update_config({"max_exposure_pct": new})
        return "ESEGUITO", (f"Profilo più prudente: esposizione massima da {cur:.0f}% a {new:.0f}%. Le posizioni aperte "
                            "non vengono vendute, ma i nuovi acquisti si fermano oltre la nuova soglia."), {"max_exposure_pct": new}

    if intent in ("advisor_mode", "auto_mode"):
        want = intent == "auto_mode"
        if "auto_execute_trades" in locked:
            return "IMPOSSIBILE", (f"La modalità è fissata da {core.ENV_OVERRIDES['auto_execute_trades']} su Render: "
                                   "va modificata lì."), None
        if want and dd_blocked and persona == "risk":
            return "SCONSIGLIATO", "Con il Drawdown Controller attivo consiglio di restare in modalità Advisor.", None
        core.update_config({"auto_execute_trades": want})
        return "ESEGUITO", ("Auto-Trading attivo: gli ordini vengono eseguiti." if want else
                            "Modalità Advisor: il sistema propone ma non invia più ordini."), {"auto_execute_trades": want}

    if intent in ("pause_bot", "resume_bot"):
        return "ESEGUITO", None, {"bot_active": intent == "resume_bot"}

    return "INFO", status_text(ctx, persona), None


def status_text(ctx, persona):
    acc = ctx["account"]
    eq = acc.get("portfolio") or 0
    exp = (acc.get("exposure") or 0) / eq * 100 if eq else 0
    st = snapshot_state()
    paused = [AGENTS[a]["name"] for a, v in st["agents"].items() if v["paused"]]
    parts = [f"Saldo {acc.get('portfolio', 0):,.2f}$, oggi {acc.get('daily_pnl_usd', 0):+,.2f}$ "
             f"({acc.get('daily_pnl_pct', 0):+.2f}%)",
             f"{exp:.0f}% investito e {100 - exp:.0f}% in cassa, {len(ctx['positions'])} posizioni aperte"]
    if ctx.get("vix") is not None:
        parts.append(f"VIX {ctx['vix']}")
    if paused:
        parts.append("agenti in pausa: " + ", ".join(paused))
    blocks = blocks_text(st["blocks"])
    if blocks:
        parts.append("acquisti bloccati su " + ", ".join(blocks))
    lead = "Rapporto operativo" if persona == "coo" else "Quadro dei rischi"
    return (f"{lead}, Comandante: " + "; ".join(parts) + ". Posso mettere in pausa un agente, bloccare un mercato, "
            "regolare l'aggressività o la sensibilità degli agenti.")


def chat(persona, message, ctx, apply_bot_state):
    """Messaggio al dirigente -> risposta. apply_bot_state(active) mette in pausa/riattiva il bot."""
    persona = persona if persona in PERSONAS else "coo"
    message = (message or "").strip()[:800]
    _push("user", persona, message)
    cmd, source = parse_command(message)
    try:
        verdict, text, change = _decide(cmd, ctx, persona, force=bool(CONFIRM_RE.search(message)))
    except ValueError as e:
        verdict, text, change = "IMPOSSIBILE", str(e), None
    if change and "bot_active" in change:
        apply_bot_state(change["bot_active"])
        text = ("Sistema riattivato: gli agenti riprendono il lavoro." if change["bot_active"] else
                "Sistema in pausa: nessuna nuova scansione né acquisto. Le posizioni aperte restano dove sono.")
    reply = _push("agent", persona, text, verdict=verdict, intent=cmd["intent"], parser=source, change=change)
    return reply


def _push(role, persona, text, **extra):
    entry = {"ts": time.time(), "time": core.now_local().strftime("%H:%M:%S"), "role": role, "persona": persona,
             "author": "Comandante" if role == "user" else PERSONAS[persona]["name"], "text": text, **extra}
    with _lock:
        entry["id"] = next(_chat_ids)
        _chat.append(entry)
    return entry


def chat_history(persona=None):
    with _lock:
        return [m for m in _chat if persona in (None, m["persona"])]
