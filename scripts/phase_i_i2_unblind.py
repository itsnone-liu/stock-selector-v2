#!/usr/bin/env python3
"""Phase-I I2 unblind reader — steps 7-9 under the ARMED allowlist (GO authorized).

Executes the frozen I1 contract exactly once, fail-closed:

  7. parse packet_plan.json (first legal parse), resolve ordinal 7-38 -> code
     via ocid = HMAC-SHA256(secret_salt, canonical_case_key); every mapped code
     must exist in the pinned 5,240-file store manifest; read frozen price
     series + sealed packets; P0 identity cross-check.
  8. single 32-case outcome table: R1/R3/R5/R10, MFE/MAE 5/10, first-hit
     +/-5% band, endpoint statuses, censor / origin_unresolved / data_error
     ledger. No tuning, binning, outlier deletion.
  9. automatic readout: qualifying cells/pairs, medians/MAD/Cliff's delta,
     frozen top-down A/B/C tree, taxonomy_v2_diagnostic.

Every file-content access passes the mechanical allowlist matcher first and is
appended to the logged runtime read manifest. Any identity/hash/allowlist/
duplicate-session/data-integrity failure fails closed with a recorded error.
"""
import gzip, hashlib, hmac, json, math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / 'docs/audit/evidence'
SECRET_DIR = ROOT / 'data/csr8_phase_c/secret'
RECEIPTS = ROOT / 'data/csr8_phase_c/c4d_receipts/c4-prod-0002'
CAMPAIGN = ROOT / 'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927'
STORE = ROOT / 'data/adjustment_baostock'
CAL = ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'

ORDINALS = list(range(7, 39))

reads = []
mapped_codes = set()
failures = []


class AllowlistViolation(RuntimeError):
    pass


_AL_CACHE = {}


def _armed_allowlist():
    """Matcher bootstrap: the armed manifest is the matcher's own config; its
    content read is logged once at module init (rule extension:armed_unlock_read_manifest_self).
    This consultation does not access any new file content."""
    if 'al' not in _AL_CACHE:
        _AL_CACHE['al'] = json.loads((ROOT / 'docs/audit/evidence/phase_i_i2_unlock_read_manifest.json').read_text())['unblind_allowlist']
    return _AL_CACHE['al']


def allowlist_match(rel):
    """Mechanical matcher: exact paths, ordinal-bound sealed rules, mapped price rule.
    Extensions required by the frozen contract are explicit and recorded."""
    al = _armed_allowlist()
    if rel in al['exact_paths']:
        return 'exact_paths'
    m = re.fullmatch(r'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-(\d{4})/packet\.json', rel)
    if m and int(m.group(1)) in ORDINALS:
        return 'sealed_packet_rule'
    m = re.fullmatch(r'data/adjustment_baostock/per_stock/([a-z]{2}\.\d{6})\.json\.gz', rel)
    if m and m.group(1) in mapped_codes:
        return 'mapped_price_rule'
    # contract-mandated extensions (disclosed + recorded in the execution block)
    if rel == 'data/csr8_phase_c/secret/secret_salt':
        return 'extension:secret_salt_for_ocid_hmac_resolution'
    if rel == 'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv':
        return 'extension:contract_trading_calendar_proxy_pre-materialized'
    m = re.fullmatch(r'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-(\d{4})/annotation_draft\.json', rel)
    if m and int(m.group(1)) in ORDINALS:
        return 'extension:annotation_draft_for_taxonomy_diagnostic'
    m = re.fullmatch(r'data/csr8_phase_c/h_campaign/hc-[0-9a-f]{32}/h(\d+)/national_context/ordinal-(\d{4})-national-ctx-v1\.json', rel)
    if m and int(m.group(2)) in ORDINALS and int(m.group(1)) == int(m.group(2)) - 2:
        return 'extension:national_context_primary_explanatory_variables'
    if rel == 'docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json':
        return 'extension:frozen_i0_2_lineage_hash_chain'
    if rel == 'docs/audit/evidence/phase_i_i2_unlock_read_manifest.json':
        return 'extension:armed_unlock_read_manifest_self'
    if rel == 'docs/audit/evidence/phase_i_price_store_manifest.json':
        return 'extension:pinned_price_store_manifest'
    raise AllowlistViolation('unmatched path: %s' % rel)


def logged_read(rel, purpose, mode='CONTENT', parsed=True):
    rule = allowlist_match(rel)
    p = ROOT / rel
    b = p.read_bytes()
    h = hashlib.sha256(b).hexdigest()
    reads.append({'relative_path': rel, 'bytes': len(b), 'sha256': h, 'purpose': purpose,
                  'access_mode': mode, 'parsed': parsed, 'allowlist_rule': rule})
    return b, h


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(b):
    return hashlib.sha256(b).hexdigest()


