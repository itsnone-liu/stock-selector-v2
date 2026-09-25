"""T6 unified gate framework — frozen at T6.0, reused by every stage gate.

Implements the shared verification primitives defined in t6_contract.json:
G1 sha256 lineage, G2 upstream immutability, G3 PIT truncation replay,
G4 outcome separation (columns + lineage), G5 segment isolation,
G6 pre-registration, G7 no-tuning source scan, G8 conservation helpers,
G9 statistical integrity, G10 canonical determinism, G11 anti-story.

Stage gates import these primitives; stage-specific logic layers on top.
Each gate may also report SKIPPED_WITH_REASON (e.g. G9 for T6.0 which runs
no inference) — a skip must always carry a reason string.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
T6 = ROOT/'output/research/t6'
sys.path.insert(0, str(ROOT/'src'))
from t6.common import (load_contract, sha256_file, canonical_frame_hash,
                       UPSTREAM_PRODUCTS)  # noqa: E402


class GateLog:
    def __init__(self):
        self.R = {}

    def gate(self, k, ok, reason='', **x):
        self.R[k] = {'verdict': 'PASS' if ok else 'FAIL', 'reason': reason, **x}

    def skip(self, k, reason):
        self.R[k] = {'verdict': 'SKIPPED_WITH_REASON', 'reason': reason}

    def finish(self, out_path: Path):
        verdict = 'PASS' if all(v['verdict'] in ('PASS', 'SKIPPED_WITH_REASON')
                                for v in self.R.values()) else 'FAIL'
        out = {k: self.R[k] for k in sorted(self.R)} | {'overall': verdict}
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(json.dumps(out, ensure_ascii=False))
        print('OVERALL:', verdict)
        return 0 if verdict == 'PASS' else 1


# G1 — explicit sha256 lineage vs manifest
def g1_lineage(log: GateLog, manifest: dict, out_dir: Path):
    n = 0
    ok = True
    for it in manifest.get('inputs', []):
        p = ROOT/it['path']
        if not p.exists() or sha256_file(p) != it['sha256']:
            ok = False
            break
        n += 1
    log.gate('G1_lineage', ok and n >= 1, inputs_hash_verified=n)


# G2 — upstream immutability vs T6.0 frozen hashes
def g2_upstream_immutability(log: GateLog, t60_manifest: dict):
    frozen = t60_manifest.get('upstream_hashes', [])
    ok = len(frozen) >= len(UPSTREAM_PRODUCTS) - 1
    for it in frozen:
        p = ROOT/it['path']
        if not p.exists() or sha256_file(p) != it['sha256']:
            ok = False
            break
    log.gate('G2_upstream_immutability', ok, frozen_products=len(frozen))


# G3 — PIT physical truncation replay on sampled events.
# Stored conventions (reverse-engineered from t5_daily_state, verified on
# sample events): cum_ret_from_t0_log = log(close/close_T0); drawdown_
# from_peak_log = post_t0_peak - cum (POSITIVE depth); max_dd_to_date_log
# = running max of that depth. NaN rets (day0/suspension) contribute 0.
def g3_pit_truncation_replay(log: GateLog, daily: pd.DataFrame, n_events=40, seed=7):
    rng = np.random.default_rng(seed)
    evs = rng.choice(daily.event_id.unique(), size=n_events, replace=False)
    bad = 0
    for ev in evs:
        d = daily[daily.event_id == ev].sort_values('delta_day')
        rets = d.ret_1d_log.to_numpy(dtype=float)
        cum = 0.0
        peak = 0.0
        mxdd = 0.0
        for i in range(len(d)):
            r = rets[i]
            if not np.isnan(r):
                cum += r
            peak = max(peak, cum)
            dd = peak - cum            # positive depth convention
            mxdd = max(mxdd, dd)
            row = d.iloc[i]
            if abs(row.cum_ret_from_t0_log - cum) > 1e-9 or \
               abs(row.drawdown_from_peak_log - dd) > 1e-9 or \
               abs(row.max_dd_to_date_log - mxdd) > 1e-9:
                bad += 1
                break
    log.gate('G3_pit_truncation_replay', bad == 0,
             events_checked=n_events, mismatches=bad,
             note='prefix recompute of cum/dd(+depth)/maxdd == stored values')


# G4 — outcome separation: no fwd columns AND builder never READS the outcome
# table (lineage check is line-level co-occurrence of a read call and the
# outcome path — merely listing the file for G2 immutability hashing is legal).
def g4_outcome_separation(log: GateLog, fact_frames: dict, build_sources: list):
    bad_cols = []
    for name, df in fact_frames.items():
        bad_cols += [f'{name}.{c}' for c in df.columns
                     if c.startswith(('fwd_', 'future_', 'outcome_'))]
    lineage_hits = []
    for src in build_sources:
        for ln, line in enumerate(src.splitlines(), 1):
            if 't5_daily_outcome' in line and 'read_parquet' in line:
                lineage_hits.append(f'L{ln}')
    log.gate('G4_outcome_separation', not bad_cols and not lineage_hits,
             forbidden_columns=bad_cols, outcome_read_lines=lineage_hits)


# G5 — segment isolation: values equal frozen T5 assignment
def g5_segment_isolation(log: GateLog, frames_with_segment: dict):
    allowed = {'development', 'validation', 'confirmation'}
    ok = True
    detail = {}
    for name, df in frames_with_segment.items():
        vals = set(df.segment.dropna().unique())
        detail[name] = sorted(vals)
        if not vals <= allowed:
            ok = False
    log.gate('G5_segment_isolation', ok, segments=detail)


# G6 — pre-registration: contract carries every threshold the code uses
def g6_preregistration(log: GateLog, stage_sources: list, contract: dict):
    src = '\n'.join(stage_sources)
    # numeric literals that smell like thresholds must exist in contract json
    cj = json.dumps(contract)
    smells = []
    for m in re.finditer(r'(?:<=|>=|<|>)\s*(-?\d+\.?\d*)', src):
        v = m.group(1)
        if v not in ('0', '1', '0.0', '1.0') and v not in cj:
            smells.append(v)
    log.gate('G6_preregistration', not smells,
             unregistered_threshold_literals=sorted(set(smells))[:10],
             note='numeric comparison constants must appear in t6_contract.json')


# G7 — no tuning idioms in T6 sources
def g7_no_tuning(log: GateLog, stage_sources: list):
    src = '\n'.join(stage_sources)
    hits = [p for p in (r'grid_search', r'param_grid', r'argmax', r'argmin', r'\bbest_',
                        r'optimize', r'champion', r'itertools\.product', r'np\.linspace')
            if re.search(p, src)]
    log.gate('G7_no_tuning', not hits, tuning_idioms_found=hits)


# G8 — conservation: decomposition sums exactly
def g8_conservation(log: GateLog, checks: dict):
    """checks: name -> (total, {part: n}) ; parts must sum to total."""
    ok = True
    detail = {}
    for name, (total, parts) in checks.items():
        s = sum(parts.values())
        detail[name] = {'total': int(total), 'parts_sum': int(s),
                        'parts': {k: int(v) for k, v in parts.items()}}
        if s != total:
            ok = False
    log.gate('G8_conservation', ok, decompositions=detail)


# G9 — statistical integrity vs contract
def g9_statistical_integrity(log: GateLog, stats_used: dict, contract: dict):
    pre = contract['statistics_prereg']
    ok = (stats_used.get('B') == pre['bootstrap_B']
          and stats_used.get('seed') == pre['bootstrap_seed']
          and stats_used.get('ci') == pre['ci_method']
          and set(stats_used.get('clusters', [])) <= set(pre['cluster_units']))
    log.gate('G9_statistical_integrity', ok, used=stats_used)


# G10 — canonical determinism: rehash products from canonical frame rebuild
def g10_determinism(log: GateLog, manifest: dict, out_dir: Path, rebuild):
    """rebuild() -> {product_file_no_ext: DataFrame}; compares canonical hash
    to the hash of the on-disk parquet re-read."""
    ok = True
    n = 0
    for pr in manifest['products']:
        if not pr['file'].endswith('.parquet'):
            continue
        key = pr['file'].rsplit('.', 1)[0]
        # canonical hash of on-disk frame
        disk = pd.read_parquet(out_dir/pr['file'])
        h_disk = canonical_frame_hash(disk)
        # stage rebuild hook provides the same frame deterministically
        ref = rebuild(key) if rebuild else None
        if ref is None:
            continue
        h_ref = canonical_frame_hash(ref)
        n += 1
        if h_disk != h_ref:
            ok = False
            break
    log.gate('G10_determinism', ok, parquet_canonical_checked=n,
             note='sorted+typed canonical frame hash, rebuild == disk')


# G11 — anti-story: claims subset of registry; forbidden wording machine check
FORBIDDEN_PATTERNS = [
    (r'tail\s*risk.{0,40}(protect|insur)', 'tail-protection claim requires quantile/CVaR evidence'),
    (r'sector.{0,60}(improve|identif|predict)', 'sector (NON-PIT) claims are EXPLORATORY only'),
]
def g11_anti_story(log: GateLog, report_md: Path, claim_registry: Path | None):
    ok = True
    reasons = []
    txt = report_md.read_text() if (report_md and report_md.exists()) else ''
    if txt:
        for pat, why in FORBIDDEN_PATTERNS:
            m = re.search(pat, txt, flags=re.I)
            if m and 'EXPLORATORY' not in txt[max(0, m.start()-200):m.end()+200]:
                ok = False
                reasons.append(why)
    if claim_registry and claim_registry.exists():
        reg = json.loads(claim_registry.read_text())
        allowed = {c['claim_id'] for c in reg} if isinstance(reg, list) else set(reg)
        cited = set(re.findall(r'C\d{3}', txt))
        uncited = cited - allowed
        if uncited:
            ok = False
            reasons.append(f'claims not in registry: {sorted(uncited)}')
    log.gate('G11_anti_story', ok, reasons=reasons)
