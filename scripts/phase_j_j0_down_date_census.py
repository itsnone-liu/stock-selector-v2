#!/usr/bin/env python3
"""CSR-8 Phase J / J0 — BLIND DOWN-date census (protocol calibration input).

Purely mechanical enumeration from the FROZEN 000985 index series using the
frozen I4A regime rule (120-trading-day median, strictly trade_date < T).
Contains ZERO outcome / ETF / entity information — only calendar structure.
Purpose: calibrate J0 stopping parameters (how many eligible DOWN dates
exist) BEFORE freezing the protocol. Blind by construction.

Eligibility (frozen rules):
  - trade_date is in the frozen 000985 series (a trading day);
  - regime(T) == DOWN under the frozen I4A rule;
  - T not among the 122 discovery observation dates (data isolation);
  - R10 forward window (10 subsequent trading days) fully inside the frozen
    series (outcome computability), i.e. T <= series[-11].
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'docs/phase_i'
SERIES = ROOT / 'docs/phase_i/evidence/market_index_000985.json'
WINDOW = 120


def main():
    norm = json.loads(SERIES.read_bytes())['rows']
    dates = [r['trade_date'] for r in norm]
    closes = [r['close'] for r in norm]
    discovery_Ts = {v['T'] for k, v in json.loads(
        (P / 'i1_structural_atlas.json').read_bytes())['cards'].items()
        if v['ordinal'] >= 7}
    eligible, excluded_discovery, down_not_eligible = [], 0, 0
    for i in range(len(dates)):
        T = dates[i]
        if i + 10 >= len(dates):          # R10 window must fit
            continue
        if i < WINDOW:                    # regime needs 120d history
            continue
        w = closes[i - WINDOW:i]          # strictly before T
        regime = 'UP' if w[-1] > sorted(w)[len(w) // 2] else 'DOWN'
        if regime != 'DOWN':
            continue
        if T in discovery_Ts:
            excluded_discovery += 1
            continue
        eligible.append({'T': T, 'prior_120d_median': sorted(w)[len(w) // 2],
                         'close_prev': w[-1]})
    out = {'phase': 'CSR-8 Phase J / J0 blind DOWN-date census',
           'rule': 'I4A frozen: close(T-1) vs median(close of 120 trading days ending T-1, all < T)',
           'series': {'range': [dates[0], dates[-1]], 'n': len(dates)},
           'r10_window_rule': 'T <= series[-11]',
           'discovery_isolation': 'excluded all 122 discovery observation dates',
           'eligible_down_dates': [e['T'] for e in eligible],
           'n_eligible': len(eligible),
           'n_excluded_because_discovery_date': excluded_discovery}
    (P / 'j0_down_date_census.json').write_text(
        json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    print(json.dumps({'eligible': len(eligible),
                      'first/last': [eligible[0]['T'], eligible[-1]['T']] if eligible else None,
                      'excluded_discovery': excluded_discovery}, ensure_ascii=False))


if __name__ == '__main__':
    main()