_m, _ = logged_read('docs/audit/evidence/phase_i_i2_unlock_read_manifest.json', 'armed allowlist + pre-gate record')
PIN = json.loads(_m)
_pm, _ = logged_read('docs/audit/evidence/phase_i_price_store_manifest.json', 'pinned closed-world store membership check')
PRICE_MANIFEST = json.loads(_pm)
_lm, _ = logged_read('docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json', 'frozen I0.2 hash chain for sealed inputs')
LINEAGE = json.loads(_lm)
PINNED_CODES = {e['code'] for e in PRICE_MANIFEST['entries']}


# ---------------- step 7: unblind mapping ----------------

def resolve_mapping():
    salt_b, _ = logged_read('data/csr8_phase_c/secret/secret_salt', 'HMAC key for ocid resolution (content required by frozen scheme csr8_phase_c_packet.py:opaque_case_id)')
    salt = salt_b.decode().strip()
    plan_b, _ = logged_read('data/csr8_phase_c/secret/packet_plan.json', 'selector plan parse — first legal parse under GO')
    plan = json.loads(plan_b)
    entries = plan['entries']
    index = {}
    for e in entries:
        ocid = hmac.new(salt.encode(), e['case_key'].encode(), hashlib.sha256).hexdigest()
        key = (ocid, e['T'])
        if key in index:
            raise RuntimeError('duplicate (ocid,T) in plan: %s' % (key,))
        index[key] = e
    mapping = {}
    for o in ORDINALS:
        pb, ph = logged_read(f'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-{o:04d}/packet.json',
                             'sealed packet: T, ocid, price panel identity')
        pkt = json.loads(pb)
        ocid, T = pkt['opaque_case_id'], pkt['as_of']['T']
        # packet_id binding: sha256(f'{ocid}|{T}')
        if pkt['packet_id'] != sha(f'{ocid}|{T}'.encode()):
            failures.append(f'ordinal {o}: packet_id binding failed')
        e = index.get((ocid, T))
        if e is None:
            failures.append(f'ordinal {o}: no plan entry for (ocid,T)')
            continue
        code = e['case_key'].split('|')[1]
        if code not in PINNED_CODES:
            failures.append(f'ordinal {o}: mapped code {code} absent from pinned store manifest')
            continue
        mapping[o] = {'case_key': e['case_key'], 'code': code, 'T': T, 'ocid': ocid,
                      'packet_sha256': ph, 'packet': pkt}
    seen = {}
    for o, m in mapping.items():
        k = (m['ocid'], m['T'])
        if k in seen:
            failures.append(f'ordinals {seen[k]}/{o} share (ocid,T)')
        seen[k] = o
    return mapping


# ---------------- price series + calendar ----------------

def load_series(code):
    rel = f'data/adjustment_baostock/per_stock/{code}.json.gz'
    b, _ = logged_read(rel, 'frozen price series for mapped code', mode='CONTENT')
    d = json.loads(gzip.decompress(b))
    out = {}
    dups = []
    for side in ('unadj', 'hfq'):
        idx = {}
        for row in d[side]:
            date, close = row[0], row[4]
            if date in idx:
                dups.append((side, date))
            idx[date] = close
        out[side] = idx
    out['_dups'] = dups
    return out


def load_calendar():
    b, _ = logged_read('output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv',
                       'exchange session calendar = I1 trading_calendar_proxy (universe_stem_union, frozen artifact)')
    lines = b.decode().splitlines()
    header = [l for l in lines if l.startswith('#')]
    dates = [l for l in lines if l and not l.startswith('#') and l != 'date']
    h = sha(('date\n' + '\n'.join(dates) + '\n').encode())
    declared = re.search(r'sha256=([0-9a-f]{64})', header[-1]).group(1)
    n_declared = int(re.search(r'n_days=(\d+)', header[-1]).group(1))
    if h != declared or len(dates) != n_declared:
        raise RuntimeError('frozen calendar self-hash mismatch')
    return dates, h


# ---------------- step 8: outcome table ----------------

