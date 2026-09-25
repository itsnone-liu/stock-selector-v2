"""T6 shared statistics — extracted from the T6.1 implementation (frozen) and
generalized: two-group cluster bootstrap over arbitrary boolean masks, with
SeedSequence-derived deterministic substreams (standalone replayable for G10).

All statistics resolve B / seed / cluster units from t6_contract.json at
call time. Holm within caller-defined families.
"""
from __future__ import annotations
import zlib
import numpy as np


def wq(sorted_v: np.ndarray, w: np.ndarray, q: float) -> float:
    """Weighted quantile == percentile of the repeat-expanded sample."""
    if len(sorted_v) == 0:
        return float('nan')
    cw = np.cumsum(w)
    pos = q * cw[-1]
    i = int(np.searchsorted(cw, pos, side='left'))
    i = min(i, len(sorted_v) - 1)
    if i == 0:
        return float(sorted_v[0])
    c0, c1 = cw[i - 1], cw[i]
    if c1 == c0:
        return float(sorted_v[i])
    frac = (pos - c0) / (c1 - c0)
    return float(sorted_v[i - 1] * (1 - frac) + sorted_v[i] * frac)


def wmedian(sorted_v: np.ndarray, w: np.ndarray) -> float:
    return wq(sorted_v, w, 0.50)


def wmean(sorted_v: np.ndarray, w: np.ndarray) -> float:
    if len(sorted_v) == 0:
        return float('nan')
    return float(np.nansum(w * sorted_v) / np.nansum(w))


def wpct(sorted_v: np.ndarray, w: np.ndarray, q: float) -> float:
    return wq(sorted_v, w, q)


STATS = {'median': wmedian, 'mean': wmean,
         'p05': lambda v, w: wpct(v, w, 0.05), 'p25': lambda v, w: wpct(v, w, 0.25),
         'p90': lambda v, w: wpct(v, w, 0.90), 'p95': lambda v, w: wpct(v, w, 0.95)}


def _prep(vals: np.ndarray, mask: np.ndarray, clusters: np.ndarray):
    v = vals[mask]
    ok = ~np.isnan(v)
    v, cl = v[ok], clusters[mask][ok]
    order = np.argsort(v, kind='mergesort')
    uq, inv = np.unique(cl[order], return_inverse=True)
    return v[order], inv, len(uq)


def make_rng_factory(seed: int, enums: list):
    """Deterministic SeedSequence substreams: rng(*keys) with keys drawn from
    the frozen enumeration lists (stage-level replayability for G10)."""
    def rng(*keys):
        entropy = [seed] + [enums[i].index(k) if isinstance(k, str) and k in enums[i]
                            else (k if isinstance(k, int) else zlib.crc32(str(k).encode()) % (2**31))
                            for i, k in enumerate(keys)]
        return np.random.default_rng(np.random.SeedSequence(entropy))
    return rng


def cluster_boot_diff(vals: np.ndarray, mask_hi: np.ndarray, mask_lo: np.ndarray,
                      clusters: np.ndarray, stat: str, rng, B: int):
    """Two-sided cluster bootstrap of stat(group_hi) - stat(group_lo).
    Weighted-repeat implementation (numerically equivalent to physical
    cluster resampling; see T6.1 frozen implementation)."""
    fn = STATS[stat]
    ph = _prep(vals, mask_hi, clusters)
    pl = _prep(vals, mask_lo, clusters)
    C = max(ph[2], pl[2])
    est = fn(ph[0], np.ones(len(ph[0]))) - fn(pl[0], np.ones(len(pl[0])))
    diffs = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, C, C)
        d = 0.0
        for (v, inv, Cu), sign in ((ph, 1), (pl, -1)):
            m_d = np.bincount(pick, minlength=C)[:Cu]
            d += sign * fn(v, m_d[inv])
        diffs[b] = d
    # R1 (audit): an empty group or all-invalid replicates means the test is
    # NOT PERFORMED — propagate NaN to diff/CI/p together. p=0 would wrongly
    # mean 'maximally significant'.
    valid = np.isfinite(diffs)
    diag = {'n_boot_valid': int(valid.sum()), 'n_hi': int(len(ph[0])), 'n_lo': int(len(pl[0]))}
    if valid.sum() == 0:
        return float('nan'), (float('nan'), float('nan')), float('nan'), diag
    d = diffs[valid]
    ci = (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)))
    p = 2 * min(float(np.mean(d <= 0)), float(np.mean(d >= 0)))
    return est, ci, float(min(p, 1.0)), diag


def cluster_boot_level(vals: np.ndarray, mask: np.ndarray, clusters: np.ndarray,
                       stat: str, rng, B: int):
    """One-group cluster bootstrap CI of stat(group) (level, not diff)."""
    fn = STATS[stat]
    v, inv, C = _prep(vals, mask, clusters)
    Cu = inv.max() + 1 if len(inv) else 0
    est = fn(v, np.ones(len(v)))
    out = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, C, C)
        m_d = np.bincount(pick, minlength=C)[:Cu]
        out[b] = fn(v, m_d[inv])
    ci = (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))
    return est, ci


def holm(pvals: dict) -> dict:
    # NaN p (not-tested cells: empty groups) are excluded from correction and
    # returned as NaN so they can never appear as 'significant'.
    finite = {k: v for k, v in pvals.items() if np.isfinite(v)}
    adj = holm._core(finite) if hasattr(holm, '_core') else None
    if adj is None:
        adj = _holm_core(finite)
    for k, v in pvals.items():
        if not np.isfinite(v):
            adj[k] = float('nan')
    return adj


def _holm_core(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        a = min(1.0, (m - i) * p)
        running = max(running, a)
        adj[k] = running
    return adj
