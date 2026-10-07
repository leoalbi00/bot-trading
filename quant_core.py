"""Orchestratore quantitativo: sciame di 100 Scout, pipeline a 3 Stage e 7 Agenti.

Flusso (trading_core.stream_scouts_to_agents):
    payload standard per ticker (build_scout_payload)
      -> ScoutSwarm: 100 Scout in 6 categorie esaminano ogni ticker in parallelo
      -> asyncio.Queue
      -> process_scout_stream(): Worker che portano ogni candidato attraverso gli Stage
           STAGE 1 Fast-Quant (< 5 ms): Hurst, Z-Score, Volatility Spike + segnali degli Scout;
                   scarta il rumore (ticker senza Scout attivati o con prezzo casuale)
           STAGE 2 Deep Filter: Agente #1 completo (GARCH), Agente #2 (VPIN, OFI),
                   notizie e calendario via Agente #4; scarta chi non può più arrivare a BUY
           STAGE 3 Executive & Risk Desk: Agente #3 (rischio), #6 (Portfolio Guardian), #5 (CIO)
      -> piano dell'Agente #5 (aperture / Asset Swap)
L'Agente #7 (CHOP Watchdog) misura latenze, coda, RAM/CPU e fa auto-healing.
Ogni passaggio viene registrato su console (a colori) e su file (quant_agents.log).
"""
import asyncio
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from agents.agent_01_quant import QuantEngineAgent
from agents.agent_02_micro import MicrostructureAgent
from agents.agent_03_risk import RiskManagerAgent
from agents.agent_04_macro import MacroSentimentAgent
from agents.agent_05_cio import CIOStrategistAgent
from agents.agent_06_sentinel import PortfolioGuardianAgent
from agents.agent_07_chop import ChopWatchdog
from scouts.swarm import ScoutSwarm

QUANT_LOG_PATH = os.path.join(os.getenv("BOT_DATA_DIR", os.path.dirname(os.path.abspath(__file__))), "quant_agents.log")
DEFAULT_ACCOUNT_BALANCE = 10000.0
STREAM_END = None   # sentinella: fine del pacchetto inviato dagli Scout sulla coda
SWARM_SIZE = 100
RVOL_STAGE1_BYPASS = 2.5        # volume relativo eccezionale: passa lo Stage 1...
STAGE1_BYPASS_MIN_SCORE = 35    # ...se lo score tecnico dello Scout è almeno intermedio


class _ColorFormatter(logging.Formatter):
    """Colori ANSI per la console (disattivabili con NO_COLOR): ogni Stage ha il suo colore."""
    RESET = "\033[0m"
    RULES = (
        ("VETO", "\033[1;31m"), ("[CHOP", "\033[1;33m"), ("Decisione: BUY", "\033[1;32m"),
        ("Decisione: SELL", "\033[1;31m"), ("[STAGE 1", "\033[36m"), ("[STAGE 2", "\033[34m"),
        ("[STAGE 3", "\033[35m"), ("[AGENTE #5", "\033[1;35m"), ("[AGENTE #6", "\033[35m"),
        ("[AGENTE #3", "\033[35m"), ("[AGENTE", "\033[94m"), ("[SCOUT STREAM]", "\033[90m"),
        ("🟢", "\033[32m"), ("🔄", "\033[33m"),
    )

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if record.levelno >= logging.WARNING:
            return f"\033[33m{text}{self.RESET}"
        for marker, color in self.RULES:
            if marker in record.getMessage():
                return f"{color}{text}{self.RESET}"
        return text


def _build_logger() -> logging.Logger:
    """Logger dedicato agli agenti: console + file a rotazione, senza toccare il root logger dell'app."""
    log = logging.getLogger("quant_core")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    console = logging.StreamHandler()
    use_color = not os.getenv("NO_COLOR") and (sys.stderr.isatty() or os.getenv("FORCE_COLOR") or os.getenv("RENDER"))
    console.setFormatter(_ColorFormatter(fmt) if use_color else logging.Formatter(fmt))
    log.addHandler(console)
    try:
        os.makedirs(os.path.dirname(QUANT_LOG_PATH), exist_ok=True)
        file_handler = RotatingFileHandler(QUANT_LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(fmt))
        log.addHandler(file_handler)
    except OSError as e:
        log.warning(f"Log su file non disponibile ({QUANT_LOG_PATH}): {e}")
    return log


logger = _build_logger()