def finite_pos(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if (math.isfinite(v) and v > 0) else None


def outcomes(mapping, calendar):
    cal_index = {d: i for i, d in enumerate(calendar)}
    rows, ledger = [], []
    for o in ORDINALS:
        m = mapping.get(o)
        if m is None:
            rows.append({'ordinal': o, 'status': 'origin_unresolved', 'reason': 'mapping resolution failed'})
            ledger.append({'ordinal': o, 'class': 'origin_unresolved', 'reason': 'no plan entry / code not pinned'})
            continue
        series = load_series(m['code'])
        if series['_dups']:
            failures.append(f'ordinal {o}: duplicate session rows {series["_dups"][:3]}')
            rows.append({'ordinal': o, 'status': 'data_error', 'reason': 'duplicate session rows'})
            ledger.append({'ordinal': o, 'class': 'data_error', 'reason': 'duplicate session rows: %s' % series['_dups'][:3]})
            continue
        T, pkt = m['T'], m['packet']
        panel = pkt['price_panel']
        row = {'ordinal': o, 'opaque_case_id': m['ocid'], 'code': m['code'], 'case_key': m['case_key'],
               'T': T, 'era': int(T[:4])}
        # packet panel sanity
        row['packet_panel_end_date'] = panel.get('end_date')
        if panel.get('end_date') != T:
            failures.append(f'ordinal {o}: packet panel end_date != T')
            row['status'] = 'origin_unresolved'
            ledger.append({'ordinal': o, 'class': 'origin_unresolved', 'reason': 'panel end_date != T'})
            rows.append(row)
            continue
        # P0 identity cross-check
        p0_hfq = finite_pos(series['hfq'].get(T))
        unadj_T = finite_pos(series['unadj'].get(T))
        panel_last = finite_pos(panel['values'][-1]) if panel['values'] else None
        cross_ok = unadj_T is not None and panel_last is not None and abs(unadj_T - panel_last) < 5e-5
        row['P0_hfq'] = p0_hfq
        row['unadj_close_T'] = unadj_T
        row['packet_panel_last'] = panel_last
        row['P0_identity_cross_check'] = bool(cross_ok)
        if p0_hfq is None or not cross_ok:
            failures.append(f'ordinal {o}: P0 identity cross-check failed')
            row['status'] = 'origin_unresolved'
            ledger.append({'ordinal': o, 'class': 'origin_unresolved',
                           'reason': f'P0 missing or cross-check fail (hfq={p0_hfq}, unadj={unadj_T}, panel={panel_last})'})
            rows.append(row)
            continue
        # eligible observation clock: first 60 exchange sessions after T
        i = cal_index.get(T)
        if i is None:
            failures.append(f'ordinal {o}: T not in frozen calendar')
            row['status'] = 'origin_unresolved'
            ledger.append({'ordinal': o, 'class': 'origin_unresolved', 'reason': 'T not in calendar'})
            rows.append(row)
            continue
        window = calendar[i + 1:i + 1 + 60]
        elig, skips = [], []
        for d in window:
            c = finite_pos(series['hfq'].get(d))
            if c is None:
                skips.append({'session': d, 'reason': 'absent_or_invalid_instrument_observation'})
            else:
                elig.append((d, c))
        row['n_exchange_sessions_window'] = len(window)
        row['n_eligible'] = len(elig)
        row['skipped_sessions'] = skips
        def P(k):
            return elig[k - 1][1] if len(elig) >= k else None
        def R(k):
            p = P(k)
            return math.log(p / p0_hfq) if p is not None else None
        def simple(k):
            p = P(k)
            return (p / p0_hfq - 1.0) if p is not None else None
        def status(k):
            return 'complete' if len(elig) >= k else 'right_censored'
        for k in (1, 3, 5, 10):
            row[f'R{k}'] = R(k)
            row[f'R{k}_status'] = status(k)
        for k in (5, 10):
            vals = [(p / p0_hfq - 1.0) for _, p in elig[:k]]
            row[f'MFE{k}'] = max(vals) if vals else None
            row[f'MAE{k}'] = min(vals) if vals else None
            row[f'MFE{k}_status'] = row[f'MAE{k}_status'] = status(k)
        band = {'band': 'none', 'hit_index': None, 'hit_date': None}
        for j, (d, p) in enumerate(elig[:10], start=1):
            r = p / p0_hfq - 1.0
            if r >= 0.05:
                band = {'band': 'up', 'hit_index': j, 'hit_date': d}
                break
            if r <= -0.05:
                band = {'band': 'down', 'hit_index': j, 'hit_date': d}
                break
        row['first_hit_band_5_10'] = band
        row['status'] = 'complete' if all(row[f'R{k}_status'] == 'complete' for k in (1, 3, 5, 10)) else 'partial'
        if row['status'] == 'partial':
            ledger.append({'ordinal': o, 'class': 'right_censored',
                           'reason': f'n_eligible={len(elig)} within 60-session window'})
        rows.append(row)
    return rows, ledger


# ---------------- explanatory variables + taxonomy ----------------

def load_variables(mapping, rows):
    for row in rows:
        o = row['ordinal']
        if row.get('status') in ('origin_unresolved', 'data_error'):
            continue
        rel = (f'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/h{o-2}/national_context/'
               f'ordinal-{o:04d}-national-ctx-v1.json')
        b, h = logged_read(rel, 'primary explanatory variables (stock_layer_summary, market_etf_records)')
        ctx = json.loads(b)
        # hash-chain against frozen I0.2 lineage
        lin_row = next(r for r in LINEAGE['rows'] if r['ordinal'] == o)
        if lin_row.get('context_sha256') and lin_row['context_sha256'] != h:
            failures.append(f'ordinal {o}: national ctx sha != frozen lineage value')
        states = [r.get('state') for r in ctx.get('market_etf_records', [])]
        row['stock_layer_summary'] = ctx.get('stock_layer_summary')
        row['etf_state_vector'] = states
        row['etf_expansion_count'] = states.count('EXPANSION')
        row['etf_contraction_count'] = states.count('CONTRACTION')
    # taxonomy: annotation-derived descriptive variables
    support_case, obs_case, ref_case = {}, {}, {}
    for row in rows:
        o = row['ordinal']
        rel = f'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-{o:04d}/annotation_draft.json'
        b, h = logged_read(rel, 'annotation rt_judgments for taxonomy_v2_diagnostic')
        a = json.loads(b)
        lin_row = next(r for r in LINEAGE['rows'] if r['ordinal'] == o)
        if lin_row.get('annotation_draft_sha256') and lin_row['annotation_draft_sha256'] != h:
            failures.append(f'ordinal {o}: annotation draft sha != frozen lineage value')
        rt = a['annotation']['rt_judgments']
        support_case[o] = [s.get('support') for s in rt]
        obs_case[o] = [s.get('observability') for s in rt]
        ref_case[o] = [s.get('reference_count') for s in rt]
    def near_constant(case_map, dominant):
        nd = [o for o, vals in case_map.items() if any(v != dominant for v in vals)]
        return {'non_dominant_cases': len(nd), 'share': len(nd) / 32.0,
                'non_dominant_ordinals': nd, 'near_constant': len(nd) <= 2}
    tax = {
        'annotation_rt_support': near_constant(support_case, 'NOT_OBSERVED'),
        'annotation_rt_observability': near_constant(obs_case, 'OBSERVABLE'),
        'support_reference_count': near_constant(ref_case, ref_case.get(7, [None])[0]),
    }
    taxonomy_v2 = all(v['near_constant'] for v in tax.values())
    return {'per_variable': tax, 'taxonomy_v2_diagnostic': taxonomy_v2}


# ---------------- step 9: readout ----------------

def median(xs):
    s = sorted(xs)
    n = len(s)
    return None if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def mad(xs):
    m = median(xs)
    return None if m is None else median([abs(x - m) for x in xs])


def cliffs_delta(a, b):
    if not a or not b:
        return None
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def readout(rows):
    ok = [r for r in rows if r.get('status') in ('complete', 'partial')]
    common = [r for r in ok if all(r.get(f'R{k}_status') == 'complete' for k in (3, 5, 10))]
    n_complete_R5 = sum(1 for r in ok if r.get('R5_status') == 'complete')
    frac = n_complete_R5 / 32.0
    variables = {'stock_layer_summary': lambda r: r.get('stock_layer_summary'),
                 'etf_expansion_count': lambda r: r.get('etf_expansion_count'),
                 'etf_contraction_count': lambda r: r.get('etf_contraction_count')}
    var_reports = {}
    consistent_pairs = []
    for name, get in variables.items():
        cells = {}
        for r in common:
            v = get(r)
            if v is None:
                continue
            cells.setdefault(v, []).append(r)
        cell_info = {}
        for v, rs in sorted(cells.items(), key=lambda kv: str(kv[0])):
            r5 = [r['R5'] for r in rs]
            eras = sorted({r['era'] for r in rs})
            cell_info[str(v)] = {'n_common_complete': len(rs), 'median_R5': median(r5), 'MAD_R5': mad(r5),
                                 'median_R3': median([r['R3'] for r in rs]), 'median_R10': median([r['R10'] for r in rs]),
                                 'era_distribution': eras}
        qualifying_cells = [v for v, rs in cells.items() if len(rs) >= 5]
        qualifying_variable = sum(1 for v in qualifying_cells if True) >= 2 if qualifying_cells else False
        qualifying_variable = len(qualifying_cells) >= 2
        pairs = []
        vals = sorted(cells.keys(), key=str)
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                A, B = vals[i], vals[j]
                ra, rb = cells[A], cells[B]
                qa, qb = len(ra) >= 5, len(rb) >= 5
                d = {'variable': name, 'cellA': str(A), 'cellB': str(B),
                     'nA': len(ra), 'nB': len(rb), 'qualifying_pair': bool(qa and qb)}
                for H in ('R3', 'R5', 'R10'):
                    d[f'd{H}'] = (median([r[H] for r in ra]) - median([r[H] for r in rb])) if ra and rb else None
                d['CONSISTENT'] = bool(qa and qb and all(d[f'd{H}'] is not None and d[f'd{H}'] != 0 for H in ('R3', 'R5', 'R10'))
                                       and len({math.copysign(1, d[f'd{H}']) for H in ('R3', 'R5', 'R10')}) == 1)
                d['cliffs_delta_R5'] = cliffs_delta([r['R5'] for r in ra], [r['R5'] for r in rb])
                d['classification'] = 'qualifying' if (qa and qb) else 'sparse_descriptive_only'
                pairs.append(d)
                if d['CONSISTENT']:
                    consistent_pairs.append(d)
        var_reports[name] = {'cells': cell_info, 'qualifying_cells': [str(v) for v in qualifying_cells],
                             'qualifying_variable': qualifying_variable, 'pairs': pairs}
    # frozen top-down tree
    if frac < 0.80:
        decision, rule = 'B', 'P1 complete_R5_fraction < 0.80'
    elif not any(v['qualifying_variable'] for v in var_reports.values()):
        decision, rule = 'C', 'P2 no qualifying variable'
    elif consistent_pairs:
        decision, rule = 'A', 'P3 >=1 CONSISTENT qualifying pair'
    else:
        decision, rule = 'B', 'P4 otherwise'
    return {'complete_R5_fraction': frac, 'n_complete_R5': n_complete_R5,
            'n_common_complete_R3_R5_R10': len(common), 'variables': var_reports,
            'consistent_pairs': consistent_pairs, 'decision': decision, 'decision_rule': rule}


def main():
    mapping = resolve_mapping()
    global mapped_codes
    mapped_codes = {m['code'] for m in mapping.values()}
    calendar, cal_sha = load_calendar()
    rows, ledger = outcomes(mapping, calendar)
    taxonomy = load_variables(mapping, rows)
    ro = readout(rows)
    execution = {
        'report_type': 'PHASE_I_I2_UNBLIND_EXECUTION',
        'authority': 'user GO on commit 62f473e (I2 OUTCOME READ — AUTHORIZED)',
        'mapping_resolved': len(mapping), 'mapped_codes': sorted(mapped_codes),
        'calendar_sha256': cal_sha, 'calendar_days': len(calendar),
        'read_count': len(reads),
        'failures': failures,
        'status': 'FAIL_CLOSED' if failures else 'UNBLIND_COMPLETE',
    }
    table = {'report_type': 'PHASE_I_I2_OUTCOME_TABLE', 'corpus': 'ordinary pilot ordinals 7-38',
             'rows': rows, 'ledger': ledger,
             'counts': {'complete': sum(1 for r in rows if r.get('status') == 'complete'),
                        'partial': sum(1 for r in rows if r.get('status') == 'partial'),
                        'origin_unresolved': sum(1 for r in rows if r.get('status') == 'origin_unresolved'),
                        'data_error': sum(1 for r in rows if r.get('status') == 'data_error')}}
    report = {'report_type': 'PHASE_I_I2_READOUT_REPORT', 'readout': ro,
              'taxonomy_v2_diagnostic': taxonomy, 'execution': execution}
    (EVID / 'phase_i_i2_outcome_table.json').write_text(json.dumps(table, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    (EVID / 'phase_i_i2_readout_report.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    # append execution reads to the logged manifest
    PIN['unblind_reads'] = reads
    PIN['unblind_execution'] = execution
    PIN['status'] = 'UNBLIND_EXECUTED' if not failures else 'FAIL_CLOSED'
    PIN['outcome_read_authorized'] = True
    PIN['allowlist_extensions_applied'] = sorted({r['allowlist_rule'] for r in reads if r['allowlist_rule'].startswith('extension:')})
    (EVID / 'phase_i_i2_unlock_read_manifest.json').write_text(json.dumps(PIN, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'status': execution['status'], 'mapping': len(mapping), 'reads': len(reads),
                      'decision': ro['decision'], 'decision_rule': ro['decision_rule'],
                      'complete_R5_fraction': ro['complete_R5_fraction'],
                      'taxonomy_v2': taxonomy['taxonomy_v2_diagnostic'], 'failures': failures[:5]}))
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
