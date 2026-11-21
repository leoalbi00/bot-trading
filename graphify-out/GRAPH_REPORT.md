# Graph Report - bot-trading  (2026-11-21)

## Corpus Check
- 40 files · ~79,138 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .css 2)

## Summary
- 1185 nodes · 2547 edges · 82 communities (53 shown, 29 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 89 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3a62d52d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- route
- MacroSentimentAgent
- test_order_history.py
- _chat_context
- Any
- normalize_symbol
- PitchAuditRegister
- DynamicUniverseScreener
- quant_engine
- ask_desk_cio
- HyperQuantAgent
- InstitutionalRiskAgent
- quant_core.py
- run_scout_swarm
- MicrostructureAgent
- graphify.yml
- PortfolioGuardianAgent
- ChopWatchdog
- numpy
- micro_scout
- buy_budget
- snapshot_state
- ScoutSwarm
- api_position_de_risk
- audit_board
- Any
- env_overrides
- read_json_file
- CIOStrategistAgent
- risk_limits
- desk
- quant_rationale
- core_allocation.py
- rotate_capital
- command_center.py
- QuantitativeTradingCore
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- require_login
- package.json
- portfolio_allocator.py
- parse_command
- initial_capital
- risk_committee
- Piano di riorganizzazione del bot
- test_swarm_regressions.py
- consumer
- _build_logger
- build_desk_cio_prompt
- .guarded_llm_call
- apply_trend_rank
- segment_matches
- log_message
- prune_runtime_caches
- git_sync_status.sh
- fix_and_run.sh
- start_background.sh
- stop_background.sh
- app.py
- api_agent_brain
- api_position_close
- build_scout_payload
- write_json_file
- _fallback_thesis
- get_recent_news
- cio_inbox
- dynamic_volume_spikes
- performance_stats
- sentiment_score
- startup_system_sync
- scout_pitch_threshold
- to_yf_symbol
- wait_for_fill
- submit_core_order

## God Nodes (most connected - your core abstractions)
1. `run_trading_cycle()` - 51 edges
2. `normalize_symbol()` - 47 edges
3. `run_scout_swarm()` - 36 edges
4. `log_message()` - 32 edges
5. `get_config()` - 32 edges
6. `QuantitativeTradingCore` - 29 edges
7. `now_local()` - 26 edges
8. `is_crypto()` - 24 edges
9. `ChopWatchdog` - 22 edges
10. `validate_desk_decision()` - 22 edges

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

## Communities (82 total, 29 thin omitted)

### Community 0 - "route"
Cohesion: 0.12
Nodes (14): api_agent_control(), api_audit(), api_blocks(), api_chat(), api_history(), api_orders(), api_settings_post(), api_toggle() (+6 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.08
Nodes (5): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, test_negative_news_stays_a_veto()

### Community 3 - "test_order_history.py"
Cohesion: 0.12
Nodes (10): index(), FakeAlpaca, test_api_orders_requires_token_and_validates_date(), test_order_history_classifies_core_bot_and_manual(), test_order_history_filters_symbol_and_returns_none_without_alpaca(), get_api_token(), get_dashboard_password(), get_secret_key() (+2 more)

### Community 4 - "_chat_context"
Cohesion: 0.20
Nodes (10): account_with_pnl(), api_data(), cached(), _chat_context(), _find_position(), get_account_summary(), get_open_positions(), positions_with_allocation() (+2 more)

### Community 5 - "Any"
Cohesion: 0.05
Nodes (10): parse_news_assessment(), _rss_mb(), _clip(), COOAgent, _public_url(), _retry_after(), _strip_html(), WebResearch (+2 more)

### Community 6 - "normalize_symbol"
Cohesion: 0.06
Nodes (26): clamp_stop_pct(), api_position_detail(), _cancel_open_orders(), position_open_risk(), account(), dynamic_stop_pct(), _gstate_read(), _gstate_write() (+18 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.15
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.05
Nodes (15): DynamicUniverseScreener, test_closed_market_buy_goes_to_opening_list_only_in_preparation(), test_closed_market_universe_includes_stocks_only_in_preparation(), test_foreign_markets_snapshot_reports_daily_change(), test_old_opening_candidates_expire(), test_opening_candidates_are_remembered_and_forgotten(), test_render_variable_overrides_the_mode(), foreign_markets_snapshot() (+7 more)

### Community 9 - "quant_engine"
Cohesion: 0.18
Nodes (6): news(), chop_audit(), events_for_agents(), guardian_signals(), _ofi_exit_signal(), quant_engine()

### Community 10 - "ask_desk_cio"
Cohesion: 0.13
Nodes (11): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), groq_news_llm(), _no_ai_keys(), parse_broker_json() (+3 more)

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 12 - "InstitutionalRiskAgent"
Cohesion: 0.11
Nodes (3): crypto_night_blocked(), hard_stop_pct(), InstitutionalRiskAgent

### Community 14 - "run_scout_swarm"
Cohesion: 0.07
Nodes (28): _audit_safe(), _close(), crypto_fear_greed(), crypto_order_books(), _daily_frames(), desk_universe(), _download(), earnings_within() (+20 more)

### Community 16 - "graphify.yml"
Cohesion: 0.10
Nodes (20): concurrency, cancel-in-progress, group, jobs, update-graph, name, on, push (+12 more)

### Community 17 - "PortfolioGuardianAgent"
Cohesion: 0.12
Nodes (6): PortfolioGuardianAgent, _usd(), test_backtest_vix_exit_matches_guardian_rule(), test_guardian_moves_stop_to_breakeven_after_one_r(), test_guardian_trend_break_exit(), test_small_vix_rise_is_not_a_news_shock()

### Community 19 - "numpy"
Cohesion: 0.08
Nodes (23): core_returns(), mix(), stats(), daily_index(), effective_stop(), enter(), entries_allocator(), entries_current() (+15 more)

### Community 20 - "micro_scout"
Cohesion: 0.06
Nodes (23): test_trend_features_ignore_illiquid_and_todays_bar(), atr_pct(), beta_correlation(), classify_score(), completed_bars(), completed_daily_close(), compute_indicators(), _ema() (+15 more)

### Community 21 - "buy_budget"
Cohesion: 0.18
Nodes (6): allocation_pct_for_score(), available_funds(), buy_budget(), _desk_cio_prompt_text(), _fmt_pct(), max_exposure_pct()

### Community 22 - "snapshot_state"
Cohesion: 0.17
Nodes (10): block_reason(), blocks_text(), brief_state_text(), build_system_prompt(), diagnosis_lines(), filter_inbox(), _fmt(), live_state_text() (+2 more)

### Community 24 - "api_position_de_risk"
Cohesion: 0.17
Nodes (9): api_position_de_risk(), execute_sell(), guardian_tick(), journal_operation(), radar_loop(), request_cio(), close_position_pct(), get_pending_order_symbols() (+1 more)

### Community 25 - "audit_board"
Cohesion: 0.24
Nodes (7): audit_board(), fallback_votes(), _chop_health(), _db(), last_entry_execution(), list_executions(), _row_dict()

### Community 26 - "Any"
Cohesion: 0.18
Nodes (4): age_assessment(), conviction_strength(), _fmt(), symbol_key()

### Community 27 - "env_overrides"
Cohesion: 0.25
Nodes (5): settings(), config_sources(), env_overrides(), _parse_env_value(), public_config()

### Community 28 - "read_json_file"
Cohesion: 0.15
Nodes (8): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _registry_data(), _review_context(), win_rates()

### Community 29 - "CIOStrategistAgent"
Cohesion: 0.17
Nodes (3): CIOStrategistAgent, test_full_portfolio_is_not_a_veto_so_no_cooldown(), test_trade_is_possible_without_news()

### Community 30 - "risk_limits"
Cohesion: 0.14
Nodes (13): risk_limits(), size_trade(), stop_pct(), test_core_position_is_invisible_to_guardian_and_radar(), test_crypto_cap(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_limits_shrink_with_regime_and_never_use_margin() (+5 more)

### Community 32 - "quant_rationale"
Cohesion: 0.10
Nodes (13): deploy_liquidity(), execute_buy(), rejected(), _ticker_detail(), account_after_buy(), _audit_close(), _audit_stages(), buy_thesis_for() (+5 more)

### Community 33 - "core_allocation.py"
Cohesion: 0.19
Nodes (7): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), test_core_rebalances_only_outside_the_band(), test_satellite_account_hides_the_core_cash()

### Community 34 - "rotate_capital"
Cohesion: 0.17
Nodes (9): bot_account(), core_spy_pct(), describe_decision(), fetch_bot_positions(), fetch_open_positions(), rebalance_core(), rotate_capital(), run_trading_cycle() (+1 more)

### Community 35 - "command_center.py"
Cohesion: 0.29
Nodes (6): _agent(), _coo_tools(), _fn(), _groq_client(), _llm_chat(), _web_research()

### Community 36 - "QuantitativeTradingCore"
Cohesion: 0.16
Nodes (4): dummy_ohlcv(), main(), QuantitativeTradingCore, test_pipeline_buys_a_trending_stock_without_news()

### Community 37 - "get_config"
Cohesion: 0.32
Nodes (14): account(), buy(), holding(), pitch(), test_ai_cannot_choose_the_size(), test_bot_never_buys_the_core_symbol(), test_exhausted_risk_budget_holds(), test_five_positions_block_new_buys() (+6 more)

### Community 38 - "chat"
Cohesion: 0.22
Nodes (6): chat(), fallback_reply(), local_reply(), _precheck(), _propose(), _push()

### Community 39 - "update_config"
Cohesion: 0.20
Nodes (7): test_default_is_preparation_and_values_are_validated(), _load_config(), _read_config_file(), repo_defaults(), _save_config(), update_config(), _validate_config()

### Community 40 - "_decide"
Cohesion: 0.23
Nodes (11): _apply(), clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), _segment_label() (+3 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.17
Nodes (6): _ago(), latest_channels(), pipeline_diagnosis(), radar_snapshot(), _reason_key(), _registry_view()

### Community 42 - "require_login"
Cohesion: 0.25
Nodes (8): api_chat_history(), api_settings_get(), has_valid_token(), require_login(), wrapper(), wrapper(), chat_history(), pending_proposal()

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 44 - "portfolio_allocator.py"
Cohesion: 0.12
Nodes (10): conviction_factor(), drawdown_scale(), open_risk_usd(), regime_scale(), trend_up_confirmed(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_one_close_below_ema100_does_not_flip_the_regime() (+2 more)

### Community 45 - "parse_command"
Cohesion: 0.25
Nodes (5): propose(), describe_command(), normalize_command(), parse_command(), _rule_parse()

### Community 46 - "initial_capital"
Cohesion: 0.25
Nodes (4): account_balance_for_agents(), equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 47 - "risk_committee"
Cohesion: 0.12
Nodes (8): alpaca_order_symbol(), gate_quant_ensemble(), gate_risk_atr(), gate_technical_liquidity(), is_tradable(), risk_committee(), submit_notional_buy(), to_alpaca_symbol()

### Community 48 - "Piano di riorganizzazione del bot"
Cohesion: 0.11
Nodes (17): 1. In breve, 2. Criticità trovate, 3. Strategie: cosa dicono gli studi, 3a. Metà "trading" (giorni-settimane): trend e momentum, 3b. Metà "day trading" (dentro la giornata, tutto chiuso entro le 15:55 di New York), 4. Divisione 50% / 50%, 5. Nuova organizzazione degli agenti, 6. Riorganizzazione del codice (+9 more)

### Community 49 - "test_swarm_regressions.py"
Cohesion: 0.18
Nodes (5): _ok_gate(), test_idle_scouts_are_not_stalled(), test_refresh_held_evaluations_passes_real_exposure(), test_risk_committee_approves_when_vwap_is_unknown(), test_scout_timeout_ignores_waiting_in_queue()

### Community 52 - "build_desk_cio_prompt"
Cohesion: 0.25
Nodes (5): _long_pitch(), test_cio_prompt_accepts_unknown_vwap(), test_cio_prompt_fits_groq_free_tier_with_many_pitches(), build_desk_cio_prompt(), estimate_tokens()

### Community 54 - "apply_trend_rank"
Cohesion: 0.33
Nodes (4): test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), apply_trend_rank(), trend_score()

### Community 55 - "segment_matches"
Cohesion: 0.40
Nodes (3): sector_of(), _segment_impact(), segment_matches()

### Community 56 - "log_message"
Cohesion: 0.17
Nodes (9): background_loop(), chop_loop(), ensure_background_threads(), guardian_loop(), keep_alive_loop(), keep_alive_url(), log_message(), should_abort() (+1 more)

### Community 65 - "app.py"
Cohesion: 0.24
Nodes (4): is_logged_in(), login(), login_blocked_for(), register_failed_login()

### Community 67 - "api_agent_brain"
Cohesion: 0.22
Nodes (8): _agent_feeds(), api_agent_brain(), api_agents(), agents_snapshot(), _clean(), logs(), thoughts_for(), dialogue_since()

### Community 68 - "api_position_close"
Cohesion: 0.33
Nodes (4): api_liquidate(), api_position_close(), record_sell(), close_position()

### Community 69 - "build_scout_payload"
Cohesion: 0.33
Nodes (3): build_scout_payload(), looks_crypto(), normalize_ohlcv()

### Community 70 - "write_json_file"
Cohesion: 0.40
Nodes (3): save_state(), sync_ledger(), write_json_file()

## Knowledge Gaps
- **29 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `MacroSentimentAgent`, `trading_core.py`, `quant_engine`, `quant_core.py`, `MicrostructureAgent`, `PortfolioGuardianAgent`, `ChopWatchdog`, `consumer`, `ScoutSwarm`, `Any`, `CIOStrategistAgent`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_trading_cycle()` (e.g. with `api_trigger()` and `Organizzazione del codice`) actually correct?**
  _`run_trading_cycle()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `route` be split into smaller, more focused modules?**
  _Cohesion score 0.11857707509881422 - nodes in this community are weakly interconnected._
- **Why does `MacroSentimentAgent` connect `MacroSentimentAgent` to `QuantitativeTradingCore`, `Any`, `portfolio_allocator.py`, `quant_core.py`, `CIOStrategistAgent`, `risk_limits`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_scout_swarm()` (e.g. with `Organizzazione del codice` and `run_one()`) actually correct?**
  _`run_scout_swarm()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.08194905869324474 - nodes in this community are weakly interconnected._
- **Why does `ChopWatchdog` connect `ChopWatchdog` to `QuantitativeTradingCore`, `Any`, `quant_core.py`, `test_swarm_regressions.py`, `.guarded_llm_call`, `CIOStrategistAgent`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._