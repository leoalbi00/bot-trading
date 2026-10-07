"""Agents HR & Pitch Audit Register: ogni scheda valutata dalla pipeline e la pagella dei 7 Agenti.

Registro persistente (data/pitch_audit_log.json):
  - reviews: schede BOCCIATE / EXPIRED dallo Stage 1, Stage 2, Stage 3 (Agente #5), Comitato Rischi (#3) e CIO,
    con l'agente che ha messo il veto e la motivazione. Restano consultabili per 5 ore, poi vengono rimosse.
    Una riga per (ticker, stage): un ticker riscansionato aggiorna la sua riga (ora, motivo, contatore).
  - executed: schede APPROVATE ed ESEGUITE, salvate PERMANENTEMENTE con il breakdown dei voti dei 7 Agenti.
  - exits: vendite eseguite (motivo e PnL realizzato), permanenti: servono alla pagella dell'Agente #6.
  - veto_outcomes: esito dei veti dell'Agente #3 (salvavita / falso allarme), contatori permanenti.

Esito di un veto dell'Agente #3: dopo il veto si segue il prezzo del ticker (dalle scansioni successive).
Se tocca lo stop che avrebbe avuto il trade è un veto salvavita; se raggiunge il target (2R) è un falso allarme;
se nelle 5 ore non succede nessuna delle due cose il veto è neutro.
"""
import json
import os
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

RETENTION_SEC = 5 * 3600
FLUSH_EVERY_SEC = 15
TARGET_R = 2.0            # target = 2 volte la distanza dello stop (come il pacchetto del Comitato Rischi)
QUANT_BULLISH = 60.0      # Agente #1: segnale tecnico rialzista
MICRO_CONFIRMED = 50.0    # Agente #2: volumi / order flow a favore
GUARDIAN_EXITS = ("TRAILING STOP", "BREAKEVEN STOP", "ALPHA DECAY", "TIME STOP", "TAKE PROFIT", "SCALE OUT",
                  "NEWS SHOCK", "OFI REVERSAL")

AGENT_NAMES = {
    1: "Agente #1 · Quant", 2: "Agente #2 · Microstruttura", 3: "Agente #3 · Risk", 4: "Agente #4 · Macro/News",
    5: "Agente #5 · CIO", 6: "Agente #6 · Guardian", 7: "Agente #7 · CHOP",
}


def _key(symbol: str) -> str:
    return str(symbol).upper().replace("-", "").replace("/", "")


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _rate(wins: int, total: int) -> Optional[float]:
    return round(wins / total * 100, 1) if total else None


