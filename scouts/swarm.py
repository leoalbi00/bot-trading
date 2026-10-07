"""Sciame di Scout asincroni divisi per categoria.

Lo sciame tiene `size` Scout persistenti (default 100) ripartiti tra le 6 categorie di
scouts.detectors. A ogni giro i ticker vengono assegnati a rotazione agli Scout di ciascuna
categoria: ogni ticker viene quindi esaminato da 6 Scout (uno per categoria) in parallelo.
Appena i 6 Scout di un ticker hanno finito, il payload arricchito con i loro segnali entra
nella asyncio.Queue degli agenti (stream continuo, non a fine giro).

Ogni scansione ha un timeout: uno Scout che lo supera viene segnato come bloccato e
riavviato (nuova istanza, stessa identità) e l'evento viene notificato al Watchdog CHOP.
"""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from scouts.detectors import CATEGORIES, DETECTORS

STREAM_END = None   # stessa sentinella di quant_core


class Scout:
    """Uno Scout: identità fissa, categoria e statistiche; `generation` cresce a ogni riavvio."""

    def __init__(self, scout_id: int, category: str, generation: int = 0):
        self.scout_id = scout_id
        self.category = category
        self.generation = generation
        self.detector = DETECTORS[category]
        self.runs = 0
        self.timeouts = 0
        self.last_heartbeat = time.time()
        self.last_ms = 0.0

    @property
    def label(self) -> str:
        return f"#{self.scout_id:03d} {self.category}"

    def scan(self, df, book) -> Dict[str, Any]:
        started = time.perf_counter()
        result = self.detector(df, book)
        self.last_ms = (time.perf_counter() - started) * 1000
        self.runs += 1
        self.last_heartbeat = time.time()
        return {**result, "category": self.category, "scout_id": self.scout_id, "elapsed_ms": round(self.last_ms, 3)}


class ScoutSwarm:
    def __init__(self, size: int = 100, timeout_s: float = 2.0, threads: int = 16, watchdog=None):
        self.size = size
        self.timeout_s = timeout_s
        self.watchdog = watchdog
        self.executor = ThreadPoolExecutor(max_workers=threads, thread_name_prefix="scout")
        self._lock = threading.Lock()
        self.scouts: List[Scout] = []
        for i in range(size):
            self.scouts.append(Scout(i + 1, CATEGORIES[i % len(CATEGORIES)]))
        self.restarts = 0
        self.active_last_cycle = 0
        self.used_since_audit: set = set()   # Scout al lavoro dall'ultimo audit del CHOP

    def by_category(self) -> Dict[str, List[Scout]]:
        groups: Dict[str, List[Scout]] = {c: [] for c in CATEGORIES}
        with self._lock:
            for s in self.scouts:
                groups[s.category].append(s)
        return groups

    def restart_scout(self, scout: Scout, reason: str) -> Scout:
        """Auto-healing: sostituisce lo Scout bloccato con una nuova istanza (stessa identità)."""
        fresh = Scout(scout.scout_id, scout.category, scout.generation + 1)
        fresh.timeouts = scout.timeouts
        with self._lock:
            self.scouts[scout.scout_id - 1] = fresh
            self.restarts += 1
        if self.watchdog:
            self.watchdog.record_heal(f"Scout {scout.label} riavviato (gen {fresh.generation}): {reason}")
        return fresh

    def stalled_scouts(self, max_silence_s: float) -> List[Scout]:
        """Scout che non danno segni di vita da troppo tempo pur essendo stati assegnati."""
        now = time.time()
        with self._lock:
            return [s for s in self.scouts if s.runs and now - s.last_heartbeat > max_silence_s]

    async def _run_scout(self, scout: Scout, symbol: str, df, book) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        try:
            res = await asyncio.wait_for(loop.run_in_executor(self.executor, scout.scan, df, book), self.timeout_s)
        except asyncio.TimeoutError:
            scout.timeouts += 1
            self.restart_scout(scout, f"timeout {self.timeout_s:.1f}s su {symbol}")
            return {"triggered": False, "side": "NONE", "strength": 0.0, "category": scout.category,
                    "scout_id": scout.scout_id, "detail": "timeout", "error": True}
        except Exception as e:
            return {"triggered": False, "side": "NONE", "strength": 0.0, "category": scout.category,
                    "scout_id": scout.scout_id, "detail": f"errore {type(e).__name__}: {e}", "error": True}
        if self.watchdog:
            self.watchdog.record_scout_run(scout.scout_id, res["elapsed_ms"])
        return res

    async def _scan_symbol(self, index: int, payload: Dict[str, Any], groups: Dict[str, List[Scout]],
                           queue: asyncio.Queue, used: set) -> None:
        df, book = payload["df_ohlcv"], payload.get("order_book")
        team = [scouts[index % len(scouts)] for scouts in groups.values() if scouts]
        used.update(s.scout_id for s in team)
        signals = await asyncio.gather(*(self._run_scout(s, payload["symbol"], df, book) for s in team))
        triggered = [s for s in signals if s["triggered"]]
        lead = max(triggered, key=lambda s: s["strength"]) if triggered else signals[0]
        payload["scout_signals"] = list(signals)
        payload["scout_id"] = f"{lead['scout_id']:03d} {lead['category']}" + (f" +{len(triggered) - 1}" if len(triggered) > 1 else "")
        await queue.put(payload)
        if self.watchdog:
            self.watchdog.record_queue(queue.qsize())

    async def stream(self, payloads: List[Dict[str, Any]], queue: asyncio.Queue) -> None:
        """Esegue gli Scout su tutti i ticker e inserisce ogni payload in coda appena pronto; chiude con STREAM_END."""
        groups = self.by_category()
        used: set = set()
        try:
            await asyncio.gather(*(self._scan_symbol(i, p, groups, queue, used) for i, p in enumerate(payloads)))
        finally:
            self.active_last_cycle = len(used)
            with self._lock:
                self.used_since_audit |= used
            await queue.put(STREAM_END)

    def take_used_since_audit(self) -> int:
        with self._lock:
            n, self.used_since_audit = len(self.used_since_audit), set()
        return n

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False)
