# Graph Report - bot-trading  (2026-11-14)

## Corpus Check
- 35 files · ~71,469 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: (none) 2, .css 1)

## Summary
- 1078 nodes · 2351 edges · 67 communities (47 shown, 20 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 74 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `bdb41160`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- run_trading_cycle
- MacroSentimentAgent
- trading_core.py
- run_scout_swarm
- app.py
- coo_agent.py
- now_local
- PitchAuditRegister
- DynamicUniverseScreener
- log_message
- HyperQuantAgent
- InstitutionalRiskAgent
- guardian_evaluate
- risk_committee
- MicrostructureAgent
- CIOStrategistAgent
- PortfolioGuardianAgent
- ChopWatchdog
- detectors.py
- micro_scout
- numpy
- snapshot_state
- ScoutSwarm
- require_login
- pitch_audit
- Any
- ask_desk_cio
- _gstate_read
- read_json_file
- risk_limits
- test_portfolio_allocator.py
- start_background_threads
- core_allocation.py
- os
- command_center.py
- QuantitativeTradingCore
- get_config
- chat
- update_config
- _decide
- pipeline_diagnosis
- buy_budget
- package.json
- .process_scout_stream
- describe_command
- core_satellite.py
- drawdown_scale
- env_overrides
- initial_capital
- _build_logger
- build_scout_payload
- agent_07_chop.py
- apply_trend_rank
- swarm_baskets
- segment_matches
- daily_index
- _cancel_open_orders
- git_sync_status.sh
- fix_and_run.sh
- start_background.sh
- stop_background.sh
- pitch_conviction

## God Nodes (most connected - your core abstractions)
1. `run_trading_cycle()` - 50 edges
2. `normalize_symbol()` - 44 edges
3. `run_scout_swarm()` - 32 edges
4. `log_message()` - 30 edges
5. `QuantitativeTradingCore` - 29 edges
6. `now_local()` - 26 edges
7. `get_config()` - 26 edges
8. `is_crypto()` - 24 edges
9. `MacroSentimentAgent` - 21 edges
10. `agent_say()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `QuantitativeTradingCore` --uses--> `MicrostructureAgent`  [INFERRED]
  quant_core.py → agents/agent_02_micro.py
- `QuantitativeTradingCore` --uses--> `NewsRadar`  [INFERRED]
  quant_core.py → agents/agent_04_macro.py
- `QuantitativeTradingCore` --uses--> `MacroSentimentAgent`  [INFERRED]
  quant_core.py → agents/agent_04_macro.py
- `test_missing_news_is_not_a_veto()` --uses--> `MacroSentimentAgent`  [INFERRED]
  tests/test_portfolio_allocator.py → agents/agent_04_macro.py
- `QuantitativeTradingCore` --uses--> `CIOStrategistAgent`  [INFERRED]
  quant_core.py → agents/agent_05_cio.py

## Import Cycles
- None detected.

## Communities (67 total, 20 thin omitted)

### Community 0 - "run_trading_cycle"
Cohesion: 0.06
Nodes (27): bot_account(), core_spy_pct(), deploy_liquidity(), describe_decision(), execute_buy(), execute_sell(), fetch_bot_positions(), guardian_tick() (+19 more)

### Community 1 - "MacroSentimentAgent"
Cohesion: 0.08
Nodes (6): build_news_prompt(), _epoch(), MacroSentimentAgent, NewsRadar, parse_news_assessment(), test_negative_news_stays_a_veto()

### Community 2 - "trading_core.py"
Cohesion: 0.05
Nodes (13): cio_inbox(), dialogue_head(), get_dashboard_password(), get_secret_key(), mark_user_seen(), _prune_cache(), prune_runtime_caches(), release_memory() (+5 more)

### Community 3 - "run_scout_swarm"
Cohesion: 0.09
Nodes (21): _audit_safe(), _close(), crypto_fear_greed(), crypto_order_books(), _daily_frames(), _download(), is_crypto(), is_us_market_open() (+13 more)

### Community 4 - "app.py"
Cohesion: 0.09
Nodes (23): account_with_pnl(), api_chat(), api_data(), api_position_detail(), api_toggle(), cached(), _chat_context(), _find_position() (+15 more)

### Community 5 - "coo_agent.py"
Cohesion: 0.11
Nodes (6): _clip(), COOAgent, _public_url(), _retry_after(), _strip_html(), WebResearch

### Community 6 - "now_local"
Cohesion: 0.08
Nodes (18): test_trend_features_ignore_illiquid_and_todays_bar(), atr_pct(), completed_daily_close(), dynamic_stop_pct(), _ema(), get_daily_bars(), guardian_atr(), guardian_atr_info() (+10 more)

### Community 7 - "PitchAuditRegister"
Cohesion: 0.13
Nodes (5): _key(), _num(), PitchAuditRegister, bucket(), _rate()

### Community 8 - "DynamicUniverseScreener"
Cohesion: 0.10
Nodes (3): DynamicUniverseScreener, _TimeoutAdapter, with_http_timeout()

### Community 9 - "log_message"
Cohesion: 0.15
Nodes (14): api_agent_control(), api_blocks(), api_liquidate(), api_position_close(), api_position_de_risk(), api_settings_post(), api_trigger(), fetch_open_positions() (+6 more)

### Community 11 - "HyperQuantAgent"
Cohesion: 0.14
Nodes (3): HyperQuantAgent, neg_log_likelihood(), variance_path()

### Community 13 - "guardian_evaluate"
Cohesion: 0.09
Nodes (12): news(), chop_audit(), earnings_within(), events_for_agents(), guardian_evaluate(), guardian_peak(), guardian_signals(), _ofi_exit_signal() (+4 more)

### Community 14 - "risk_committee"
Cohesion: 0.09
Nodes (12): alpaca_order_symbol(), _finnhub_headlines(), gate_quant_ensemble(), gate_risk_atr(), gate_sentiment_compliance(), gate_technical_liquidity(), get_recent_news(), is_tradable() (+4 more)

### Community 16 - "CIOStrategistAgent"
Cohesion: 0.13
Nodes (5): build_buy_thesis(), CIOStrategistAgent, ofi_to_score(), test_full_portfolio_is_not_a_veto_so_no_cooldown(), test_trade_is_possible_without_news()

### Community 17 - "PortfolioGuardianAgent"
Cohesion: 0.13
Nodes (5): PortfolioGuardianAgent, _usd(), test_guardian_moves_stop_to_breakeven_after_one_r(), test_guardian_trend_break_exit(), test_small_vix_rise_is_not_a_news_shock()

### Community 19 - "detectors.py"
Cohesion: 0.20
Nodes (9): _atr(), breakout(), hurst_exponent(), mean_reversion(), orderbook(), _signal(), volatility(), volume() (+1 more)

### Community 20 - "micro_scout"
Cohesion: 0.10
Nodes (11): beta_correlation(), classify_score(), completed_bars(), compute_indicators(), get_indicators(), indicators_on_closed_bars(), market_analyst(), micro_scout() (+3 more)

### Community 21 - "numpy"
Cohesion: 0.17
Nodes (10): clamp_stop_pct(), hard_stop_pct(), effective_stop(), enter(), entries_allocator(), entries_current(), exits_trend(), load_data() (+2 more)

### Community 22 - "snapshot_state"
Cohesion: 0.13
Nodes (14): agents_snapshot(), block_reason(), blocks_text(), brief_state_text(), build_system_prompt(), _clean(), logs(), diagnosis_lines() (+6 more)

### Community 24 - "require_login"
Cohesion: 0.12
Nodes (13): _agent_feeds(), api_agent_brain(), api_agents(), api_audit(), api_chat_history(), api_history(), api_settings_get(), has_valid_token() (+5 more)

### Community 25 - "pitch_audit"
Cohesion: 0.12
Nodes (13): rejected(), audit_board(), fallback_votes(), _audit_close(), _audit_stages(), _chop_health(), _db(), last_entry_execution() (+5 more)

### Community 26 - "Any"
Cohesion: 0.18
Nodes (4): age_assessment(), conviction_strength(), _fmt(), symbol_key()

### Community 27 - "ask_desk_cio"
Cohesion: 0.13
Nodes (11): ask_desk_cio(), _ask_gemini(), _ask_groq(), _clean_number(), _clean_score(), groq_news_llm(), _no_ai_keys(), parse_broker_json() (+3 more)

### Community 28 - "_gstate_read"
Cohesion: 0.14
Nodes (9): _fallback_thesis(), _gstate_read(), _gstate_write(), guardian_position_state(), guardian_prune(), guardian_record_exit(), guardian_register_entry(), summarize_reason() (+1 more)

### Community 29 - "read_json_file"
Cohesion: 0.12
Nodes (10): current_drawdown(), drawdown_controller(), _intraday_equity_peak(), load_state(), read_json_file(), _registry_data(), _review_context(), save_state() (+2 more)

### Community 30 - "risk_limits"
Cohesion: 0.14
Nodes (9): conviction_factor(), risk_limits(), size_trade(), stop_pct(), test_crypto_cap(), test_limits_shrink_with_regime_and_never_use_margin(), test_more_volatile_titles_get_less_capital(), test_size_never_exceeds_cap_or_cash_floor() (+1 more)

### Community 31 - "test_portfolio_allocator.py"
Cohesion: 0.13
Nodes (10): open_risk_usd(), trend_up_confirmed(), desk(), test_core_position_is_invisible_to_guardian_and_radar(), test_cycle_reinvests_idle_cash_even_with_ai_on_hold(), test_cycle_with_core_buys_spy_and_keeps_the_bot_in_its_sleeve(), test_liquidity_wakes_the_cio(), test_one_close_below_ema100_does_not_flip_the_regime() (+2 more)

### Community 32 - "start_background_threads"
Cohesion: 0.13
Nodes (8): background_loop(), chop_loop(), ensure_background_threads(), guardian_loop(), keep_alive_loop(), keep_alive_url(), start_background_threads(), startup_system_sync()

### Community 33 - "core_allocation.py"
Cohesion: 0.19
Nodes (7): is_core(), rebalance(), satellite_account(), split_positions(), target_value(), test_core_rebalances_only_outside_the_band(), test_satellite_account_hides_the_core_cash()

### Community 35 - "command_center.py"
Cohesion: 0.23
Nodes (9): _agent(), chat_history(), _coo_tools(), _fn(), _groq_client(), _llm_chat(), pending_proposal(), _ticker_detail() (+1 more)

### Community 36 - "QuantitativeTradingCore"
Cohesion: 0.22
Nodes (4): dummy_ohlcv(), main(), QuantitativeTradingCore, test_pipeline_buys_a_trending_stock_without_news()

### Community 37 - "get_config"
Cohesion: 0.38
Nodes (12): account(), buy(), holding(), pitch(), test_ai_cannot_choose_the_size(), test_bot_never_buys_the_core_symbol(), test_exhausted_risk_budget_holds(), test_panic_regime_blocks_and_crypto_needs_btc_trend() (+4 more)

### Community 38 - "chat"
Cohesion: 0.18
Nodes (7): _apply(), chat(), fallback_reply(), local_reply(), _precheck(), _propose(), _push()

### Community 39 - "update_config"
Cohesion: 0.22
Nodes (6): _load_config(), _read_config_file(), repo_defaults(), _save_config(), update_config(), _validate_config()

### Community 40 - "_decide"
Cohesion: 0.24
Nodes (9): clear_blocks(), _decide(), _default_state(), is_paused(), _load(), _save(), set_agent(), set_block() (+1 more)

### Community 41 - "pipeline_diagnosis"
Cohesion: 0.17
Nodes (6): _ago(), latest_channels(), pipeline_diagnosis(), radar_snapshot(), _reason_key(), _registry_view()

### Community 42 - "buy_budget"
Cohesion: 0.20
Nodes (6): allocation_pct_for_score(), available_funds(), build_desk_cio_prompt(), buy_budget(), max_exposure_pct(), risk_manager()

### Community 43 - "package.json"
Cohesion: 0.29
Nodes (9): dependencies, clsx@^2.1.1, framer-motion@^14.0.0, lightweight-charts@^5.2.1, lucide@^1.52.0, clsx, framer-motion, lightweight-charts (+1 more)

### Community 45 - "describe_command"
Cohesion: 0.22
Nodes (6): propose(), describe_command(), normalize_command(), parse_command(), _rule_parse(), _segment_label()

### Community 46 - "core_satellite.py"
Cohesion: 0.25
Nodes (3): core_returns(), mix(), stats()

### Community 47 - "drawdown_scale"
Cohesion: 0.25
Nodes (5): drawdown_scale(), regime_scale(), test_drawdown_scale(), test_missing_news_is_not_a_veto(), test_regime_scale()

### Community 48 - "env_overrides"
Cohesion: 0.25
Nodes (5): settings(), config_sources(), env_overrides(), _parse_env_value(), public_config()

### Community 49 - "initial_capital"
Cohesion: 0.25
Nodes (4): account_balance_for_agents(), equity_drawdown_pct(), initial_capital(), pnl_summary()

### Community 51 - "build_scout_payload"
Cohesion: 0.33
Nodes (3): build_scout_payload(), looks_crypto(), normalize_ohlcv()

### Community 53 - "apply_trend_rank"
Cohesion: 0.33
Nodes (4): test_rank_is_computed_on_the_universe(), test_score_outside_trend_never_enters(), apply_trend_rank(), trend_score()

### Community 54 - "swarm_baskets"
Cohesion: 0.33
Nodes (3): desk_universe(), dynamic_volume_spikes(), swarm_baskets()

### Community 55 - "segment_matches"
Cohesion: 0.40
Nodes (3): sector_of(), _segment_impact(), segment_matches()

## Knowledge Gaps
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `QuantitativeTradingCore` connect `QuantitativeTradingCore` to `MacroSentimentAgent`, `trading_core.py`, `quant_core.py`, `.process_scout_stream`, `guardian_evaluate`, `MicrostructureAgent`, `CIOStrategistAgent`, `PortfolioGuardianAgent`, `ChopWatchdog`, `ScoutSwarm`, `Any`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `log_message()` (e.g. with `api_position_de_risk()` and `background_loop()`) actually correct?**
  _`log_message()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `run_trading_cycle` be split into smaller, more focused modules?**
  _Cohesion score 0.06274509803921569 - nodes in this community are weakly interconnected._
- **Why does `ChopWatchdog` connect `ChopWatchdog` to `CIOStrategistAgent`, `quant_core.py`, `agent_07_chop.py`, `QuantitativeTradingCore`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `QuantitativeTradingCore` (e.g. with `MicrostructureAgent` and `MacroSentimentAgent`) actually correct?**
  _`QuantitativeTradingCore` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `MacroSentimentAgent` be split into smaller, more focused modules?**
  _Cohesion score 0.07777777777777778 - nodes in this community are weakly interconnected._
- **Why does `HyperQuantAgent` connect `HyperQuantAgent` to `quant_core.py`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._