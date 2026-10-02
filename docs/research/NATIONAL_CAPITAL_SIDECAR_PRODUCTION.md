# National-capital sidecar production input

This document describes the tracked code and ignored runtime data for the CSR-8 national-capital extension.

## Scope

The current prepared dataset covers the 84 frozen CSR case stocks and 22 quarter-end report periods from 2021-03-31 through 2026-06-30. Full 5,240-stock expansion is intentionally deferred.

Runtime outputs are ignored by Git and must be regenerated from the collectors:

```text
scripts/collect_national_capital_history.py
scripts/collect_publication_dates.py
scripts/normalize_national_capital_history.py
scripts/join_publication_dates.py
scripts/collect_etf_share_history.py
scripts/audit_national_capital_coverage.py
scripts/production_readiness_check.py
```

The deterministic actor registry is tracked at:

```text
config/csr/national_actor_registry_v1.json
```

## Production inputs

After collection and checks, the sidecar inputs are:

```text
output/research/csr/national_capital/national_holdings_pit.csv
output/research/csr/national_capital/etf_share_daily_sse.csv
```

These are generated files under ignored `data/` and `output/research/` trees. The raw layer stores request parameters, final URLs, response bytes, retrieval timestamps, outcome, and SHA256 metadata.

## PIT rules

- `report_period` is never used as `available_date`.
- Holding publication dates are joined from captured financial-report metadata.
- `available_date` is conservatively the next frozen exchange trading day.
- ETF share `available_date` follows the same conservative next-trading-day rule.
- ETF share expansion/contraction is a background proxy and is never attributed to a named national-capital actor.
- Empty or incomplete tables remain `UNKNOWN`/source-empty; they are not converted to absence evidence.

## Current readiness and manual review

`production_readiness_report.json` is the machine-readable gate. The prepared sidecar is suitable as an input to a later context builder, not as permission to rewrite frozen packets or Phase H artifacts.

Manual review remains required for:

1. 50 explicit empty historical shareholder responses;
2. spot checks of publication dates against issuer/exchange announcements;
3. residual unmatched actor names;
4. historical SZSE ETF share archive or an approved paid source.

Do not commit the generated raw/CSV data unless a separate data-release policy explicitly requires it.