def symbol_key(symbol: str) -> str:
    """Chiave di confronto unica (BTC-USD, BTC/USD e BTCUSD -> BTCUSD), come trading_core.normalize_symbol."""
    return str(symbol).upper().replace("-", "").replace("/", "")


def normalize_ohlcv(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """DataFrame con colonne minuscole open/high/low/close/volume (yfinance usa 'Close', 'Volume', ...)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    out = out[[c for c in ("open", "high", "low", "close", "volume") if c in out.columns]]
    return out.apply(pd.to_numeric, errors="coerce").dropna(subset=[c for c in ("close",) if c in out.columns])


def build_scout_payload(
    symbol: str,
    df_ohlcv: Optional[pd.DataFrame],
    order_book: Optional[Dict[str, Any]] = None,
    macro_inputs: Optional[Dict[str, Any]] = None,
    account_balance: Optional[float] = None,
    scout_id: Optional[Union[int, str]] = None,
    force_full: bool = False,
    scout_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Payload standard di un candidato.

    {"symbol": str, "df_ohlcv": DataFrame, "order_book": dict, "macro_inputs": dict,
     "account_balance": float} + "scout_id" per i log e "force_full" per saltare i filtri
    degli Stage 1-2 (posizioni aperte e schede già proposte: vanno sempre valutate).
    """
    try:
        balance = float(account_balance) if account_balance is not None else DEFAULT_ACCOUNT_BALANCE
    except (TypeError, ValueError):
        balance = DEFAULT_ACCOUNT_BALANCE
    return {
        "symbol": str(symbol),
        "df_ohlcv": normalize_ohlcv(df_ohlcv),
        "order_book": dict(order_book or {}),
        "macro_inputs": dict(macro_inputs or {}),
        "account_balance": balance,
        "scout_id": scout_id if scout_id is not None else "?",
        "force_full": bool(force_full),
        # Esito dello Scout classico (score tecnico 0-100 e RVOL): abilita il bypass RVOL dello Stage 1
        "scout_meta": dict(scout_meta or {}),
    }


def conviction_strength(cio_res: Dict[str, Any]) -> float:
    """
    Forza del segnale indipendente dalla direzione, sulla stessa scala 0-100
    dello score CIO: un BUY a 80 e un SELL a 20 valgono entrambi 80.
    Senza questa normalizzazione un SELL forte (score basso) risulterebbe
    sempre la posizione "più debole" e non potrebbe mai vincere uno swap.
    """
    score = cio_res.get("cio_ensemble_score", 50.0)
    return 100.0 - score if cio_res.get("final_decision") == "SELL" else score


def _fmt(value: Any, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


class QuantitativeTradingCore:
    """
    MOTORE PRINCIPALE DI TRADING QUANTITATIVO (Core Orchestrator)
    Sciame di Scout, pipeline a 3 Stage con 7 Agenti, Capital Recycling (Asset Swap) e CHOP Watchdog.
    """
    def __init__(
        self,
        portfolio_max_slots: int = 3,
        num_workers: int = 4,
        swap_delta_threshold: float = 20.0,
        swarm_size: int = SWARM_SIZE,
        news_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
        watchdog: Optional[ChopWatchdog] = None,
    ):
        self.portfolio_max_slots = portfolio_max_slots
        self.num_workers = num_workers
        self.base_workers = num_workers
        self.swap_delta_threshold = swap_delta_threshold
        self.news_provider = news_provider

        # Squadra di Agenti (stateless: condivisibili tra i worker)
        self.agent_quant = QuantEngineAgent()
        self.agent_micro = MicrostructureAgent()
        self.agent_risk = RiskManagerAgent()
        self.agent_macro = MacroSentimentAgent()
        self.agent_cio = CIOStrategistAgent()
        self.agent_guardian = PortfolioGuardianAgent()
        self.watchdog = watchdog or ChopWatchdog()
        self.swarm = ScoutSwarm(size=swarm_size, watchdog=self.watchdog)

        # Worker Pool reale: gli agenti sono codice sincrono pandas/numpy, quindi
        # vanno eseguiti fuori dall'event loop per non bloccarlo.
        self.executor = ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="quant-worker")

        # Stato del portafoglio per l'Agente #6 e per gli slot dell'Agente #5 (chiavi normalizzate)
        self.portfolio_context: Dict[str, Any] = {}
        self.active_portfolio: Dict[str, Dict[str, Any]] = {}
        # Ultima valutazione completa (Stage 3) e ultimo esito di Stage 1-2 per simbolo
        self.latest_evaluations: Dict[str, Dict[str, Any]] = {}
        self.stage_filtered: Dict[str, Dict[str, Any]] = {}
        self._eval_lock = threading.Lock()

    # ------------------------------------------------------------------ auto-healing
    def scale_workers(self, add: int, reason: str = "") -> None:
        """Più Worker per gli agenti: nuovo pool più grande (quello vecchio finisce i compiti in corso)."""
        old = self.executor
        self.num_workers += add
        self.executor = ThreadPoolExecutor(max_workers=self.num_workers, thread_name_prefix="quant-worker")
        old.shutdown(wait=False)
        self.watchdog.record_heal(f"Worker {self.num_workers - add} → {self.num_workers} ({reason})")
        logger.warning(f"🐝 [CHOP AUTO-HEALING] Worker aumentati a {self.num_workers}: {reason}")

    # ------------------------------------------------------------------ agenti
    def _run_agent(self, label: str, symbol: str, fn, fallback: Dict[str, Any]) -> Dict[str, Any]:
        """Esegue un agente: un'eccezione non viene silenziata ma registrata come Warning con la causa."""
        self.watchdog.heartbeat(label.split(" ")[0] + " " + label.split(" ")[1])
        try:
            res = fn()
        except Exception as e:
            logger.warning(f"[{label}] ⚠️ {symbol} -> eccezione {type(e).__name__}: {e}")
            return {**fallback, "status": "AGENT_ERROR", "reason": f"{label} {type(e).__name__}: {e}"}
        if res.get("status") == "INSUFFICIENT_DATA":
            logger.warning(f"[{label}] ⚠️ {symbol} scartato -> dati insufficienti: {res.get('reason', 'N/D')}")
        return res

    def _best_case_score(self, quant: float, micro: float, macro: float) -> float:
        """Ensemble massimo raggiungibile con Agente #3 a 100: se è sotto la soglia BUY lo Stage 3 è inutile."""
        return max(self.agent_cio.ensemble_score(quant, micro, 100.0, macro, high) for high in (False, True))

    def _filtered(self, symbol: str, stage: int, reason: str, extra: Dict[str, Any]) -> None:
        with self._eval_lock:
            self.stage_filtered[symbol_key(symbol)] = {"stage": stage, "reason": reason, "at": time.time(), **extra}

    def _run_agent_pipeline(self, worker_id: int, candidate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Pipeline sincrona a 3 Stage su un singolo candidato (eseguita in un thread del pool)."""
        symbol = candidate_data.get("symbol")
        df_ohlcv = candidate_data.get("df_ohlcv")
        order_book = candidate_data.get("order_book") or {}
        macro_inputs = candidate_data.get("macro_inputs") or {}
        account_balance = candidate_data.get("account_balance", DEFAULT_ACCOUNT_BALANCE)
        signals = candidate_data.get("scout_signals") or []
        force = bool(candidate_data.get("force_full"))
        self.watchdog.heartbeat("Pipeline")

        if not symbol or not isinstance(df_ohlcv, pd.DataFrame):
            logger.warning(f"[Worker {worker_id}] ⚠️ Payload scartato: simbolo mancante o df_ohlcv non è un DataFrame "
                           f"(symbol={symbol!r}, df_ohlcv={type(df_ohlcv).__name__})")
            return None
        if len(df_ohlcv) < 30 or "close" not in df_ohlcv.columns:
            logger.warning(f"[STAGE 1 · FAST-QUANT] ⚠️ {symbol} scartato -> dati insufficienti ({len(df_ohlcv)} barre)")
            return None

        # ============================== STAGE 1: Fast-Quant ==============================
        t1 = time.perf_counter()
        fast = self.agent_quant.fast_screen(df_ohlcv["close"])
        triggered = [s for s in signals if s.get("triggered")]
        # Il bot apre solo posizioni long: i segnali ribassisti contano solo per le posizioni aperte (forzate)
        bullish = [s for s in triggered if s.get("side") == "LONG"]
        meta = candidate_data.get("scout_meta") or {}
        rvol, scout_score = meta.get("rvol"), meta.get("score")
        rvol_bypass = (rvol is not None and rvol > RVOL_STAGE1_BYPASS and scout_score is not None
                       and scout_score >= STAGE1_BYPASS_MIN_SCORE)
        passed = force or rvol_bypass or (fast["interesting"] and bool(bullish))
        ms1 = (time.perf_counter() - t1) * 1000
        self.watchdog.record_latency("stage1", ms1)
        self.watchdog.count("received")
        scout_txt = ", ".join(f"{s['category']}{'↑' if s['side'] == 'LONG' else '↓'}" for s in triggered) or "nessuno"
        natural = fast["interesting"] and bool(bullish)
        verdict = "PASSA → Stage 2" + (" (forzato: posizione/scheda)" if force and not natural
                                       else f" (RVOL {rvol}x > {RVOL_STAGE1_BYPASS}x, score {scout_score})"
                                       if rvol_bypass and not natural else "") \
            if passed else ("FILTRATO (rumore: nessuno Scout attivato)" if not triggered
                            else "FILTRATO (solo segnali ribassisti: il bot non va short)" if not bullish
                            else "FILTRATO (rumore: prezzo statisticamente casuale)") \
            + (f" [RVOL {rvol}x ma score {scout_score} < {STAGE1_BYPASS_MIN_SCORE}]"
               if not passed and rvol is not None and rvol > RVOL_STAGE1_BYPASS else "")
        logger.info(f"[STAGE 1 · FAST-QUANT] ⚡ {symbol} -> Hurst: {fast['hurst']:.3f}, Z-Score: {fast['z_score']:+.2f}, "
                    f"Vol Spike: {fast['vol_spike']:.1f}σ | Scout attivati: {scout_txt} -> {verdict} ({ms1:.2f}ms)")
        if not passed:
            self._filtered(symbol, 1, verdict, {"fast": fast, "scouts": scout_txt})
            return None
        self.watchdog.count("stage1_pass")

        # ============================== STAGE 2: Deep Filter ==============================
        t2 = time.perf_counter()
        res_quant = self._run_agent("AGENTE #1 QUANT", symbol, lambda: self.agent_quant.analyze(df_ohlcv),
                                    {"agent_id": self.agent_quant.agent_id, "quant_score": 50.0, "trade_signal": "NEUTRAL"})
        qm = res_quant.get("metrics", {})
        garch = f"{qm['garch_vol_pct']:.4f}%" if "garch_vol_pct" in qm else "N/D"
        logger.info(f"[AGENTE #1 QUANT] 📊 {symbol} -> Hurst: {_fmt(qm.get('hurst_exponent', 'N/D'))}, "
                    f"GARCH Vol: {garch}, Z-Score: {_fmt(qm.get('z_score', 'N/D'))} -> Score: {_fmt(res_quant.get('quant_score'), 2)}")

        res_micro = self._run_agent("AGENTE #2 MICRO", symbol, lambda: self.agent_micro.analyze(df_ohlcv, order_book=order_book),
                                    {"agent_id": self.agent_micro.agent_id, "microstructure_score": 50.0, "trade_signal": "NEUTRAL"})
        mm = res_micro.get("metrics", {})
        logger.info(f"[AGENTE #2 MICRO] 💧 {symbol} -> VPIN: {_fmt(mm.get('vpin_toxicity', 'N/D'))}, "
                    f"OFI: {_fmt(mm.get('order_flow_imbalance', 'N/D'))} ({mm.get('ofi_source', 'N/D')}) "
                    f"-> Score: {_fmt(res_micro.get('microstructure_score'), 2)}")

        news = {"sentiment": macro_inputs.get("news_sentiment", 0.0), "headlines": 0, "events": [], "source": "nessuna"}
        if self.news_provider:
            try:
                news = {**news, **(self.news_provider(symbol) or {})}
            except Exception as e:
                logger.warning(f"[AGENTE #4 MACRO] ⚠️ {symbol} -> ricerca notizie fallita {type(e).__name__}: {e}")
        events = list(macro_inputs.get("upcoming_events", [])) + list(news.get("events") or [])
        res_macro = self._run_agent("AGENTE #4 MACRO", symbol, lambda: self.agent_macro.analyze(
            df=df_ohlcv,
            vix_level=macro_inputs.get("vix_level", 16.5),
            fear_greed_index=macro_inputs.get("fear_greed_index", 50.0),
            news_sentiment=news.get("sentiment", 0.0),
            central_bank_speech=macro_inputs.get("central_bank_speech", ""),
            upcoming_events=events
        ), {"agent_id": self.agent_macro.agent_id, "macro_approved": False, "macro_score": 0.0, "stress_level": "UNKNOWN"})
        logger.info(f"[AGENTE #4 MACRO] 🌐 {symbol} -> Macro Stress: {res_macro.get('stress_level', 'N/D')}, "
                    f"Macro Approved: {res_macro.get('macro_approved')} | notizie {news.get('headlines', 0)} "
                    f"(sentiment {float(news.get('sentiment') or 0):+.2f}, {news.get('source')}), eventi {len(events)}"
                    + (f" ({res_macro['reason']})" if res_macro.get("reason") else ""))
        if not res_macro.get("macro_approved"):
            logger.warning(f"[AGENTE #4 MACRO] ⚠️ {symbol} respinto dall'Agente Macro: {res_macro.get('reason', 'N/D')}")

        ms2 = (time.perf_counter() - t2) * 1000
        self.watchdog.record_latency("stage2", ms2)
        best = self._best_case_score(res_quant.get("quant_score", 50.0), res_micro.get("microstructure_score", 50.0),
                                     res_macro.get("macro_score", 50.0))
        deep_ok = force or best >= self.agent_cio.buy_threshold or best <= self.agent_cio.sell_threshold
        logger.info(f"[STAGE 2 · DEEP FILTER] 🔎 {symbol} -> ensemble massimo raggiungibile {best:.1f} "
                    f"(soglia BUY {self.agent_cio.buy_threshold:.0f}) -> "
                    f"{'PASSA → Stage 3' if deep_ok else 'FILTRATO (non può arrivare a BUY)'} ({ms2:.1f}ms)")
        if not deep_ok:
            self._filtered(symbol, 2, f"ensemble massimo {best:.1f} < {self.agent_cio.buy_threshold:.0f}",
                           {"fast": fast, "scouts": scout_txt})
            return None
        self.watchdog.count("stage2_pass")

        # ============================== STAGE 3: Executive & Risk Desk ==============================
        t3 = time.perf_counter()
        res_risk = self._run_agent("AGENTE #3 RISK", symbol,
                                   lambda: self.agent_risk.analyze(df_ohlcv, account_balance=account_balance),
                                   {"agent_id": self.agent_risk.agent_id, "risk_approved": False, "risk_score": 0.0})
        stop = res_risk.get("position_parameters", {}).get("stop_loss_price", "N/D")
        logger.info(f"[AGENTE #3 RISK] 🛡️ {symbol} -> ATR Stop: {_fmt(stop)}, "
                    f"Risk Approved: {res_risk.get('risk_approved')} ({res_risk.get('reason', 'N/D')})")
        if not res_risk.get("risk_approved"):
            logger.warning(f"🛡️ [RISK VETO] {symbol} bocciato per: {res_risk.get('reason', 'N/D')}")

        # Le posizioni già aperte non vanno giudicate come nuovi ingressi dal Guardian
        res_guard = None
        if symbol_key(symbol) not in set(self.portfolio_context.get("held") or ()):
            res_guard = self._run_agent("AGENTE #6 GUARDIAN", symbol,
                                        lambda: self.agent_guardian.pre_trade_check(symbol_key(symbol), self.portfolio_context),
                                        {"agent_id": self.agent_guardian.agent_id, "guardian_approved": False})
            logger.info(f"[AGENTE #6 GUARDIAN] 🧿 {symbol} -> Portfolio Approved: {res_guard.get('guardian_approved')} "
                        f"({res_guard.get('reason', 'N/D')})")

        try:
            self.watchdog.heartbeat("AGENTE #5")
            res_cio = self.agent_cio.synthesize(
                agent_01_quant_res=res_quant,
                agent_02_micro_res=res_micro,
                agent_03_risk_res=res_risk,
                agent_04_macro_res=res_macro,
                agent_06_guardian_res=res_guard,
            )
        except Exception as e:
            logger.warning(f"[AGENTE #5 CIO] ⚠️ {symbol} scartato -> eccezione {type(e).__name__}: {e}")
            return None
        decision = res_cio.get("veto") or res_cio.get("final_decision")
        logger.info(f"[AGENTE #5 CIO] 👑 {symbol} -> Ensemble Score: {_fmt(res_cio.get('cio_ensemble_score'), 2)}/100 "
                    f"-> Decisione: {decision}" + (f" ({res_cio.get('reason')})" if res_cio.get("veto") else ""))
        ms3 = (time.perf_counter() - t3) * 1000
        self.watchdog.record_latency("stage3", ms3)
        self.watchdog.count("stage3_done")
        logger.info(f"[STAGE 3 · EXECUTIVE DESK] 🏛️ {symbol} -> {decision} | latenze: Stage 1 {ms1:.2f}ms · "
                    f"Stage 2 {ms2:.1f}ms · Stage 3 {ms3:.1f}ms")

        result = {
            "symbol": symbol,
            "scout_id": candidate_data.get("scout_id"),
            "cio_result": res_cio,
            "raw_results": {"quant": res_quant, "micro": res_micro, "risk": res_risk, "macro": res_macro,
                            "guardian": res_guard},
            "stage_info": {"fast": fast, "scouts": [s for s in signals if s.get("triggered")], "news": news,
                           "latency_ms": {"stage1": round(ms1, 3), "stage2": round(ms2, 1), "stage3": round(ms3, 1)},
                           "forced": force},
        }
        with self._eval_lock:
            self.latest_evaluations[symbol_key(symbol)] = {**result, "evaluated_at": time.time()}
            self.stage_filtered.pop(symbol_key(symbol), None)
        return result

    async def analyze_candidate_worker(self, worker_id: int, candidate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Sottomette l'analisi di un singolo candidato Scout al Worker Pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._run_agent_pipeline, worker_id, candidate_data)

    def rationale_for(self, symbol: str, max_age_sec: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Rationale dei 7 agenti sull'ultima valutazione di Stage 3 (None se assente o troppo vecchia)."""
        with self._eval_lock:
            ev = self.latest_evaluations.get(symbol_key(symbol))
        if not ev or (max_age_sec is not None and time.time() - ev["evaluated_at"] > max_age_sec):
            return None
        raw, cio, st = ev["raw_results"], ev["cio_result"], ev.get("stage_info", {})
        guard = raw.get("guardian")
        return {
            "evaluated_at": ev["evaluated_at"],
            "agent_01_quant": {"score": raw["quant"].get("quant_score"), "signal": raw["quant"].get("trade_signal"),
                               "metrics": raw["quant"].get("metrics", {})},
            "agent_02_micro": {"score": raw["micro"].get("microstructure_score"), "signal": raw["micro"].get("trade_signal"),
                               "vpin": raw["micro"].get("metrics", {}).get("vpin_toxicity"),
                               "ofi": raw["micro"].get("metrics", {}).get("order_flow_imbalance")},
            "agent_03_risk": {"score": raw["risk"].get("risk_score"), "approved": raw["risk"].get("risk_approved"),
                              "reason": raw["risk"].get("reason"),
                              "stop_loss_price": raw["risk"].get("position_parameters", {}).get("stop_loss_price"),
                              "take_profit_price": raw["risk"].get("position_parameters", {}).get("take_profit_price")},
            "agent_04_macro": {"score": raw["macro"].get("macro_score"), "approved": raw["macro"].get("macro_approved"),
                               "stress_level": raw["macro"].get("stress_level"),
                               "news_sentiment": (st.get("news") or {}).get("sentiment"),
                               "headlines": (st.get("news") or {}).get("headlines")},
            "agent_05_cio": {"score": cio.get("cio_ensemble_score"), "decision": cio.get("veto") or cio.get("final_decision"),
                             "reason": cio.get("reason")},
            "agent_06_guardian": ({"approved": guard.get("guardian_approved"), "reason": guard.get("reason")}
                                  if guard else {"approved": None, "reason": "posizione già aperta: monitoraggio h24"}),
            "agent_07_chop": {"scouts": [f"#{s['scout_id']:03d} {s['category']} {s['side']}: {s['detail']}"
                                         for s in st.get("scouts", [])],
                              "stage1": st.get("fast"), "latency_ms": st.get("latency_ms"), "forced": st.get("forced")},
        }

    # ------------------------------------------------------------------ allocazione
    def evaluate_capital_recycling_swap(self, new_opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """
        Algoritmo di Asset Swap: determina se la nuova opportunità deve sostituire
        una posizione debole attiva in portafoglio.
        """
        symbol = new_opportunity["symbol"]
        cio_res = new_opportunity["cio_result"]
        new_strength = conviction_strength(cio_res)
        decision = cio_res.get("final_decision", "HOLD")

        if decision not in ["BUY", "SELL"]:
            return {"action": "REJECT", "reason": f"DECISION_IS_{decision}"}

        if symbol_key(symbol) in self.active_portfolio:
            return {"action": "REJECT", "reason": "ALREADY_IN_PORTFOLIO"}

        # Caso A: Il portafoglio ha ancora posti liberi
        if len(self.active_portfolio) < self.portfolio_max_slots:
            return {"action": "EXECUTE_NEW", "symbol": symbol, "reason": "SLOT_AVAILABLE"}

        # Caso B: Il portafoglio è pieno -> Cerca la posizione più debole per eventuale SWAP
        weakest_symbol = None
        lowest_strength = 999.0

        for active_sym, active_data in self.active_portfolio.items():
            active_strength = active_data.get("strength", 50.0)
            if active_strength < lowest_strength:
                lowest_strength = active_strength
                weakest_symbol = active_sym

        # Verifica della condizione di Swap Delta
        if weakest_symbol and new_strength > (lowest_strength + self.swap_delta_threshold):
            return {
                "action": "SWAP_POSITIONS",
                "close_symbol": weakest_symbol,
                "open_symbol": symbol,
                "delta_score": round(new_strength - lowest_strength, 2),
                "reason": f"HIGH_CONVICTION_SWAP (New: {new_strength} vs Old: {lowest_strength})"
            }

        return {
            "action": "REJECT",
            "reason": f"INSUFFICIENT_SWAP_DELTA (New: {new_strength} vs Lowest Active: {lowest_strength})"
        }

    def _register_position(self, symbol: str, cio_res: Dict[str, Any]) -> None:
        self.active_portfolio[symbol_key(symbol)] = {
            "symbol": symbol,
            "side": cio_res["final_decision"],
            "cio_ensemble_score": cio_res["cio_ensemble_score"],
            "strength": conviction_strength(cio_res),
            "details": cio_res
        }

    def _allocate(self, valid_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Le opportunità più forti occupano gli slot per prime: evita che un
        # candidato mediocre entri e venga subito swappato nello stesso batch.
        valid_results.sort(key=lambda r: conviction_strength(r["cio_result"]), reverse=True)
        execution_queue = []
        for item in valid_results:
            cio_res = item["cio_result"]
            if cio_res.get("final_decision") in ["BUY", "SELL"]:
                swap_decision = self.evaluate_capital_recycling_swap(item)

                if swap_decision["action"] == "EXECUTE_NEW":
                    logger.info(f"🟢 [APERTURA NUOVA] {item['symbol']} {cio_res['final_decision']} approvato con score {cio_res['cio_ensemble_score']}")
                    self._register_position(item["symbol"], cio_res)
                    execution_queue.append({"action": "OPEN", "data": item, "swap_info": swap_decision})

                elif swap_decision["action"] == "SWAP_POSITIONS":
                    close_sym = swap_decision["close_symbol"]
                    logger.info(f"🔄 [ASSET SWAP] Chiusura {close_sym} per apertura {item['symbol']} (Delta Score: {swap_decision['delta_score']})")
                    self.active_portfolio.pop(close_sym, None)
                    self._register_position(item["symbol"], cio_res)
                    execution_queue.append({"action": "SWAP", "data": item, "swap_info": swap_decision})

                else:
                    logger.info(f"⚪ [REJECTED] {item['symbol']} - {swap_decision['reason']}")
            else:
                label = cio_res.get("veto") or cio_res.get("final_decision")
                logger.info(f"⚪ [{label}] {item['symbol']} - {cio_res.get('reason')}")
        return execution_queue

    # ------------------------------------------------------------------ stream degli Scout
    async def _consume_queue(self, queue: asyncio.Queue) -> List[Dict[str, Any]]:
        """Consumatori sulla coda finché non arriva STREAM_END; con backlog oltre il limite il CHOP aggiunge Worker."""
        results: List[Dict[str, Any]] = []
        received = 0
        tasks: List[asyncio.Task] = []

        async def consumer(worker_id: int) -> None:
            nonlocal received
            while True:
                candidate = await queue.get()
                try:
                    if candidate is STREAM_END:
                        await queue.put(STREAM_END)   # la sentinella ferma anche gli altri consumatori
                        return
                    received += 1
                    backlog = queue.qsize()
                    self.watchdog.record_queue(backlog)
                    add = self.watchdog.needs_more_workers(backlog, len(tasks))
                    if add:
                        self.scale_workers(add, reason=f"backlog coda {backlog} > {self.watchdog.backlog_limit}")
                        for _ in range(add):
                            tasks.append(asyncio.ensure_future(consumer(len(tasks))))
                    logger.info(f"[SCOUT STREAM] 📨 Ricevuto candidato {candidate.get('symbol')} "
                                f"dallo Scout #{candidate.get('scout_id', '?')} (coda {backlog})")
                    res = await self.analyze_candidate_worker(worker_id, candidate)
                    if res is not None:
                        results.append(res)
                except Exception as e:
                    sym = candidate.get("symbol") if isinstance(candidate, dict) else repr(candidate)
                    logger.warning(f"[SCOUT STREAM] ⚠️ Candidato {sym} scartato per eccezione {type(e).__name__}: {e}")
                finally:
                    queue.task_done()

        tasks.extend(asyncio.ensure_future(consumer(i)) for i in range(self.num_workers))
        while True:
            pending = [t for t in tasks if not t.done()]
            if not pending:
                break
            await asyncio.wait(pending)
        self.watchdog.record_queue(0)   # coda svuotata (resta solo la sentinella)
        if self.num_workers > self.base_workers:
            # Backlog smaltito: si torna al numero base di Worker
            old, extra = self.executor, self.num_workers - self.base_workers
            self.num_workers = self.base_workers
            self.executor = ThreadPoolExecutor(max_workers=self.num_workers, thread_name_prefix="quant-worker")
            old.shutdown(wait=False)
            self.watchdog.record_heal(f"Worker {self.num_workers + extra} → {self.num_workers} (coda smaltita)")
            logger.info(f"🐝 [CHOP AUTO-HEALING] Coda smaltita: Worker riportati a {self.num_workers}")
        logger.info(f"[SCOUT STREAM] Pacchetto completato: {received} candidati ricevuti, "
                    f"{len(results)} arrivati allo Stage 3 e valutati dall'Agente #5")
        return results

    async def process_scout_stream(
        self, scout_stream: Union[asyncio.Queue, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Ingestione dei candidati e pipeline a 3 Stage.

        scout_stream: asyncio.Queue alimentata dallo sciame (terminata da STREAM_END) oppure una lista
        di payload, che in questo caso passa prima dai 100 Scout.
        """
        if isinstance(scout_stream, asyncio.Queue):
            logger.info(f"[SCOUT STREAM] In ascolto sulla coda degli Scout con {self.num_workers} Workers...")
            valid_results = await self._consume_queue(scout_stream)
        else:
            logger.info(f"Ricevuti {len(scout_stream)} candidati: {self.swarm.size} Scout + {self.num_workers} Workers...")
            queue: asyncio.Queue = asyncio.Queue()
            _, valid_results = await asyncio.gather(self.swarm.stream(list(scout_stream), queue),
                                                    self._consume_queue(queue))
        return self._allocate(valid_results)

    async def run_swarm_cycle(self, payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sciame -> asyncio.Queue -> Stage 1-3, in streaming: gli agenti partono appena un ticker è pronto."""
        queue: asyncio.Queue = asyncio.Queue()
        _, plan = await asyncio.gather(self.swarm.stream(payloads, queue), self.process_scout_stream(queue))
        return plan

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)
        self.swarm.shutdown()


def dummy_ohlcv(seed: int, bars: int = 100) -> pd.DataFrame:
    """Barre OHLCV sintetiche per i test offline."""
    rng = np.random.default_rng(seed)
    close = rng.standard_normal(bars).cumsum() + 100
    open_ = close + rng.standard_normal(bars) * 0.3
    return pd.DataFrame({
        "open": open_,
        "high": np.maximum(open_, close) + rng.random(bars),
        "low": np.minimum(open_, close) - rng.random(bars),
        "close": close,
        "volume": rng.integers(100, 1000, bars)
    })


# ==============================================================================
# PIPELINE STREAMING DEMO / ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    async def main():
        core = QuantitativeTradingCore(portfolio_max_slots=2, num_workers=4)
        payloads = [build_scout_payload(sym, dummy_ohlcv(i, 300), account_balance=50000.0)
                    for i, sym in enumerate(["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"])]
        try:
            orders_to_execute = await core.run_swarm_cycle(payloads)
        finally:
            core.shutdown()
        print("\n--- PIANO ESECUTIVO GENERATO DALL'AGENTE #5 ---")
        for order in orders_to_execute:
            print(order["action"], order["data"]["symbol"], order["data"]["cio_result"]["final_decision"],
                  order["data"]["cio_result"]["cio_ensemble_score"], order["swap_info"])
        core.watchdog.maybe_audit(print, swarm=core.swarm, engine=core, force=True)

    asyncio.run(main())
