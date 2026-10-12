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
- Chat con i dirigenti (COO e Risk Manager): assistente conversazionale Groq con la mappa dell'architettura e lo
  stato live del sistema (conto, posizioni, VIX, sciame, bocciature, log). Risponde a qualsiasi domanda; quando
  un'azione è utile la PROPONE e la applica solo dopo la conferma esplicita dell'utente ("sì", "conferma").
  Senza Groq resta un parser a regole di riserva, con la stessa conferma obbligatoria.
"""
import itertools
import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import trading_core as core

STATE_PATH = os.path.join(core.DATA_DIR, "command_center.json")
CHAT_TIMEOUT_S = 6.0            # budget TOTALE (wall-clock) per la risposta di Groq; oltre -> riserva locale
CHAT_HISTORY_MAX = 80
CHAT_TURNS_IN_PROMPT = 12        # ultimi messaggi della conversazione passati all'LLM
PROPOSAL_TTL_SEC = 600           # una proposta non confermata entro 10 minuti decade

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
# Risposta a una proposta in sospeso: conferma o annullamento espliciti (a inizio messaggio)
CONFIRM_RE = re.compile(r"^\s*(s[iì]|conferm\w*|procedi|ok|okay|va bene|vai|esegui|fallo|d'accordo|certo|approv\w*)\b", re.I)
CANCEL_RE = re.compile(r"^\s*(no|annulla|lascia (stare|perdere)|niente|non (farlo|procedere)|rifiut\w*)\b", re.I)

_lock = threading.Lock()
_state = None
_chat = deque(maxlen=CHAT_HISTORY_MAX)
_chat_ids = itertools.count(1)
_pending = {}                    # persona -> proposta in attesa di conferma {"cmd", "summary", "ts"}


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
ACTION_INTENTS = tuple(i for i in INTENTS if i not in ("status", "unknown"))

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


def normalize_command(parsed):
    """Comando (dall'LLM o dalle regole) con chiavi complete e valori validati."""
    parsed = dict(parsed or {})
    if parsed.get("intent") not in INTENTS:
        parsed["intent"] = "unknown"
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
    return parsed


def parse_command(message):
    """Parser a regole di riserva (Groq non disponibile)."""
    return normalize_command(_rule_parse(message)), "regole"


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
            return "IMPOSSIBILE", (f"{meta['title']} lavora con parametri di sicurezza fissi (stop 1.5x ATR nella fascia 1.2-3.5%, Target 1 a 2R) "
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
    return "; ".join(parts) + "."


# --------------------------------------------------------------------------- assistente conversazionale (Groq)

ARCHITECTURE = f"""ARCHITETTURA DEL BOT (Quant Desk multi-agente, conto Alpaca, azioni USA + crypto, solo posizioni long)
Flusso: Scout -> Stage 1-3 (Agenti #1 #2 #4 -> Fusion Engine #5, con #3 e #6) -> Comitato Rischi -> CIO (#5) -> Execution Desk; #6 sorveglia le posizioni, #7 il sistema.
- Universo e Scout: universo dinamico dei soli asset negoziabili su Alpaca (S&P 500, Nasdaq-100, screener Yahoo, movers Alpaca e crypto /USD di Alpaca ordinate per volume), scansionato a rotazione in blocchi di {core.UNIVERSE_CHUNK_SIZE} ticker (a mercato USA chiuso solo crypto); la watchlist è inclusa in ogni blocco. Un giro completo dell'universo richiede più blocchi; senza universo dinamico si ruotano panieri statici. 100 Scout in 6 categorie (breakout, volatilità, orderbook, volumi, balene, mean reversion). Le anomalie diventano "schede" (pitch) con TTL {core.PROPOSAL_TTL_MIN} minuti.
- Agente #1 Quant: statistica sulle candele 1h chiuse (esponente di Hurst, Z-score, volatilità GARCH(1,1), stabilità spettrale di Koopman, limiti conformal, traiettoria attesa). Voto 0-100.
- Agente #2 Microstruttura: OFI dal book L2 di Alpaca per le crypto, stimato dalle candele per le azioni (Alpaca non fornisce L2 azionario); VPIN, iceberg, RVOL, lambda di Kyle. OFI <= -0.5 su una posizione = uscita anticipata.
- Agente #3 Risk Manager (non sospendibile): hard stop dinamico Stop = max(1.2%, min(3.5%, 1.5 x ATR% giornaliero)) ricalcolato sulla volatilità reale di ogni posizione, Target 1 = 2 x Stop, CVaR, beta, sizing, veto. Safety Net: esposizione massima 50% del capitale, massimo 4 posizioni, perdita massima per trade {core.MAX_RISK_PER_TRADE_PCT:g}% del capitale, nessuna nuova crypto tra le 22:00 e le 08:00. Circuit breaker e Drawdown Controller: perdita giornaliera oltre {abs(core.DAILY_DRAWDOWN_LIMIT):g}% (rispetto al massimo tra chiusura precedente e picco intraday) blocca i nuovi acquisti per 24 ore.
- Agente #4 Macro & News: VIX (>= 28 = panico, veto sui nuovi ingressi; > {core.VIX_RISK_CONTRACTION:.0f} = contrazione del rischio, asset ad alto beta bloccati), regime di mercato (SPY, QQQ e BTC rispetto alla EMA50 giornaliera), blackout trimestrali. News Radar (Finnhub, Polygon, RSS Yahoo, SEC 8-K) valutato da Groq: impact, catalizzatore, tesi; notizie più vecchie di 30 minuti valgono 0; spinta quantitativa forte senza notizia fresca = veto. Il Fear & Greed (alternative.me) vale solo per le crypto.
- Agente #5 CIO / Fusion Engine: Ensemble Score = Quant x 0.50 + News x 0.35 + OFI x 0.15. Ingresso solo con Ensemble >= {core.PIPELINE_BUY_SCORE:.0f}. Convinzione -> allocazione: 72-79 = 8-15%, 80-89 = 15-25%, 90+ SUPER_CONVICTION = 35-50%; in regime RISK-OFF allocazione dimezzata. Può ruotare capitale solo da posizioni con tesi degradata verso un SUPER_CONVICTION. Nessuna vendita discrezionale: le uscite sono solo del Guardian.
- Comitato Rischi: ogni scheda passa da 3 gatekeeper (Tecnico & Liquidità, Sentiment & Compliance, Risk & ATR) più il controllo del Fusion Engine; un solo veto la respinge (cooldown 60 minuti).
- Agente #6 Guardian: ogni {core.GUARDIAN_INTERVAL_SEC} secondi su ogni posizione. Hard stop sempre attivo; Target 1 a {core.TARGET_RISK_REWARD:.0f}R: vende il 50% e porta lo stop del resto a breakeven + commissioni; il runner segue il Trailing ATR Stop (Chandelier, 1.5x ATR azioni, 2x crypto) senza tetto. Uscite anticipate solo per Thesis Decay (#4), Orderbook Reversal (#2), News Shock (VIX >= 28 o +20% dall'ingresso). NESSUN time-stop.
- Agente #7 CHOP Watchdog: salute dello sciame, auto-healing degli scout bloccati, timeout di Groq a 2 secondi, audit ogni 30 secondi.
- Rischio Zero (pulsante sul portafoglio): su una posizione in profitto vende subito il 50% e porta lo stop del resto a breakeven + commissioni; il resto resta gestito dal Guardian.
- Modalità: Auto-Trading (ordini inviati) o Advisor (solo suggerimenti). Le azioni USA si negoziano lun-ven 09:30-16:00 New York; le crypto h24.
- Centro di Comando: pausa/attivazione agenti (#3 mai), sensibilità (Standard/Selettivo/Rigoroso) di #1 #2 #4 #5, blocchi su asset class/settori/ticker, aggressività = esposizione massima tra 10% e 50%."""

_PERSONA_STYLE = {
    "coo": "Sei il COO (Capo delle Operazioni) del desk: pratico, orientato all'operatività e ai risultati.",
    "risk": "Sei il Risk Manager del desk: prudente, metti sempre in evidenza rischi, drawdown e protezioni.",
}

_CHAT_RULES = """REGOLE DI RISPOSTA
- Parla in italiano, con linguaggio semplice, fluido e naturale, come un collega esperto. Niente formule fisse, niente elenchi inutili. Di solito 2-6 frasi; più dettagli solo se richiesti.
- Rispondi a qualsiasi domanda: funzionamento del software, mercati e concetti finanziari, stato del portafoglio.
- Usa SOLO i dati dello STATO LIVE per numeri e fatti sul sistema. Se un dato manca dillo, non inventarlo.
- Se chiedono perché il portafoglio è fermo o perché non si compra, ragiona sullo stato live e sui log: bot in pausa, modalità Advisor, mercato chiuso, VIX alto, drawdown, esposizione al limite, agenti in pausa, blocchi, nessuna scheda con Ensemble >= 72, veti delle notizie, cooldown. Indica la causa concreta con i numeri.
- NON applichi mai nulla di tua iniziativa. Se un'azione del Centro di Comando è utile o richiesta, spiegala (cosa cambia, pro e rischi) e mettila in "proposal": verrà eseguita SOLO se l'utente risponde confermando. La richiesta di conferma viene aggiunta automaticamente in fondo: non ripeterla.
- Non proporre mai ordini di acquisto/vendita su singoli titoli: non sono tra le azioni disponibili (l'utente può usare i pulsanti del portafoglio, es. Rischio Zero o Vendi subito).
FORMATO: rispondi SOLO con un oggetto JSON {"reply": "testo per l'utente", "proposal": null oppure {...}}.
proposal (solo se proponi un'azione): {"intent": uno tra """ + ", ".join(ACTION_INTENTS) + """, "agent": "01".."07" o null, "level": 0|1|2 o null (sensibilità: 0 Standard, 1 Selettivo, 2 Rigoroso), "kind": "asset"|"sector"|"symbol" o null, "value": (asset: crypto|stocks; sector: tech|commodities|bonds|energy|finance|biotech; symbol: ticker maiuscolo, crypto come BTC-USD) o null, "sector_hint": null, "summary": "descrizione breve dell'azione"}.
Significato: pause_agent/resume_agent (agent), set_sensitivity (agent, level), block/unblock nuovi acquisti (kind, value), clear_blocks, aggressiveness_up (+10 punti di esposizione massima, max 50%), aggressiveness_down (-10, min 10%), pause_bot/resume_bot (tutto il sistema), advisor_mode (nessun ordine), auto_mode (ordini eseguiti)."""


def _fmt(v, nd=2):
    return "N/D" if v is None else f"{v:,.{nd}f}" if isinstance(v, (int, float)) else str(v)


def live_state_text(ctx):
    """Fotografia dello stato reale del sistema per il System Prompt."""
    acc = ctx.get("account") or {}
    eq = acc.get("portfolio") or 0
    exposure = acc.get("exposure") or 0
    cfg = ctx.get("config") or {}
    st = snapshot_state()
    lines = [f"Ora del bot: {core.now_local().strftime('%Y-%m-%d %H:%M')} ({core.now_local().strftime('%A')})",
             f"Sistema: {'ATTIVO' if ctx.get('bot_active', True) else 'IN PAUSA'} · stato '{ctx.get('bot_status', 'N/D')}' · "
             f"ultimo ciclo CIO {ctx.get('last_scan', 'N/D')} · modalità "
             f"{'Auto-Trading' if cfg.get('auto_execute_trades') else 'Advisor (nessun ordine)' if cfg else 'N/D'}",
             f"Mercato azionario USA: {'APERTO' if ctx.get('market_open') else 'CHIUSO' if ctx.get('market_open') is not None else 'N/D'} (crypto sempre aperte)",
             f"Conto: patrimonio ${_fmt(eq)}, cassa ${_fmt(acc.get('cash'))}, buying power ${_fmt(acc.get('buying_power'))}, "
             f"investito ${_fmt(exposure)} ({exposure / eq * 100 if eq else 0:.1f}%), esposizione massima "
             f"{_fmt(cfg.get('max_exposure_pct'), 0)}%, PnL oggi ${_fmt(acc.get('daily_pnl_usd'))} ({_fmt(acc.get('daily_pnl_pct'))}%)",
             f"VIX: {_fmt(ctx.get('vix'))} · Drawdown Controller: {'BLOCCA gli acquisti' if ctx.get('drawdown_blocked') else 'ok'}"]
    macro = ctx.get("macro") or {}
    if macro.get("regime"):
        lines.append(f"Regime di mercato: {json.dumps(macro['regime'], ensure_ascii=False)[:300]}")
    paused = [AGENTS[a]["title"] for a, v in st["agents"].items() if v["paused"]]
    tuned = [f"{AGENTS[a]['title']} {SENSITIVITY_LABELS[v['sensitivity']]}" for a, v in st["agents"].items() if v["sensitivity"]]
    lines.append("Agenti in pausa: " + (", ".join(paused) or "nessuno")
                 + " · Sensibilità non standard: " + (", ".join(tuned) or "nessuna")
                 + " · Blocchi acquisti: " + (", ".join(blocks_text(st["blocks"])) or "nessuno"))

    positions = ctx.get("positions") or []
    lines.append(f"\nPOSIZIONI APERTE ({len(positions)}):")
    for p in positions[:10]:
        lines.append(f"- {p['symbol']}: qty {p['qty']:g}, ingresso ${_fmt(p.get('avg_entry_price'), 4)}, prezzo "
                     f"${_fmt(p.get('current_price'), 4)}, valore ${_fmt(p.get('market_value'))}, PnL ${_fmt(p.get('unrealized_pl'))} "
                     f"({_fmt(p.get('unrealized_plpc'))}%)"
                     + (f", stop effettivo {p['effective_stop_pct']:+.2f}%" if p.get("effective_stop_pct") is not None else "")
                     + (" , runner (metà già incassata)" if p.get("scaled_out") else "")
                     + (f" · Guardian: {p['hold_rationale']}" if p.get("hold_rationale") else ""))
    if not positions:
        lines.append("- nessuna")

    cio = ctx.get("cio") or {}
    if cio:
        lines.append(f"\nULTIMO MANDATO CIO ({cio.get('timestamp', '?')}, {cio.get('trigger', '')}): {cio.get('action')} "
                     f"{cio.get('buy_symbol') or cio.get('sell_symbol') or ''} — {str(cio.get('reason') or '')[:300]}")

    radar = ctx.get("radar") or {}
    channels = radar.get("channels") or {}
    top = channels.get("top") or []
    if top:
        lines.append("\nMIGLIORI SCORE DELLO SCIAME (ultimo giro): " + ", ".join(
            f"{t['symbol']} {_fmt(t.get('score'), 0)}" for t in top[:10]))
    queue = radar.get("queue") or []
    lines.append(f"Schede in coda: {len(queue)}" + (": " + "; ".join(
        f"{q['symbol']} {q['status']} score {_fmt(q.get('score'), 0)}" for q in queue[:8]) if queue else ""))
    recent = radar.get("recent") or []
    if recent:
        lines.append("Schede chiuse di recente: " + "; ".join(
            f"{q['symbol']} {q['status']}" + (f" ({str(q.get('note') or '; '.join(q.get('vetoes') or []))[:120]})"
                                               if q.get("note") or q.get("vetoes") else "") for q in recent[:8]))
    if radar.get("cooldown"):
        lines.append("Ticker in cooldown dopo un veto: " + ", ".join(f"{c['symbol']} ({c['minutes']} min)"
                                                                   for c in radar["cooldown"][:10]))
    rejected = ctx.get("rejected") or []
    if rejected:
        lines.append("\nULTIME BOCCIATURE DELLA PIPELINE (motivo):")
        for r in rejected[:12]:
            lines.append(f"- {r.get('time', '')} {r['symbol']} [{r.get('stage')}] {r.get('status')}: "
                         f"{str(r.get('reason') or '')[:160]}" + (f" (score {_fmt(r.get('score'), 0)})" if r.get("score") is not None else ""))
    logs = ctx.get("logs") or []
    if logs:
        lines.append("\nLOG RECENTI (dal più vecchio al più recente):")
        lines += [_clean(l["text"])[:220] for l in logs[-35:]]
    return "\n".join(lines)


def build_system_prompt(persona, ctx):
    pending = _pending.get(persona)
    extra = (f"\nPROPOSTA IN ATTESA DI CONFERMA: {pending['summary']} (se l'utente ne parla, ricordagli che basta rispondere "
             "\"sì\" per applicarla o \"no\" per annullarla).") if pending else ""
    return "\n\n".join([_PERSONA_STYLE.get(persona, _PERSONA_STYLE["coo"])
                        + " Lavori nella sala operativa di un bot di trading e parli con il suo proprietario.",
                        ARCHITECTURE, "STATO LIVE DEL SISTEMA\n" + live_state_text(ctx) + extra, _CHAT_RULES])


_groq = None


def _groq_client():
    global _groq
    if _groq is None:
        import groq
        _groq = groq.Groq(api_key=core.GROQ_KEY, timeout=CHAT_TIMEOUT_S, max_retries=0)
    return _groq


_llm_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-llm")


def _llm_request(messages, deadline):
    """Prova i modelli Groq finché resta tempo nel budget. Solleva l'ultimo errore se nessuno risponde."""
    last_error = TimeoutError("budget esaurito")
    for model in core.GROQ_MODELS[:3]:
        remaining = deadline - time.monotonic()
        if remaining < 0.5:
            break
        try:
            res = _groq_client().chat.completions.create(model=model, max_tokens=600, temperature=0.4,
                                                         response_format={"type": "json_object"}, messages=messages,
                                                         timeout=remaining)
            data = json.loads(res.choices[0].message.content)
            if not str(data.get("reply") or "").strip():
                raise ValueError("risposta vuota")
            return data, model
        except Exception as e:
            last_error = e
    raise last_error


def _llm_chat(persona, message, ctx):
    """Risposta conversazionale dell'LLM -> {"reply", "proposal"}; None se Groq manca, sbaglia o supera CHAT_TIMEOUT_S."""
    if not core.GROQ_KEY:
        return None
    started = time.monotonic()
    try:
        history = [m for m in chat_history(persona) if m.get("text")][-CHAT_TURNS_IN_PROMPT - 1:-1]   # senza il messaggio appena salvato
        messages = [{"role": "system", "content": build_system_prompt(persona, ctx)}]
        messages += [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"][:1500]} for m in history]
        messages.append({"role": "user", "content": message})
        deadline = started + CHAT_TIMEOUT_S
        # Timeout rigoroso sul tempo totale: il timeout di httpx vale per singola operazione, non per la richiesta
        data, model = _llm_pool.submit(_llm_request, messages, deadline).result(timeout=max(0.1, deadline - time.monotonic()))
        proposal = data.get("proposal")
        if isinstance(proposal, dict) and proposal.get("intent") in ACTION_INTENTS:
            summary = str(proposal.get("summary") or "").strip()
            proposal = normalize_command(proposal)
            proposal["summary"] = summary or describe_command(proposal)
        else:
            proposal = None
        return {"reply": str(data["reply"]).strip(), "proposal": proposal, "model": model}
    except FutureTimeout:
        print(f"[chat] Groq oltre {CHAT_TIMEOUT_S:.0f}s: risposta locale", flush=True)
    except Exception as e:
        print(f"[chat] Groq non disponibile ({type(e).__name__}: {str(e)[:140]}): risposta locale", flush=True)
    return None


def local_reply(ctx):
    """Risposta sintetica dai dati reali (senza LLM): stato del conto e cause concrete di un portafoglio fermo."""
    acc = ctx.get("account") or {}
    cfg = ctx.get("config") or {}
    st = snapshot_state()
    eq = acc.get("portfolio") or 0
    exp_pct = (acc.get("exposure") or 0) / eq * 100 if eq else 0
    positions = ctx.get("positions") or []
    text = (f"Patrimonio ${eq:,.2f} (oggi {acc.get('daily_pnl_usd', 0) or 0:+,.2f}$, {acc.get('daily_pnl_pct', 0) or 0:+.2f}%), "
            f"cassa ${acc.get('cash', 0) or 0:,.2f}, investito {exp_pct:.0f}%, {len(positions)} posizioni aperte")
    if positions:
        text += " (" + ", ".join(f"{p['symbol']} {p.get('unrealized_plpc', 0):+.2f}%" for p in positions[:5]) + ")"
    if ctx.get("vix") is not None:
        text += f", VIX {ctx['vix']}"
    text += "."
    why = []
    if ctx.get("bot_active") is False:
        why.append("il sistema è in pausa")
    if cfg and not cfg.get("auto_execute_trades"):
        why.append("è attiva la modalità Advisor (nessun ordine inviato)")
    if ctx.get("market_open") is False:
        why.append("il mercato azionario USA è chiuso (solo crypto operative)")
    if ctx.get("drawdown_blocked"):
        why.append("il Drawdown Controller blocca gli acquisti per la perdita giornaliera")
    if cfg.get("max_exposure_pct") and exp_pct >= float(cfg["max_exposure_pct"]) - 1:
        why.append(f"l'esposizione è al limite ({exp_pct:.0f}% su {float(cfg['max_exposure_pct']):.0f}%)")
    if ctx.get("vix") is not None and ctx["vix"] > core.VIX_RISK_CONTRACTION:
        why.append(f"VIX {ctx['vix']} sopra {core.VIX_RISK_CONTRACTION:.0f}: rischio contratto")
    paused = [AGENTS[a]["title"] for a, v in st["agents"].items() if v["paused"]]
    if paused:
        why.append("agenti in pausa: " + ", ".join(paused))
    blocks = blocks_text(st["blocks"])
    if blocks:
        why.append("acquisti bloccati su " + ", ".join(blocks))
    queue = (ctx.get("radar") or {}).get("queue") or []
    if not any(q.get("status") == "APPROVED_BY_RISK" for q in queue):
        why.append(f"nessuna scheda approvata con Ensemble ≥ {core.PIPELINE_BUY_SCORE:.0f}")
    rejected = ctx.get("rejected") or []
    if rejected:
        why.append("ultime bocciature: " + "; ".join(f"{r['symbol']} ({str(r.get('reason') or '')[:70]})" for r in rejected[:3]))
    if why:
        text += " Perché non si compra ora: " + "; ".join(why) + "."
    return text


def describe_command(cmd):
    """Descrizione leggibile di un'azione proposta."""
    agent = AGENTS.get(cmd.get("agent") or "", {}).get("title", "agente non specificato")
    label = _segment_label(cmd.get("kind"), cmd.get("value")) if cmd.get("value") else "segmento non specificato"
    level = SENSITIVITY_LABELS.get(cmd.get("level") if cmd.get("level") is not None else 1)
    return {"pause_agent": f"mettere in pausa {agent}", "resume_agent": f"riattivare {agent}",
            "set_sensitivity": f"impostare la sensibilità di {agent} su {level}",
            "block": f"bloccare i nuovi acquisti su {label}", "unblock": f"sbloccare i nuovi acquisti su {label}",
            "clear_blocks": "rimuovere tutti i blocchi sugli acquisti",
            "aggressiveness_up": "aumentare l'esposizione massima di 10 punti (fino al 50%)",
            "aggressiveness_down": "ridurre l'esposizione massima di 10 punti (fino al 10%)",
            "pause_bot": "mettere in pausa tutto il sistema", "resume_bot": "riattivare il sistema",
            "advisor_mode": "passare in modalità Advisor (nessun ordine inviato)",
            "auto_mode": "passare in modalità Auto-Trading (ordini eseguiti)"}.get(cmd["intent"], cmd["intent"])


def _apply(persona, cmd, ctx, apply_bot_state):
    """Esegue una proposta confermata dall'utente con i controlli del Centro di Comando."""
    try:
        verdict, text, change = _decide(cmd, ctx, persona, force=True)
    except ValueError as e:
        verdict, text, change = "IMPOSSIBILE", str(e), None
    if change and "bot_active" in change:
        apply_bot_state(change["bot_active"])
        text = ("Sistema riattivato: gli agenti riprendono il lavoro." if change["bot_active"] else
                "Sistema in pausa: nessuna nuova scansione né acquisto. Le posizioni aperte restano protette dagli stop.")
    return verdict, text, change


def chat(persona, message, ctx, apply_bot_state):
    """Messaggio al dirigente -> risposta. Le azioni vengono solo proposte e applicate dopo la conferma esplicita.

    apply_bot_state(active) mette in pausa/riattiva il bot.
    """
    persona = persona if persona in PERSONAS else "coo"
    message = (message or "").strip()[:800]
    _push("user", persona, message)
    pending = _pending.get(persona)
    if pending and time.time() - pending["ts"] > PROPOSAL_TTL_SEC:
        _pending.pop(persona, None)
        pending = None

    # Risposta a una proposta in sospeso: conferma -> esecuzione, annullamento -> nessuna modifica
    if pending and CONFIRM_RE.search(message) and len(message) <= 80:
        _pending.pop(persona, None)
        verdict, text, change = _apply(persona, pending["cmd"], ctx, apply_bot_state)
        return _push("agent", persona, text, verdict=verdict, intent=pending["cmd"]["intent"], parser="conferma",
                     change=change)
    if pending and CANCEL_RE.search(message) and len(message) <= 80:
        _pending.pop(persona, None)
        return _push("agent", persona, f"Va bene, nessuna modifica: ho annullato la proposta ({pending['summary']}).",
                     verdict="INFO", intent="cancel", parser="conferma", change=None)

    llm = _llm_chat(persona, message, ctx)
    if llm:
        proposal = llm["proposal"]
        reply = llm["reply"]
        if proposal:
            _pending[persona] = {"cmd": proposal, "summary": proposal["summary"], "ts": time.time()}
            # Conferma obbligatoria: la richiesta esplicita c'è sempre, anche se l'LLM l'ha omessa
            reply += f"\n\nProposta: {proposal['summary']}. Confermi? Rispondi \"sì\" per applicarla o \"no\" per annullare."
        return _push("agent", persona, reply, verdict="PROPOSTA" if proposal else "INFO",
                     intent=proposal["intent"] if proposal else "chat", parser=f"Groq · {llm['model']}", change=None,
                     proposal=proposal["summary"] if proposal else None)

    # Riserva senza LLM: comandi riconosciuti dalle regole, sempre con conferma
    cmd, source = parse_command(message)
    if cmd["intent"] in ACTION_INTENTS:
        summary = describe_command(cmd)
        _pending[persona] = {"cmd": cmd, "summary": summary, "ts": time.time()}
        text = (f"Assistente IA momentaneamente non disponibile: ho interpretato la richiesta come: {summary}. "
                "Vuoi che proceda? Rispondi \"sì\" per confermare o \"no\" per annullare.")
        return _push("agent", persona, text, verdict="PROPOSTA", intent=cmd["intent"], parser=source, change=None,
                     proposal=summary)
    text = "Risposta rapida dai dati di sistema (assistente IA momentaneamente non disponibile). " + local_reply(ctx)
    return _push("agent", persona, text, verdict="INFO", intent=cmd["intent"], parser="locale", change=None)


def fallback_reply(persona, ctx):
    """Risposta locale d'emergenza (errore inatteso nella chat): mai una richiesta lasciata senza risposta."""
    persona = persona if persona in PERSONAS else "coo"
    try:
        text = "Risposta rapida dai dati di sistema (assistente momentaneamente non disponibile). " + local_reply(ctx)
    except Exception:
        text = "Assistente momentaneamente non disponibile: riprova tra qualche secondo."
    return _push("agent", persona, text, verdict="INFO", intent="chat", parser="locale", change=None)


def pending_proposal(persona):
    p = _pending.get(persona)
    return p["summary"] if p and time.time() - p["ts"] <= PROPOSAL_TTL_SEC else None


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
