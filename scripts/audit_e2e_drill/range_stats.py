"""A5 audit E2E drill module (frozen task packet aa0eaf122ba0, stage T1)."""

import math


def clamp_range(values, lo, hi):
    """Return the sorted, de-duplicated elements of ``values`` within [lo, hi].

    R2 boundary semantics (frozen requirements):
      a) empty list [] or None input must return [] (never None, never raise);
      b) NaN elements must be excluded;
      c) lo > hi must return [].
    """
    if values is None or len(values) == 0:
        return []
    if lo > hi:
        return []
    kept = set()
    for v in values:
        try:
            if math.isnan(v):
                continue
        except (TypeError, ValueError):
            pass
        if lo <= v <= hi:
            kept.add(v)
    return sorted(kept)