class PitchAuditRegister:
    def __init__(self, path: str, retention_sec: float = RETENTION_SEC, clock: Callable[[], str] = None):
        self.path = path
        self.retention_sec = retention_sec
        self.clock = clock or (lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.started = time.time()
        self._lock = threading.RLock()
        self._dirty = False
        self._last_flush = 0.0
        data = self._load()
        self.reviews: Dict[str, Dict[str, Any]] = {f"{_key(r['symbol'])}|{r['stage']}": r for r in data["reviews"]}
        self.executed: List[Dict[str, Any]] = data["executed"]
        self.exits: List[Dict[str, Any]] = data["exits"]
        self.veto_outcomes: Dict[str, Any] = data["veto_outcomes"]
        self.purge()

    # ------------------------------------------------------------------ persistenza
    def _load(self) -> Dict[str, Any]:
        default = {"reviews": [], "executed": [], "exits": [],
                   "veto_outcomes": {"lifesaver": 0, "false_alarm": 0, "neutral": 0, "avoided_pct": 0.0, "missed_pct": 0.0}}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return default
        if not isinstance(data, dict):
            return default
        for k, v in default.items():
            if not isinstance(data.get(k), type(v)):
                data[k] = v
        data["veto_outcomes"] = {**default["veto_outcomes"], **data["veto_outcomes"]}
        return data

    def flush(self, force: bool = False) -> None:
        """Scrittura atomica su disco, al massimo ogni FLUSH_EVERY_SEC (subito con force o per le eseguite)."""
        with self._lock:
            if not self._dirty or (not force and time.time() - self._last_flush < FLUSH_EVERY_SEC):
                return
            data = {"reviews": list(self.reviews.values()), "executed": self.executed, "exits": self.exits,
                    "veto_outcomes": self.veto_outcomes}
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, default=str)
                os.replace(tmp, self.path)
                self._dirty, self._last_flush = False, time.time()
            except OSError as e:
                print(f"[!] Registro audit agenti non salvato: {e}", flush=True)

    # ------------------------------------------------------------------ registrazione
    def record_review(self, symbol: str, stage: str, status: str, reason: str, veto_agent: str, agent_no: Optional[int],
                      score=None, price=None, stop_pct=None, agents: Optional[Dict[str, Any]] = None,
                      details: Optional[Dict[str, Any]] = None) -> None:
        """Scheda bocciata o scaduta (retention 5h): una riga per (ticker, stage), aggiornata a ogni nuova bocciatura."""
        k = f"{_key(symbol)}|{stage}"
        now = time.time()
        with self._lock:
            prev = self.reviews.get(k)
            entry = {"symbol": symbol, "stage": stage, "status": status, "reason": reason, "veto_agent": veto_agent,
                     "agent_no": agent_no, "score": score, "price": _num(price), "stop_pct": _num(stop_pct),
                     "ts": now, "time": self.clock(), "count": (prev or {}).get("count", 0) + 1,
                     "first_ts": (prev or {}).get("first_ts", now)}
            if agents:
                entry["agents"] = agents
            if details:
                entry["details"] = details
            # Un veto dell'Agente #3 già classificato resta nei contatori; il nuovo veto riparte da zero
            self.reviews[k] = entry
            self._dirty = True

    def record_executed(self, symbol: str, details: Dict[str, Any]) -> None:
        """Scheda approvata ed eseguita: storico permanente con i voti dei 7 Agenti."""
        with self._lock:
            self.executed.append({"symbol": symbol, "ts": time.time(), "time": self.clock(), **details})
            for k in [k for k in self.reviews if k.startswith(_key(symbol) + "|")]:
                self.reviews.pop(k)     # comprata: le bocciature precedenti non sono più attuali
            self._dirty = True
        self.flush(force=True)

    def record_exit(self, symbol: str, operation: str, reason: str, realized_pnl=None, price=None) -> None:
        with self._lock:
            self.exits.append({"symbol": symbol, "operation": operation, "reason": reason or "",
                               "realized_pnl": _num(realized_pnl), "price": _num(price), "ts": time.time(),
                               "time": self.clock()})
            self._dirty = True
        self.flush(force=True)

    # ------------------------------------------------------------------ manutenzione
    def resolve_vetoes(self, prices: Dict[str, float]) -> int:
        """Classifica i veti dell'Agente #3 con i prezzi delle ultime scansioni ({ticker: prezzo})."""
        by_key = {_key(s): _num(p) for s, p in prices.items()}
        resolved = 0
        with self._lock:
            for r in self.reviews.values():
                if r.get("agent_no") != 3 or r.get("outcome") or not r.get("price") or not r.get("stop_pct"):
                    continue
                now_price = by_key.get(_key(r["symbol"]))
                if not now_price:
                    continue
                move = (now_price / r["price"] - 1) * 100
                stop = -abs(r["stop_pct"])
                if move <= stop:
                    r["outcome"], r["outcome_move_pct"] = "lifesaver", round(move, 2)
                    self.veto_outcomes["lifesaver"] += 1
                    self.veto_outcomes["avoided_pct"] = round(self.veto_outcomes["avoided_pct"] - move, 2)
                elif move >= TARGET_R * abs(stop):
                    r["outcome"], r["outcome_move_pct"] = "false_alarm", round(move, 2)
                    self.veto_outcomes["false_alarm"] += 1
                    self.veto_outcomes["missed_pct"] = round(self.veto_outcomes["missed_pct"] + move, 2)
                else:
                    continue
                resolved += 1
                self._dirty = True
        return resolved

    def purge(self) -> int:
        """Rimuove le bocciate più vecchie di 5 ore (i veti #3 mai risolti contano come neutri)."""
        cutoff = time.time() - self.retention_sec
        with self._lock:
            old = [k for k, r in self.reviews.items() if r["ts"] < cutoff]
            for k in old:
                r = self.reviews.pop(k)
                if r.get("agent_no") == 3 and not r.get("outcome") and r.get("price") and r.get("stop_pct"):
                    self.veto_outcomes["neutral"] += 1
            if old:
                self._dirty = True
        return len(old)

    # ------------------------------------------------------------------ letture
    def rejected(self, limit: int = 300, stage: Optional[str] = None) -> Dict[str, Any]:
        self.purge()
        with self._lock:
            rows = [r for r in self.reviews.values() if not stage or r["stage"] == stage]
            by_stage: Dict[str, int] = {}
            for r in self.reviews.values():
                by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
        rows.sort(key=lambda r: r["ts"], reverse=True)
        return {"rows": [dict(r) for r in rows[:limit]], "total": len(rows), "by_stage": by_stage,
                "retention_hours": self.retention_sec / 3600}

    def executed_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in reversed(self.executed[-limit:])]

    def entry_votes(self, symbol: str, before_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Voti dei 7 Agenti sull'ultimo acquisto eseguito del ticker (prima di before_ts)."""
        k = _key(symbol)
        with self._lock:
            for e in reversed(self.executed):
                if _key(e["symbol"]) == k and (before_ts is None or e["ts"] <= before_ts + 60):
                    return e
        return None

    # ------------------------------------------------------------------ pagella
    def scorecard(self, trades: Iterable[Dict[str, Any]], chop: Optional[Dict[str, Any]] = None,
                  fallback_votes: Callable[[str, float], Optional[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Pagella dei 7 Agenti dai trade chiusi (trade_history), dallo storico eseguite e dalle uscite."""
        closed = []
        for t in trades or []:
            if not isinstance(t, dict) or t.get("pnl") is None:
                continue
            try:
                closed_ts = time.mktime(time.strptime(str(t.get("closed_at", ""))[:19], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                closed_ts = time.time()
            opened_ts = closed_ts - float(t.get("held_min") or 0) * 60
            entry = self.entry_votes(t["symbol"], opened_ts)
            agents = (entry or {}).get("agents") or (fallback_votes(t["symbol"], opened_ts) if fallback_votes else None)
            closed.append({"pnl": float(t["pnl"]), "pnl_pct": _num(t.get("pnl_pct")), "agents": agents or {}})

        def bucket(rows):
            wins = sum(1 for r in rows if r["pnl"] > 0)
            return {"trades": len(rows), "wins": wins, "win_rate": _rate(wins, len(rows)),
                    "pnl": round(sum(r["pnl"] for r in rows), 2)}

        voted = [r for r in closed if r["agents"]]
        score = lambda r, a: _num((r["agents"].get(a) or {}).get("score"))
        quant_bull = [r for r in voted if (score(r, "agent_01_quant") or 0) >= QUANT_BULLISH]
        micro_ok = [r for r in voted if (score(r, "agent_02_micro") or 0) >= MICRO_CONFIRMED]
        sent = lambda r: _num((r["agents"].get("agent_04_macro") or {}).get("news_sentiment"))
        news_pos = [r for r in voted if (sent(r) or 0) > 0]
        news_other = [r for r in voted if (sent(r) or 0) <= 0]
        avg = lambda rows: round(sum(r["pnl"] for r in rows) / len(rows), 2) if rows else None

        with self._lock:
            reviews = list(self.reviews.values())
            exits = list(self.exits)
            vo = dict(self.veto_outcomes)
        guardian = [x for x in exits if str(x.get("reason", "")).upper().startswith(GUARDIAN_EXITS)
                    or str(x.get("operation", "")).upper() == "TAKE PROFIT"]
        g_pnl = [x["realized_pnl"] for x in guardian if x.get("realized_pnl") is not None]
        stage_rej = lambda s: sum(1 for r in reviews if r["stage"] == s)
        decided = vo["lifesaver"] + vo["false_alarm"]
        all_b, q_b, m_b, n_b = bucket(closed), bucket(quant_bull), bucket(micro_ok), bucket(news_pos)
        chop = chop or {}
        lat = chop.get("latency_ms") or {}
        uptime_s = int(chop.get("uptime_s") or time.time() - self.started)

        board = [
            {"no": 1, "name": AGENT_NAMES[1], "win_rate": q_b["win_rate"], "pnl": q_b["pnl"], "samples": q_b["trades"],
             "metric": f"Precisione tecnica {q_b['win_rate'] if q_b['win_rate'] is not None else '—'}% sui trade con score ≥ {QUANT_BULLISH:.0f}",
             "detail": f"{q_b['wins']}/{q_b['trades']} vincenti · {stage_rej('Stage 1')} scartati dal Fast-Quant (5h)"},
            {"no": 2, "name": AGENT_NAMES[2], "win_rate": m_b["win_rate"], "pnl": m_b["pnl"], "samples": m_b["trades"],
             "metric": f"Successo filtri volume/order flow {m_b['win_rate'] if m_b['win_rate'] is not None else '—'}%",
             "detail": f"{m_b['wins']}/{m_b['trades']} vincenti con flusso confermato (score ≥ {MICRO_CONFIRMED:.0f}) · "
                       f"{stage_rej('Stage 2')} scartati dal Deep Filter (5h)"},
            {"no": 3, "name": AGENT_NAMES[3], "win_rate": _rate(vo["lifesaver"], decided), "pnl": None, "samples": decided,
             "metric": f"{vo['lifesaver']} veti salvavita vs {vo['false_alarm']} falsi allarmi ({vo['neutral']} neutri)",
             "detail": f"perdita evitata {vo['avoided_pct']:.1f}% cumulata · rialzo mancato {vo['missed_pct']:.1f}% · "
                       f"{sum(1 for r in reviews if r.get('agent_no') == 3)} veti nelle ultime 5h"},
            {"no": 4, "name": AGENT_NAMES[4], "win_rate": n_b["win_rate"], "pnl": n_b["pnl"], "samples": n_b["trades"],
             "metric": f"PnL medio con notizie positive {avg(news_pos) if news_pos else '—'} vs neutre/negative "
                       f"{avg(news_other) if news_other else '—'}",
             "detail": f"{n_b['trades']} trade con sentiment > 0 · {len(news_other)} senza"},
            {"no": 5, "name": AGENT_NAMES[5], "win_rate": all_b["win_rate"], "pnl": all_b["pnl"], "samples": all_b["trades"],
             "metric": f"Win rate {all_b['win_rate'] if all_b['win_rate'] is not None else '—'}% · PnL netto {all_b['pnl']:+,.2f}$",
             "detail": f"{all_b['wins']}/{all_b['trades']} trade chiusi in utile · {len(self.executed)} BUY eseguiti registrati"},
            {"no": 6, "name": AGENT_NAMES[6], "win_rate": _rate(sum(1 for p in g_pnl if p > 0), len(g_pnl)),
             "pnl": round(sum(g_pnl), 2) if g_pnl else 0.0, "samples": len(guardian),
             "metric": f"Guadagno medio recuperato {round(sum(g_pnl) / len(g_pnl), 2) if g_pnl else '—'}$ per uscita",
             "detail": f"{len(guardian)} uscite da Trailing / Breakeven / Scaling Out / Early Exit / Alpha Decay"},
            {"no": 7, "name": AGENT_NAMES[7], "win_rate": None, "pnl": None, "samples": None,
             "metric": f"Uptime {uptime_s // 3600}h {uptime_s % 3600 // 60:02d}m · riavvii Scout {chop.get('restarts', 0)} · "
                       f"auto-healing {chop.get('heals', 0)}",
             "detail": "latenza media " + " · ".join(f"{s.replace('stage', 'Stage ')} {v:.1f}ms" for s, v in lat.items() if v is not None)
                       + (f" · moduli senza heartbeat: {', '.join(chop['stale'])}" if chop.get("stale") else "")},
        ]
        # Classifica: prima per contributo al PnL, poi per win rate (il CHOP, senza PnL, in fondo)
        board.sort(key=lambda a: (a["pnl"] is None, -(a["pnl"] or 0), -(a["win_rate"] or 0)))
        for i, a in enumerate(board, 1):
            a["rank"] = i
        return {"agents": board, "closed_trades": len(closed), "voted_trades": len(voted)}
