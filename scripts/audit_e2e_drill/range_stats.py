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
    kept = {
        v for v in values
        if not (isinstance(v, float) and math.isnan(v)) and lo <= v <= hi
    }
    return sorted(kept)
