# Graph Report - bot-trading  (2026-11-17)

## Corpus Check
- 38 files · ~76,632 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .css 2)

## Summary
- 1131 nodes · 2423 edges · 65 communities (48 shown, 17 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 83 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7b6077a5`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.py
- MacroSentimentAgent
- trading_core.py
- portfolio_sim.py
- _chat_context
- Any
- completed_daily_close
- PitchAuditRegister
- DynamicUniverseScreener
- run_trading_cycle
- quant_core.py
- HyperQuantAgent
- InstitutionalRiskAgent
- run_scout_swarm
- MicrostructureAgent
- graphify.yml
- PortfolioGuardianAgent
- ChopWatchdog
- detectors.py
- micro_scout
- api_position_detail
- snapshot_state
- ScoutSwarm
- api_agent_brain
- audit_board
- QuantitativeTradingCore
- ask_desk_cio
- read_json_file
- guardian_tick
- risk_limits
- test_portfolio_allocator.py
- coo_agent.py
- core_allocation.py
- rotate_capital
- command_center.py
- get_api_token
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- numpy
- package.json
- drawdown_scale
- describe_command
- initial_capital
- universe_chunk
- Piano di riorganizzazione del bot
- os
- yf_data_symbol
- _build_logger
- _warn_throttled
- agent_04_macro.py
- apply_trend_rank
- segment_matches
- prune_runtime_caches
- git_sync_status.sh
- fix_and_run.sh
- start_background.sh
- stop_background.sh

## God Nodes (most connected - your core abstractions)
1. `run_trading_cycle()` - 51 edges
2. `normalize_symbol()` - 45 edges
3. `run_scout_swarm()` - 33 edges
4. `log_message()` - 32 edges
5. `QuantitativeTradingCore` - 29 edges
6. `now_local()` - 26 edges
7. `get_config()` - 26 edges
8. `is_crypto()` - 24 edges
9. `validate_desk_decision()` - 21 edges
10. `MacroSentimentAgent` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Dati e affidabilità` --references--> `log_message()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Organizzazione del codice` --references--> `run_trading_cycle()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Organizzazione del codice` --references--> `run_scout_swarm()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py
- `5. Nuova organizzazione degli agenti` --references--> `validate_desk_decision()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py
- `Capitale e rischio` --references--> `validate_desk_decision()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py

## Import Cycles
- None detected.

## Communities (65 total, 17 thin omitted)

### Community 0 - "app.py"
Cohesion: 0.07
Nodes (34): api_agent_control(), api_chat(), api_liquidate(), api_orders(), api_position_close(), api_position_de_risk(), api_settings_post(), api_toggle() (+26 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.06
Nodes (11): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, news(), test_negative_news_stays_a_veto(), chop_audit(), events_for_agents() (+3 more)

### Community 2 - "trading_core.py"
Cohesion: 0.04
Nodes (14): account_after_buy(), allocation_pct_for_score(), available_funds(), dynamic_volume_spikes(), _finnhub_headlines(), gate_technical_liquidity(), get_recent_news(), performance_stats() (+6 more)

### Community 3 - "portfolio_sim.py"
Cohesion: 0.16
Nodes (10): daily_index(), effective_stop(), enter(), entries_allocator(), entries_current(), exits_trend(), load_data(), Market (+2 more)

### Community 4 - "_chat_context"
Cohesion: 0.08
Nodes (21): account_with_pnl(), _agent_feeds(), api_agents(), api_audit(), api_data(), api_history(), cached(), _chat_context() (+13 more)

### Community 5 - "Any"
Cohesion: 0.17
Nodes (3): _clip(), COOAgent, WebResearch

### Community 6 - "completed_daily_close"
Cohesion: 0.15
Nodes (10): trend_up_confirmed(), test_one_close_below_ema100_does_not_flip_the_regime(), test_trend_features_ignore_illiquid_and_todays_bar(), completed_daily_close(), _ema(), get_daily_bars(), guardian_trend_break(), macro_channel() (+2 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.15
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.10
Nodes (3): DynamicUniverseScreener, _TimeoutAdapter, with_http_timeout()

### Community 9 - "run_trading_cycle"
Cohesion: 0.06
Nodes (30): deploy_liquidity(), describe_decision(), execute_buy(), position_open_risk(), rebalance_core(), run_trading_cycle(), rejected(), _ticker_detail() (+22 more)

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 12 - "InstitutionalRiskAgent"
Cohesion: 0.08
Nodes (8): crypto_night_blocked(), InstitutionalRiskAgent, FakeAlpaca, test_api_orders_requires_token_and_validates_date(), test_order_history_classifies_core_bot_and_manual(), test_order_history_filters_symbol_and_returns_none_without_alpaca(), get_api_token(), order_history()

### Community 14 - "run_scout_swarm"
Cohesion: 0.06
Nodes (30): _audit_close(), _audit_safe(), _audit_stages(), cio_inbox(), _close(), crypto_fear_greed(), crypto_order_books(), _daily_frames() (+22 more)

### Community 16 - "graphify.yml"
Cohesion: 0.10
Nodes (20): concurrency, cancel-in-progress, group, jobs, update-graph, name, on, push (+12 more)

### Community 17 - "PortfolioGuardianAgent"
Cohesion: 0.13
Nodes (5): PortfolioGuardianAgent, _usd(), test_guardian_moves_stop_to_breakeven_after_one_r(), test_guardian_trend_break_exit(), test_small_vix_rise_is_not_a_news_shock()

### Community 19 - "detectors.py"
Cohesion: 0.20
Nodes (9): _atr(), breakout(), hurst_exponent(), mean_reversion(), orderbook(), _signal(), volatility(), volume() (+1 more)

### Community 20 - "micro_scout"
Cohesion: 0.10
Nodes (11): beta_correlation(), classify_score(), completed_bars(), compute_indicators(), get_indicators(), indicators_on_closed_bars(), market_analyst(), micro_scout() (+3 more)

### Community 21 - "api_position_detail"
Cohesion: 0.11
Nodes (9): api_position_detail(), dynamic_stop_pct(), gate_quant_ensemble(), gate_risk_atr(), guardian_atr(), guardian_atr_info(), guardian_watch(), position_stop() (+1 more)

### Community 22 - "snapshot_state"
Cohesion: 0.15
Nodes (11): block_reason(), blocks_text(), brief_state_text(), build_system_prompt(), diagnosis_lines(), filter_inbox(), _fmt(), live_state_text() (+3 more)

### Community 24 - "api_agent_brain"
Cohesion: 0.33
Nodes (5): api_agent_brain(), agents_snapshot(), _clean(), logs(), thoughts_for()

### Community 25 - "audit_board"
Cohesion: 0.16
Nodes (9): audit_board(), fallback_votes(), _chop_health(), _db(), _fallback_thesis(), last_entry_execution(), list_executions(), _row_dict() (+1 more)

### Community 26 - "QuantitativeTradingCore"
Cohesion: 0.05
Nodes (16): build_buy_thesis(), CIOStrategistAgent, age_assessment(), build_scout_payload(), conviction_strength(), dummy_ohlcv(), _fmt(), looks_crypto() (+8 more)

### Community 27 - "ask_desk_cio"
Cohesion: 0.22
Nodes (7): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), parse_broker_json(), parse_desk_decision()

### Community 28 - "read_json_file"
Cohesion: 0.12
Nodes (10): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _review_context(), save_state(), sync_ledger() (+2 more)

### Community 29 - "guardian_tick"
Cohesion: 0.18
Nodes (7): guardian_loop(), guardian_tick(), journal_operation(), radar_loop(), request_cio(), get_pending_order_symbols(), is_market_open()

### Community 30 - "risk_limits"
Cohesion: 0.14
Nodes (9): conviction_factor(), risk_limits(), size_trade(), stop_pct(), test_crypto_cap(), test_limits_shrink_with_regime_and_never_use_margin(), test_more_volatile_titles_get_less_capital(), test_size_never_exceeds_cap_or_cash_floor() (+1 more)

### Community 31 - "test_portfolio_allocator.py"
Cohesion: 0.17
Nodes (8): open_risk_usd(), desk(), test_core_position_is_invisible_to_guardian_and_radar(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_liquidity_wakes_the_cio(), test_open_risk_of_a_runner_is_smaller(), with_core()

### Community 32 - "coo_agent.py"
Cohesion: 0.19
Nodes (3): _public_url(), _retry_after(), _strip_html()

### Community 33 - "core_allocation.py"
Cohesion: 0.19
Nodes (7): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), test_core_rebalances_only_outside_the_band(), test_satellite_account_hides_the_core_cash()

### Community 34 - "rotate_capital"
Cohesion: 0.20
Nodes (6): bot_account(), core_spy_pct(), fetch_bot_positions(), fetch_open_positions(), rotate_capital(), to_yf_symbol()

### Community 35 - "command_center.py"
Cohesion: 0.19
Nodes (10): api_chat_history(), _agent(), chat_history(), _coo_tools(), settings(), _fn(), _groq_client(), _llm_chat() (+2 more)

### Community 36 - "get_api_token"
Cohesion: 0.40
Nodes (3): get_dashboard_password(), get_secret_key(), _secret()

### Community 37 - "get_config"
Cohesion: 0.31
Nodes (13): account(), buy(), holding(), pitch(), test_ai_cannot_choose_the_size(), test_bot_never_buys_the_core_symbol(), test_exhausted_risk_budget_holds(), test_panic_regime_blocks_and_crypto_needs_btc_trend() (+5 more)

### Community 38 - "chat"
Cohesion: 0.29
Nodes (4): fallback_reply(), _precheck(), _propose(), _push()

### Community 39 - "update_config"
Cohesion: 0.12
Nodes (11): api_settings_get(), config_sources(), env_overrides(), _load_config(), _parse_env_value(), public_config(), _read_config_file(), repo_defaults() (+3 more)

### Community 40 - "_decide"
Cohesion: 0.21
Nodes (10): api_blocks(), clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), set_agent() (+2 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.22
Nodes (5): _ago(), pipeline_diagnosis(), _reason_key(), _registry_data(), _registry_view()

### Community 42 - "numpy"
Cohesion: 0.19
Nodes (5): clamp_stop_pct(), hard_stop_pct(), core_returns(), mix(), stats()

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 44 - "drawdown_scale"
Cohesion: 0.25
Nodes (5): drawdown_scale(), regime_scale(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_regime_scale()

### Community 45 - "describe_command"
Cohesion: 0.17
Nodes (8): _apply(), chat(), propose(), describe_command(), normalize_command(), parse_command(), _rule_parse(), _segment_label()

### Community 46 - "initial_capital"
Cohesion: 0.25
Nodes (4): account_balance_for_agents(), equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 47 - "universe_chunk"
Cohesion: 0.15
Nodes (7): alpaca_order_symbol(), is_tradable(), release_memory(), to_alpaca_symbol(), universe_chunk(), universe_screener(), yf_missing()

### Community 48 - "Piano di riorganizzazione del bot"
Cohesion: 0.11
Nodes (17): 1. In breve, 2. Criticità trovate, 3. Strategie: cosa dicono gli studi, 3a. Metà "trading" (giorni-settimane): trend e momentum, 3b. Metà "day trading" (dentro la giornata, tutto chiuso entro le 15:55 di New York), 4. Divisione 50% / 50%, 5. Nuova organizzazione degli agenti, 6. Riorganizzazione del codice (+9 more)

### Community 50 - "yf_data_symbol"
Cohesion: 0.20
Nodes (5): atr_pct(), guardian_peak(), hourly_atr_pct(), _peak_since(), yf_data_symbol()

### Community 52 - "_warn_throttled"
Cohesion: 0.33
Nodes (4): groq_news_llm(), _no_ai_keys(), _resolve_provider(), _warn_throttled()

### Community 54 - "apply_trend_rank"
Cohesion: 0.33
Nodes (4): test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), apply_trend_rank(), trend_score()

### Community 55 - "segment_matches"
Cohesion: 0.40
Nodes (3): sector_of(), _segment_impact(), segment_matches()

## Knowledge Gaps
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `MacroSentimentAgent`, `trading_core.py`, `quant_core.py`, `MicrostructureAgent`, `PortfolioGuardianAgent`, `ChopWatchdog`, `ScoutSwarm`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_trading_cycle()` (e.g. with `api_trigger()` and `Organizzazione del codice`) actually correct?**
  _`run_trading_cycle()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07130333138515488 - nodes in this community are weakly interconnected._
- **Why does `MicrostructureAgent` connect `MicrostructureAgent` to `QuantitativeTradingCore`, `MacroSentimentAgent`, `numpy`, `quant_core.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_scout_swarm()` (e.g. with `Organizzazione del codice` and `run_one()`) actually correct?**
  _`run_scout_swarm()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.05714285714285714 - nodes in this community are weakly interconnected._
- **Why does `DynamicUniverseScreener` connect `DynamicUniverseScreener` to `coo_agent.py`, `trading_core.py`, `universe_chunk`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._