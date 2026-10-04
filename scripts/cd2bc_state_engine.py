#!/usr/bin/env python3
"""CD-2B base_state x modifier + CD-2C path labels + transition matrix.
Preregistered: docs/cd/cd2b2c_preregistration.json. Deterministic single-pass."""
import json, gzip, hashlib, time
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
BANDS = ROOT/'data'/'cd'/'sector_axes'/'l2_axis_bands.json.gz'
OUT_S = ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz'
OUT_D = ROOT/'docs'/'cd'/'cd2bc_states_run.json'

GRID = {('HIGH','HIGH'):'BROAD_STRENGTH', ('HIGH','MID'):'NARROW_STRENGTH', ('HIGH','LOW'):'NARROW_STRENGTH',
        ('MID','HIGH'):'NEUTRAL_WIDE_UP', ('MID','MID'):'NEUTRAL', ('MID','LOW'):'NEUTRAL_WIDE_DOWN',
        ('LOW','LOW'):'BROAD_WEAKNESS', ('LOW','MID'):'NARROW_WEAKNESS', ('LOW','HIGH'):'NARROW_WEAKNESS'}
NEUTRALISH = ('NEUTRAL','NEUTRAL_WIDE_UP','NEUTRAL_WIDE_DOWN')

def base_of(r):
    base = GRID[(r['rp'], r['breadth'])]
    if r['disp'] == 'HIGH' and r['rp'] in ('MID','HIGH'):
        base = 'DIVERGENT'
    return base

def path_label(w, base):
    """w = 5 consecutive non-null band dicts (T-4..T); base = base state at T."""
    t = w[-1]
    if base == 'BROAD_STRENGTH' and t['part'] == 'EXPANDING':
        prev_bases = [GRID[(x['rp'], x['breadth'])] for x in w[:-1]]
        if any(b != 'BROAD_STRENGTH' for b in prev_bases):
            return 'EXPANSION'
    if (sum(1 for x in w if x['rp'] == 'HIGH') >= 4 and w[0]['breadth'] == 'HIGH'
            and t['breadth'] in ('MID','LOW') and t['conc'] == 'HIGH'
            and base in ('NARROW_STRENGTH','DIVERGENT')):
        return 'NARROWING'
    if base == 'BROAD_WEAKNESS' and t['part'] == 'FALLING':
        return 'FADING'
    if (all(GRID[(x['rp'], x['breadth'])] in NEUTRALISH for x in w[:-1])
            and sum(1 for x in w if x['part'] == 'EXPANDING') >= 3
            and t['breadth'] in ('MID','HIGH') and t['rp'] in ('MID','HIGH')):
        return 'BUILDING'
    return None

def main():
    rec = json.loads(gzip.decompress(BANDS.read_bytes()))
    rows = rec['bands']
    per_sec = defaultdict(list)
    for r in rows: per_sec[r['l2']].append(r)
    states = []
    path_counts = Counter(); trans = Counter()
    combo = Counter(); combo_sec = defaultdict(set); combo_year = defaultdict(set)
    for s in sorted(per_sec):
        rs = sorted(per_sec[s], key=lambda r: r['date'])
        band_seq = []
        sec_states = []
        for r in rs:
            if r.get('state') == 'INSUFFICIENT_SUPPORT':
                sec_states.append({'l2': s, 'date': r['date'], 'state': 'INSUFFICIENT_SUPPORT', 'n': r.get('n', 0)})
                band_seq.append(None)
                continue
            b = {'rp': r['rp'], 'breadth': r['breadth'], 'part': r['part'], 'conc': r['conc'], 'disp': r['disp']}
            band_seq.append(b)
            base = base_of(b)
            mods = []
            if b['part'] == 'EXPANDING': mods.append('PARTICIPATION_EXPANDING')
            if b['part'] == 'FALLING': mods.append('PARTICIPATION_FADING')
            if b['conc'] == 'HIGH': mods.append('HIGH_CONCENTRATION')
            if b['disp'] == 'HIGH': mods.append('HIGH_DISPERSION')
            st = {'l2': s, 'date': r['date'], 'n': r['n'], 'base': base, 'mods': mods}
            sec_states.append(st)
            yr = r['date'][:4]
            combo[(base, tuple(mods))] += 1
            combo_sec[(base, tuple(mods))].add(s)
            combo_year[(base, tuple(mods))].add(yr)
        for i in range(4, len(band_seq)):
            w = band_seq[i-4:i+1]
            if any(x is None for x in w): continue
            lab = path_label(w, sec_states[i]['base'])
            if lab:
                sec_states[i]['path'] = lab
                path_counts[lab] += 1
        prev = None
        for b in band_seq:
            if b is None:
                prev = None; continue
            cur = base_of(b)
            if prev is not None:
                trans[(prev, cur)] += 1
            prev = cur
        states.extend(sec_states)
    sha = hashlib.sha256(json.dumps(states, separators=(',',':')).encode()).hexdigest()
    OUT_S.write_bytes(gzip.compress(json.dumps({'n': len(states), 'states': states}, separators=(',',':')).encode(), 6))
    support = {}
    for (b, m), c in sorted(combo.items(), key=lambda kv: -kv[1]):
        support[f"{b}|{'+'.join(m) if m else 'NONE'}"] = {
            'count': c, 'sectors': len(combo_sec[(b,m)]), 'years': sorted(combo_year[(b,m)]),
            'low_support': c < 100 or len(combo_sec[(b,m)]) < 3}
    persistence = {}
    inflow = defaultdict(int); diag = defaultdict(int)
    for (a, b), c in trans.items():
        inflow[b] += c
        if a == b: diag[b] += c
    for b in inflow:
        persistence[b] = round(diag[b]/inflow[b], 4)
    json.dump({'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'state_table_sha256': sha, 'n_rows': len(states),
               'base_counts': dict(Counter(st.get('base', 'INSUFFICIENT_SUPPORT') for st in states)),
               'path_counts': dict(path_counts), 'path_days_total': sum(path_counts.values()),
               'support_census': support,
               'transition_top': {f"{a}->{b}": c for (a, b), c in sorted(trans.items(), key=lambda kv: -kv[1])[:20]},
               'persistence_diag_share_of_inflow': persistence},
              open(OUT_D, 'w'), indent=1)
    print('states=', len(states), 'sha=', sha[:16])
    print('base:', dict(Counter(st.get('base', 'INSUFFICIENT_SUPPORT') for st in states)))
    print('paths:', dict(path_counts))
    print('persistence:', persistence)

if __name__ == '__main__':
    main()
