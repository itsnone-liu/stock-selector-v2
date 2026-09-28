# T2 Rule & Data Semantics Audit Evidence (Run audit_20260928055411432)

- Task: stock-selector-v2 formal audit, frozen task packet hash 3ed7f3bc098d
- Run: audit_20260928055411432 (stage T2, iteration 1)
- Date: 2026-09-28

## SPEC §1-8 item-by-item verification

- §1 explicit asof / completed-vs-current week split: `calendar.current_week_rows` /
  `completed_week_rows` verified for empty input and the Monday boundary
  (completed weeks end at the previous Friday; the current Monday row belongs to the
  current week only).
- §2 data gates: future daily bar → `ERROR future_daily_bar`; realtime stale history →
  `SKIP daily_data_stale`; after-close tolerance is at most 1 business day; quote without
  timestamp → `quote_timestamp_missing`; aged quote → `quote_stale`; zero price →
  `invalid_zero_quote`; zero open or zero volume → `halted_or_preopen_quote`.
- §3 risk filters: B-share (`900`/`200`) excluded, ST/退市 names excluded, short listing
  history rejected, low 20d-median amount rejected when configured.
- §4 monthly trend: <20 bars → skip; MA5>MA10>MA20 ordering enforced; >8% last-month
  drop rejected; bullish ordering passes with the `MA5>MA10>MA20` signal.
- §5 weekly trend: <35 weekly bars → skip; uptrend resolves to one of the three allowed
  signals (ma_bull / macd_cross / macd_stabilizing); accelerating decline →
  `weekly_trend_not_passed`.
- §6 weekly short-term pattern: <5 completed weeks → skip; no current-week rows without a
  quote → skip; bearish week with ≥1.5× turnover vs prior 4-week mean →
  `bearish_heavy_turnover_veto` fires before the current-week check; non-bullish current
  week → `current_week_not_bullish`.
- §7 daily buy points: <60 bars → skip; missing same-time snapshot falls back with
  `volume_method=projected_full_day`; fallback disabled → `same_time_reference_missing`;
  pre-open → `market_not_started`; pullback has priority over two-day acceleration when
  both qualify.
- §8 board mode: `skip_surge` records `board_mode_skips_surge` instead of evaluating the
  surge stage, while freshness, risk filters and the unified daily buy point still run
  (an ST name is still rejected in board mode).

## Boundary coverage added

Empty frames, short history, future data, stale data, zero price/volume/open, Monday and
intraday boundaries, volume units (hands→shares normalization re-verified in
`test_realtime.py`), and the missing-same-time-snapshot fallback are all covered
deterministically with no network access.

## Result

- New suite: `tests/test_spec_semantics_t2.py` (30 tests, all passing).
- No SPEC §1-8 semantic defect found requiring source changes; the gaps were missing
  deterministic boundary tests, which this stage adds.
- Backtest results are not used as evidence of rule correctness anywhere in this suite,
  and scores are treated as ranking only (SPEC §7/§10 semantics).
- No `data/` raw data, credentials, or unrelated projects modified.
