"""AGENTE #7: CHOP Watchdog (ispettore di sistema dello sciame).

Traccia:
- heartbeat di ogni modulo (Scout e Agenti #1-#6);
- latenza in millisecondi di ciascuno Stage della pipeline;
- occupazione della asyncio.Queue degli Scout;
- memoria (RSS) e CPU del processo.
Auto-healing:
- Scout in timeout o silenziosi -> riavvio (ScoutSwarm.restart_scout);
- coda oltre `backlog_limit` elementi -> più Worker per gli agenti (scale_workers).
Ogni `audit_interval` secondi produce la riga
`🐝 [CHOP SWARM AUDIT] N Scout Attivi | Backlog Code: X | Stage 1 Latency: Yms | RAM: ZMB`.
"""
import os
import resource
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

STAGES = ("stage1", "stage2", "stage3")


def _rss_mb() -> float:
    """Memoria residente attuale del processo (Linux /proc), altrimenti il picco da getrusage."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


class ChopWatchdog:
    def __init__(self, backlog_limit: int = 50, audit_interval: float = 30.0, scout_silence_s: float = 600.0,
                 module_silence_s: float = 900.0, max_workers: int = 16, scale_step: int = 2,
                 scale_cooldown_s: float = 5.0):
        self.agent_id = "AGENT_07_CHOP_WATCHDOG"
        self.backlog_limit = backlog_limit
        self.audit_interval = audit_interval
        self.scout_silence_s = scout_silence_s
        self.module_silence_s = module_silence_s
        self.max_workers = max_workers
        self.scale_step = scale_step
        self.scale_cooldown_s = scale_cooldown_s
        self._last_scale = 0.0
        self._lock = threading.Lock()
        self.heartbeats: Dict[str, float] = {}
        self.latencies: Dict[str, Deque[float]] = {s: deque(maxlen=200) for s in STAGES}
        self.scout_ms: Deque[float] = deque(maxlen=500)
        self.queue_now = 0
        self.queue_peak = 0
        self.heals: Deque[str] = deque(maxlen=50)
        self.stage_counts = {"received": 0, "stage1_pass": 0, "stage2_pass": 0, "stage3_done": 0}
        self._last_audit = 0.0
        self.universe: Dict[str, Any] = {}   # copertura dell'universo dinamico (impostata dallo sciame)
        self._cpu_mark = (time.process_time(), time.time())

    # ------------------------------------------------------------------ telemetria
    def heartbeat(self, module: str) -> None:
        with self._lock:
            self.heartbeats[module] = time.time()

    def record_latency(self, stage: str, ms: float) -> None:
        with self._lock:
            self.latencies[stage].append(ms)

    def record_scout_run(self, scout_id: int, ms: float) -> None:
        with self._lock:
            self.scout_ms.append(ms)
            self.heartbeats["Scout"] = time.time()

    def record_queue(self, size: int) -> None:
        with self._lock:
            self.queue_now = size
            self.queue_peak = max(self.queue_peak, size)

    def count(self, key: str) -> None:
        with self._lock:
            self.stage_counts[key] += 1

    def record_heal(self, action: str) -> None:
        with self._lock:
            self.heals.append(f"{time.strftime('%H:%M:%S')} {action}")

    # ------------------------------------------------------------------ auto-healing
    def needs_more_workers(self, backlog: int, current_workers: int) -> int:
        """Worker da aggiungere se la coda supera il limite (0 se non serve, al massimo o entro il cooldown).

        Il cooldown lascia ai nuovi Worker il tempo di smaltire la coda prima di aggiungerne altri.
        """
        if backlog <= self.backlog_limit or current_workers >= self.max_workers:
            return 0
        with self._lock:
            if time.time() - self._last_scale < self.scale_cooldown_s:
                return 0
            self._last_scale = time.time()
        return min(self.scale_step, self.max_workers - current_workers)

    def check_and_heal(self, engine=None, swarm=None) -> List[str]:
        """Controllo periodico: Scout silenziosi da riavviare e backlog residuo da smaltire."""
        actions = []
        if swarm is not None:
            for scout in swarm.stalled_scouts(self.scout_silence_s):
                swarm.restart_scout(scout, f"nessun heartbeat da {self.scout_silence_s:.0f}s")
                actions.append(f"riavviato Scout {scout.label}")
        if engine is not None:
            add = self.needs_more_workers(self.queue_now, engine.num_workers)
            if add:
                engine.scale_workers(add, reason=f"backlog {self.queue_now} > {self.backlog_limit}")
                actions.append(f"+{add} Worker")
        return actions

    # ------------------------------------------------------------------ report
    def _cpu_pct(self) -> float:
        cpu, wall = time.process_time(), time.time()
        prev_cpu, prev_wall = self._cpu_mark
        self._cpu_mark = (cpu, wall)
        return 100.0 * (cpu - prev_cpu) / (wall - prev_wall) if wall > prev_wall else 0.0

    @staticmethod
    def _avg(values) -> Optional[float]:
        values = list(values)
        return sum(values) / len(values) if values else None

    def snapshot(self, swarm=None, engine=None) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            lat = {s: self._avg(v) for s, v in self.latencies.items()}
            # Gli agenti degli Stage 2-3 lavorano solo sui ticker che superano lo Stage 1: in un mercato calmo
            # possono restare fermi a lungo senza essere bloccati. Il silenzio è un guasto solo per Scout e pipeline.
            stale = sorted(m for m, ts in self.heartbeats.items()
                           if m in ("Scout", "Pipeline") and now - ts > self.module_silence_s)
            agents_seen = {m: round(now - ts) for m, ts in self.heartbeats.items() if m.startswith("AGENTE")}
            snap = {
                "scouts_total": swarm.size if swarm else 0,
                "scouts_active": swarm.take_used_since_audit() if swarm else 0,
                "scout_restarts": swarm.restarts if swarm else 0,
                "scout_avg_ms": self._avg(self.scout_ms),
                "backlog": self.queue_now, "backlog_peak": self.queue_peak,
                "latency_ms": lat, "workers": engine.num_workers if engine else None,
                "stage_counts": dict(self.stage_counts), "stale_modules": stale, "agents_last_seen_s": agents_seen,
                "heals": list(self.heals)[-5:],
            }
            self.queue_peak = self.queue_now
        snap["ram_mb"] = round(_rss_mb(), 1)
        snap["cpu_pct"] = round(self._cpu_pct(), 1)
        return snap

    def audit_line(self, snap: Dict[str, Any]) -> str:
        fmt = lambda v: f"{v:.2f}ms" if v is not None else "N/D"
        lat, counts = snap["latency_ms"], snap["stage_counts"]
        noise = (1 - counts["stage1_pass"] / counts["received"]) * 100 if counts["received"] else 0.0
        line = (f"🐝 [CHOP SWARM AUDIT] {snap['scouts_total']} Scout Attivi | Backlog Code: {snap['backlog']} "
                f"(picco {snap['backlog_peak']}) | Stage 1 Latency: {fmt(lat['stage1'])} | RAM: {snap['ram_mb']:.0f}MB"
                f" | CPU {snap['cpu_pct']:.0f}% | Stage 2 {fmt(lat['stage2'])} · Stage 3 {fmt(lat['stage3'])}"
                f" | Scout al lavoro (ultimi {self.audit_interval:.0f}s) {snap['scouts_active']} · riavvii {snap['scout_restarts']}"
                f" | Worker {snap['workers']} | rumore filtrato {noise:.0f}% "
                f"({counts['stage1_pass']}/{counts['received']} passano lo Stage 1)")
        u = self.universe
        if u:
            line += (f" | 🌐 Universo {u['total']} ticker ({u['stocks']} USA · {u['crypto']} crypto) · "
                     f"blocco {u['chunk']}/{u['chunks']} · giri completi {u['cycles']}")
        if snap["stale_modules"]:
            line += f" | ⚠️ senza heartbeat: {', '.join(snap['stale_modules'])}"
        if snap["heals"]:
            line += f" | auto-healing: {snap['heals'][-1]}"
        return line

    def maybe_audit(self, log: Callable[[str], Any], swarm=None, engine=None, force: bool = False) -> Optional[str]:
        """Auto-healing + riga di audit, al massimo una volta ogni audit_interval secondi."""
        if not force and time.time() - self._last_audit < self.audit_interval:
            return None
        self._last_audit = time.time()
        self.check_and_heal(engine=engine, swarm=swarm)
        line = self.audit_line(self.snapshot(swarm=swarm, engine=engine))
        log(line)
        return line
