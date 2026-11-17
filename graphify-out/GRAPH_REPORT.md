# Graph Report - bot-trading  (2026-11-17)

## Corpus Check
- 37 files · ~74,370 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 4, .css 1)

## Summary
- 1117 nodes · 2396 edges · 64 communities (51 shown, 13 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 82 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e4979a44`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.py
- MacroSentimentAgent
- trading_core.py
- run_closed_market_pulse
- _chat_context
- coo_agent.py
- now_local
- PitchAuditRegister
- DynamicUniverseScreener
- run_trading_cycle
- quant_core.py
- HyperQuantAgent
- InstitutionalRiskAgent
- portfolio_allocator.py
- normalize_symbol
- MicrostructureAgent
- graphify.yml
- PortfolioGuardianAgent
- ChopWatchdog
- numpy
- micro_scout
- CIOStrategistAgent
- live_state_text
- ScoutSwarm
- require_login
- audit_board
- QuantitativeTradingCore
- ask_desk_cio
- read_json_file
- guardian_tick
- risk_limits
- test_portfolio_allocator.py
- earnings_within
- core_allocation.py
- rotate_capital
- command_center.py
- get_api_token
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- clamp_stop_pct
- package.json
- drawdown_scale
- describe_command
- initial_capital
- _gstate_read
- Piano di riorganizzazione del bot
- build_scout_payload
- .process_scout_stream
- log_message
- run_orchestrator_service
- _coo_tools
- background_loop
- snapshot_state
- git_sync_status.sh
- fix_and_run.sh
- start_background.sh
- stop_background.sh

## God Nodes (most connected - your core abstractions)
1. `run_trading_cycle()` - 51 edges
2. `normalize_symbol()` - 44 edges
3. `run_scout_swarm()` - 33 edges
4. `log_message()` - 31 edges
5. `QuantitativeTradingCore` - 29 edges
6. `now_local()` - 26 edges
7. `get_config()` - 26 edges
8. `is_crypto()` - 24 edges
9. `MacroSentimentAgent` - 21 edges
10. `validate_desk_decision()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Dati e affidabilità` --references--> `log_message()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Capitale e rischio` --references--> `rebalance()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → agents/core_allocation.py
- `Organizzazione del codice` --references--> `run_trading_cycle()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → app.py
- `Organizzazione del codice` --references--> `_decide()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → command_center.py
- `Organizzazione del codice` --references--> `run_scout_swarm()`  [INFERRED]
  docs/PIANO_RIORGANIZZAZIONE.md → trading_core.py

## Import Cycles
- None detected.

## Communities (64 total, 13 thin omitted)

### Community 0 - "app.py"
Cohesion: 0.10
Nodes (13): _cancel_open_orders(), chop_loop(), ensure_background_threads(), guardian_loop(), keep_alive_loop(), keep_alive_url(), login(), login_blocked_for() (+5 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.07
Nodes (6): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, parse_news_assessment(), test_negative_news_stays_a_veto()

### Community 2 - "trading_core.py"
Cohesion: 0.05
Nodes (12): account_balance_for_agents(), chop_audit(), gate_quant_ensemble(), gate_technical_liquidity(), _prune_cache(), prune_runtime_caches(), release_memory(), scout_pitch_threshold() (+4 more)

### Community 3 - "run_closed_market_pulse"
Cohesion: 0.11
Nodes (11): crypto_fear_greed(), _daily_frames(), desk_universe(), _download(), dynamic_volume_spikes(), is_us_market_open(), _now_epoch(), radar_snapshot() (+3 more)

### Community 4 - "_chat_context"
Cohesion: 0.14
Nodes (13): account_with_pnl(), api_audit(), api_data(), api_position_detail(), cached(), _chat_context(), _find_position(), get_account_summary() (+5 more)

### Community 5 - "coo_agent.py"
Cohesion: 0.07
Nodes (8): _clip(), COOAgent, _public_url(), _retry_after(), _strip_html(), WebResearch, blocked_name(), main()

### Community 6 - "now_local"
Cohesion: 0.08
Nodes (18): test_trend_features_ignore_illiquid_and_todays_bar(), completed_daily_close(), dynamic_stop_pct(), _ema(), get_daily_bars(), guardian_evaluate(), guardian_signals(), guardian_trend_break() (+10 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.15
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.10
Nodes (3): DynamicUniverseScreener, _TimeoutAdapter, with_http_timeout()

### Community 9 - "run_trading_cycle"
Cohesion: 0.11
Nodes (13): deploy_liquidity(), describe_decision(), execute_buy(), position_open_risk(), run_trading_cycle(), set_ai_analysis(), account_after_buy(), buy_thesis_for() (+5 more)

### Community 10 - "quant_core.py"
Cohesion: 0.13
Nodes (4): ofi_to_score(), _build_logger(), _ColorFormatter, _fmt()

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 12 - "InstitutionalRiskAgent"
Cohesion: 0.11
Nodes (3): crypto_night_blocked(), hard_stop_pct(), InstitutionalRiskAgent

### Community 13 - "portfolio_allocator.py"
Cohesion: 0.15
Nodes (5): conviction_factor(), open_risk_usd(), trend_up_confirmed(), test_one_close_below_ema100_does_not_flip_the_regime(), test_open_risk_of_a_runner_is_smaller()

### Community 14 - "normalize_symbol"
Cohesion: 0.08
Nodes (21): radar_loop(), news(), alpaca_order_symbol(), _audit_safe(), _audit_stages(), crypto_order_books(), gate_risk_atr(), get_pending_order_symbols() (+13 more)

### Community 16 - "graphify.yml"
Cohesion: 0.10
Nodes (20): concurrency, cancel-in-progress, group, jobs, update-graph, name, on, push (+12 more)

### Community 17 - "PortfolioGuardianAgent"
Cohesion: 0.13
Nodes (5): PortfolioGuardianAgent, _usd(), test_guardian_moves_stop_to_breakeven_after_one_r(), test_guardian_trend_break_exit(), test_small_vix_rise_is_not_a_news_shock()

### Community 19 - "numpy"
Cohesion: 0.07
Nodes (22): core_returns(), mix(), stats(), daily_index(), effective_stop(), enter(), entries_allocator(), entries_current() (+14 more)

### Community 20 - "micro_scout"
Cohesion: 0.07
Nodes (16): atr_pct(), beta_correlation(), classify_score(), completed_bars(), compute_indicators(), get_indicators(), guardian_peak(), hourly_atr_pct() (+8 more)

### Community 21 - "CIOStrategistAgent"
Cohesion: 0.17
Nodes (4): build_buy_thesis(), CIOStrategistAgent, test_full_portfolio_is_not_a_veto_so_no_cooldown(), test_trade_is_possible_without_news()

### Community 22 - "live_state_text"
Cohesion: 0.20
Nodes (8): agents_snapshot(), blocks_text(), _clean(), logs(), diagnosis_lines(), live_state_text(), status_text(), thoughts_for()

### Community 24 - "require_login"
Cohesion: 0.12
Nodes (14): _agent_feeds(), api_agent_brain(), api_agents(), api_chat_history(), api_history(), api_settings_get(), has_valid_token(), index() (+6 more)

### Community 25 - "audit_board"
Cohesion: 0.16
Nodes (11): rejected(), audit_board(), fallback_votes(), _chop_health(), _db(), last_entry_execution(), list_executions(), pitch_audit() (+3 more)

### Community 26 - "QuantitativeTradingCore"
Cohesion: 0.14
Nodes (4): age_assessment(), conviction_strength(), QuantitativeTradingCore, symbol_key()

### Community 27 - "ask_desk_cio"
Cohesion: 0.13
Nodes (11): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), groq_news_llm(), _no_ai_keys(), parse_broker_json() (+3 more)

### Community 28 - "read_json_file"
Cohesion: 0.12
Nodes (10): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _review_context(), save_state(), sync_ledger() (+2 more)

### Community 29 - "guardian_tick"
Cohesion: 0.33
Nodes (4): guardian_tick(), journal_operation(), request_cio(), is_market_open()

### Community 30 - "risk_limits"
Cohesion: 0.16
Nodes (8): risk_limits(), size_trade(), stop_pct(), test_crypto_cap(), test_limits_shrink_with_regime_and_never_use_margin(), test_more_volatile_titles_get_less_capital(), test_size_never_exceeds_cap_or_cash_floor(), desk_limits()

### Community 31 - "test_portfolio_allocator.py"
Cohesion: 0.14
Nodes (10): desk(), test_core_position_is_invisible_to_guardian_and_radar(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_liquidity_wakes_the_cio(), test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), with_core() (+2 more)

### Community 32 - "earnings_within"
Cohesion: 0.18
Nodes (6): earnings_within(), events_for_agents(), _finnhub_headlines(), gate_sentiment_compliance(), get_recent_news(), sentiment_score()

### Community 33 - "core_allocation.py"
Cohesion: 0.19
Nodes (7): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), test_core_rebalances_only_outside_the_band(), test_satellite_account_hides_the_core_cash()

### Community 34 - "rotate_capital"
Cohesion: 0.14
Nodes (8): bot_account(), core_spy_pct(), fetch_bot_positions(), fetch_open_positions(), rebalance_core(), rotate_capital(), submit_core_order(), wait_for_fill()

### Community 35 - "command_center.py"
Cohesion: 0.22
Nodes (9): _agent(), brief_state_text(), build_system_prompt(), chat_history(), _fmt(), _groq_client(), _llm_chat(), pending_proposal() (+1 more)

### Community 36 - "get_api_token"
Cohesion: 0.40
Nodes (3): get_dashboard_password(), get_secret_key(), _secret()

### Community 37 - "get_config"
Cohesion: 0.26
Nodes (16): 2. Criticità trovate, Capitale e rischio, Dati e affidabilità, Organizzazione del codice, account(), buy(), holding(), pitch() (+8 more)

### Community 38 - "chat"
Cohesion: 0.18
Nodes (7): _apply(), chat(), fallback_reply(), local_reply(), _precheck(), _propose(), _push()

### Community 39 - "update_config"
Cohesion: 0.13
Nodes (10): config_sources(), env_overrides(), _load_config(), _parse_env_value(), public_config(), _read_config_file(), repo_defaults(), _save_config() (+2 more)

### Community 40 - "_decide"
Cohesion: 0.24
Nodes (9): clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), set_agent(), set_block() (+1 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.18
Nodes (6): _ago(), latest_channels(), pipeline_diagnosis(), _reason_key(), _registry_data(), _registry_view()

### Community 42 - "clamp_stop_pct"
Cohesion: 0.17
Nodes (7): clamp_stop_pct(), allocation_pct_for_score(), available_funds(), build_desk_cio_prompt(), buy_budget(), max_exposure_pct(), risk_manager()

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 44 - "drawdown_scale"
Cohesion: 0.25
Nodes (5): drawdown_scale(), regime_scale(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_regime_scale()

### Community 45 - "describe_command"
Cohesion: 0.22
Nodes (6): propose(), describe_command(), normalize_command(), parse_command(), _rule_parse(), _segment_label()

### Community 46 - "initial_capital"
Cohesion: 0.33
Nodes (3): equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 47 - "_gstate_read"
Cohesion: 0.16
Nodes (8): _fallback_thesis(), _gstate_read(), _gstate_write(), guardian_position_state(), guardian_prune(), guardian_record_exit(), guardian_register_entry(), _thesis_fields()

### Community 48 - "Piano di riorganizzazione del bot"
Cohesion: 0.14
Nodes (13): 1. In breve, 3. Strategie: cosa dicono gli studi, 3a. Metà "trading" (giorni-settimane): trend e momentum, 3b. Metà "day trading" (dentro la giornata, tutto chiuso entro le 15:55 di New York), 4. Divisione 50% / 50%, 5. Nuova organizzazione degli agenti, 6. Riorganizzazione del codice, 7. Grafica "a prova di bambino" (+5 more)

### Community 49 - "build_scout_payload"
Cohesion: 0.21
Nodes (6): build_scout_payload(), dummy_ohlcv(), looks_crypto(), main(), normalize_ohlcv(), test_pipeline_buys_a_trending_stock_without_news()

### Community 51 - "log_message"
Cohesion: 0.14
Nodes (17): api_agent_control(), api_blocks(), api_chat(), api_liquidate(), api_position_close(), api_position_de_risk(), api_settings_post(), api_toggle() (+9 more)

### Community 52 - "run_orchestrator_service"
Cohesion: 0.15
Nodes (8): _audit_close(), cio_inbox(), _close(), load_scout_registry(), record_cio_outcome(), run_orchestrator_service(), _save_registry(), _transition()

### Community 53 - "_coo_tools"
Cohesion: 0.29
Nodes (5): _coo_tools(), account(), settings(), _fn(), _ticker_detail()

### Community 55 - "snapshot_state"
Cohesion: 0.18
Nodes (7): block_reason(), filter_inbox(), sector_of(), _segment_impact(), segment_matches(), snapshot_state(), pitch_conviction()

## Knowledge Gaps
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `MacroSentimentAgent`, `trading_core.py`, `quant_core.py`, `normalize_symbol`, `MicrostructureAgent`, `build_scout_payload`, `PortfolioGuardianAgent`, `ChopWatchdog`, `.process_scout_stream`, `CIOStrategistAgent`, `ScoutSwarm`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_trading_cycle()` (e.g. with `api_trigger()` and `Organizzazione del codice`) actually correct?**
  _`run_trading_cycle()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09846153846153846 - nodes in this community are weakly interconnected._
- **Why does `MicrostructureAgent` connect `MicrostructureAgent` to `QuantitativeTradingCore`, `quant_core.py`, `numpy`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_scout_swarm()` (e.g. with `Organizzazione del codice` and `run_one()`) actually correct?**
  _`run_scout_swarm()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.07227891156462585 - nodes in this community are weakly interconnected._
- **Why does `PitchAuditRegister` connect `PitchAuditRegister` to `audit_board`, `trading_core.py`, `coo_agent.py`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._