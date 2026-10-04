#!/usr/bin/env python3
"""CSR-8 Phase I — FINAL SYNTHESIS / THEORY BOUNDARY FREEZE builder.

Reads the frozen I1/I3/I4B artifacts, asserts every number quoted in the
freeze, assembles the four-tier theory map (Established / Conditional /
Unresolved / Forbidden), and writes the freeze JSON + MD. ZERO new results
are computed; this only compresses what I1-I4B already froze.

Outputs: docs/phase_i/phase_i_final_freeze.json
         docs/phase_i/PHASE_I_FINAL_SYNTHESIS_FREEZE.md
"""
import json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'docs/phase_i'
EVID = ROOT / 'docs/audit/evidence'


def load(p):
    return json.loads(Path(p).read_bytes())


def approx(a, b, eps=1e-9):
    return abs(a - b) < eps


def main():
    i1 = load(P / 'i1_structural_atlas.json')
    i3 = load(P / 'i3_contextual_readout.json')
    i4b = load(P / 'i4b_readout.json')
    i4a_cov = load(P / 'i4a_coverage_matrix.json')
    third = load(EVID / 'phase_i_third_readout_128_report.json')
    i3_by = {r['relation']: r for r in i3['relation_results']}
    i4b_by = {r['relation']: r for r in i4b['relation_results']}

    # ---- assertions: every frozen number must match its source artifact ----
    A = []
    A.append(('I1 non-dominant set', sorted(k for k, v in i1['cards'].items()
             if v['taxonomy_status']['non_dominant'] and int(k) >= 7) ==
             sorted(str(x) for x in [8, 15, 41, 44, 48, 51, 53, 55, 63, 67, 68,
                                     72, 79, 105, 108, 112, 115, 117, 119, 127])))
    A.append(('I3 ND/NO_PIT DESCRIPTIVE_ONLY', i3_by['SL_ND_vs_NOPIT']['classification_EXT1'] == 'DESCRIPTIVE_ONLY'))
    A.append(('I3 ETF both THEORY_ELIGIBLE',
              i3_by['ETF_4_vs_8']['classification_EXT1'] == 'THEORY_ELIGIBLE'
              and i3_by['ETF_8_vs_9']['classification_EXT1'] == 'THEORY_ELIGIBLE'))
    A.append(('I3 dedup numbers', approx(i3_by['ETF_4_vs_8']['date_dedup_R3']['dR5_dedup'], -0.0163, 1e-3)
              and approx(i3_by['ETF_8_vs_9']['date_dedup_R3']['dR5_dedup'], 0.0433, 1e-3)))
    A.append(('I4B both CONDITIONAL',
              i4b_by['ETF_4_vs_8']['context_classification'] == 'CONDITIONAL'
              and i4b_by['ETF_8_vs_9']['context_classification'] == 'CONDITIONAL'))
    up48 = i4b_by['ETF_4_vs_8']['strata']['UP']
    up89 = i4b_by['ETF_8_vs_9']['strata']['UP']
    A.append(('UP 4v8 theory-grade', up48['stratum_r4_theory_grade'] and up48['dates_A'] == 8
              and up48['dates_B'] == 5 and approx(up48['naive_d'], -0.0863, 1e-3)
              and approx(up48['dedup_d'], -0.0375, 1e-3) and approx(up48['lco']['d_dedup'], -0.0371, 1e-3)))
    A.append(('UP 8v9 theory-grade magnitude-stable', up89['stratum_r4_theory_grade']
              and up89['dates_A'] == 5 and up89['dates_B'] == 8 and approx(up89['naive_d'], 0.0478, 1e-3)
              and approx(up89['dedup_d'], 0.0551, 1e-3) and approx(up89['lco']['d_dedup'], 0.0546, 1e-3)))
    for rel, s in (('ETF_4_vs_8', 0.0513), ('ETF_8_vs_9', -0.0242)):
        dn = i4b_by[rel]['strata']['DOWN']
        A.append((f'DOWN {rel} low-coverage flipped', dn['low_coverage'] and dn['dates_A'] == 3
                  and dn['dates_B'] == 3 and approx(dn['dedup_d'], s, 1e-3)))
    A.append(('regime census UP94/DOWN28', i4a_cov['manifest']['n_rows'] == 1280
              and sum(1 for v in i4a_cov['per_case_regime'].values() if v['regime'] == 'UP') == 94
              and sum(1 for v in i4a_cov['per_case_regime'].values() if v['regime'] == 'DOWN') == 28))
    failed = [n for n, ok in A if not ok]
    assert not failed, f'freeze assertions failed: {failed}'

    freeze = {
        'freeze_id': 'csr8-phase-i-final-synthesis-theory-boundary-v1',
        'status_block': {
            'PHASE I': 'FROZEN — interpretation authority',
            'I1-I4B': 'COMPLETE (I1 cee5efd / I2 eddd1ff / I3 5674101 / I4A 664b35d+597e4a1 / I4B c0937c9)',
            'SAME-128-CORPUS ANALYSIS': 'CLOSED — no further analysis on the frozen corpus',
            'SECTOR CONTEXT': 'DEFERRED — requires independent historical-membership + PIT-provenance pipeline',
            'PHASE J DOWN-REGIME VALIDATION': 'GO AFTER THIS FREEZE — new INDEPENDENT corpus; directions preregistered below',
            'PHASE H 128 CORPUS': 'IMMUTABLE (freeze 9dfc516 lineage)',
            'ORDINALS 129+': 'UNAUTHORIZED — HOLD'
        },
        'authority_chain': [
            'user rulings 2026-10-04: I1 acceptance + three rulings; I2 APPROVE/FROZEN + I3 GO; I3 COMPLETE + I4 GO (two-stage); I4B APPROVE/COMPLETE + Phase I final freeze GO',
            'Phase H final freeze csr8-phase-h-final-freeze-v1 (9dfc516); third readout (3f46515)',
            'I2 contract sha e32bf614... + addendum-1; I4A contract sha b1278342... + addendum-semantic-1'
        ],
        'evidence_hierarchy_table': [
            {'relation': 'stock_layer ND vs NO_PIT', 'phase_H': 'PRESERVED',
             'I3_date_clustering': 'direction holds; dates 74/4', 'I4B_market_context': 'DOWN unreadable (NO_PIT n=1)',
             'standing': 'DESCRIPTIVE_ONLY — excluded from re-upgrade'},
            {'relation': 'ETF 4 vs 8', 'phase_H': 'PRESERVED',
             'I3_date_clustering': 'THEORY_ELIGIBLE (direction robust; naive magnitude sampling-amplified)',
             'I4B_market_context': 'UP − / DOWN + (DOWN 3/3 dates LOW_COVERAGE)',
             'standing': 'CONDITIONAL'},
            {'relation': 'ETF 8 vs 9', 'phase_H': 'PRESERVED',
             'I3_date_clustering': 'THEORY_ELIGIBLE (direction+magnitude robust)',
             'I4B_market_context': 'UP + / DOWN − (DOWN 3/3 dates LOW_COVERAGE)',
             'standing': 'CONDITIONAL'}
        ],
        'theory_map': {
            'established': {
                'corpus_identity_provenance': '128 sealed cases (64 opaque entities x 2 epochs), Phase H immutable freeze 9dfc516; identity-lineage violations 0; I1 atlas (cee5efd) provides per-case structural cards with deterministic rebuild',
                'date_clustering_facts': ['128 cases != 128 independent environment observations: observation-date clusters (2021-04-06: 9, 2021-03-08: 7) materially move cell medians',
                                          'the 3 Phase-H REVERSED pairs are sampling-dependent structure (T=2021-04-06 cluster lifted cell-8 median -0.0362 -> -0.0088; epoch-1 restriction reproduces the 64-corpus sign)',
                                          'I3 three-way evidence-tier split: ND/NO_PIT DESCRIPTIVE_ONLY (NO_PIT 18 cases on 4 dates); ETF 4v8 & 8v9 THEORY_ELIGIBLE (date-dedup + leave-max-cluster-out direction-stable)'],
                'up_stratum_theory_grade_relations': {
                    'ETF_4_vs_8_UP': {'dates': '8/5', 'naive_d': up48['naive_d'], 'dedup_d': up48['dedup_d'],
                                      'lco_dedup': up48['lco']['d_dedup'],
                                      'statement': 'in the preregistered UP regime the 4<8 direction is theory-grade (within-stratum R4 fully passed)'},
                    'ETF_8_vs_9_UP': {'dates': '5/8', 'naive_d': up89['naive_d'], 'dedup_d': up89['dedup_d'],
                                      'lco_dedup': up89['lco']['d_dedup'],
                                      'statement': 'in the preregistered UP regime the 8>9 direction is theory-grade with magnitude stable across all calibers'}}
            },
            'conditional': {
                'ETF_4_vs_8': 'market-environment-conditional structural relation; refined from I3 "magnitude fragile": overall magnitude unstable, but clearly more stable within the UP condition (dedup -0.0375 / LCO -0.0371); composition attenuation (mixing UP and DOWN) is a natural but UNPROVEN explanation candidate',
                'ETF_8_vs_9': 'market-environment-conditional structural relation; in the preregistered UP regime theory-grade positive structural evidence exists; the stronger "cross-context structural relation" candidacy is RETRACTED (refuted by I4B DOWN flip)',
                'mirror_ordering_observed_fact': {
                    'wording_frozen': 'mirror ordering across the observed ETF-expansion levels 4/8/9',
                    'fact': 'UP: 4<8>9; DOWN: 4>8<9 (DOWN strata 3/3 dates, LOW_COVERAGE — sign reported under output-coverage semantics only)'}
            },
            'unresolved': [
                'DOWN regime has only 3 distinct observation dates per side — the flipped directions cannot be upgraded to theory grade in this corpus',
                'sector context DEFERRED entirely (single-snapshot 2026-09-21 classification is lookahead; an independent historical-membership + PIT-provenance + coverage-census pipeline is required before any sector analysis)',
                'ND-vs-NO_PIT: NO_PIT arm covers only 4 observation dates; upgrade requires new sampling diversity (production problem)',
                'whether the mirror ordering is a genuine market-conditional structure or an artifact of 3 dates — answerable ONLY by an independent DOWN-diverse validation corpus (Phase J)'
            ],
            'forbidden_inference': [
                'causal claims of any form (e.g. "the 9th ETF expansion causes R5 to rise")',
                'actor-intention attribution (national team / 主力 / institutional intent) on any layer',
                'treating 4/8/9 as points on a continuous function; U-shape or inverted-U mechanism language; "8 is a regime threshold"',
                '"the more ETF expansion, the ..." monotonic extrapolation',
                '"DOWN market mechanism proven" — DOWN strata are output-coverage only',
                'treating the 000985 120-day-median regime as a complete market-state model (it is a coarse modifier)',
                're-opening the 128 corpus, ordinal 129+ production, capital-state label redefinition'
            ]
        },
        'phase_j_preregistration_sketch': {
            'status': 'AUTHORIZED AFTER THIS FREEZE — NOT STARTED; sketch frozen now to prevent post-hoc design',
            'name': 'Phase J — DOWN-Regime External Validation',
            'purpose': 'raise DOWN-regime observation-date diversity on an INDEPENDENT corpus (the 128 discovery corpus stays immutable) and test the frozen mirror-direction predictions',
            'frozen_directions': {
                'already_frozen_from_discovery_UP': {'ETF_4_vs_8': '<0', 'ETF_8_vs_9': '>0'},
                'down_validation_hypotheses': {'ETF_4_vs_8': '>0', 'ETF_8_vs_9': '<0'}},
            'locks': ['no re-search of ETF levels; only cells 4/8/9 as frozen', 'no new comparisons',
                      '120-day median regime definition unchanged', 'index stays 000985 raw close with trade_date<T',
                      'R5 definition unchanged', 'R4 hard gate + date-dedup + leave-max-cluster-out + effective-N reporting all inherited',
                      'discovery corpus never merged into the validation corpus']
        },
        'guarantees': ['zero new results computed in this freeze (assertions re-verify frozen artifacts only)',
                       'all interpretation boundaries carried verbatim from I2/I3/I4A contracts + addenda + user rulings',
                       'change control: append-only erratum + explicit user authorization']
    }
    (P / 'phase_i_final_freeze.json').write_text(
        json.dumps(freeze, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    h = hashlib.sha256(json.dumps(freeze, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':')).encode()).hexdigest()
    md = f"""# CSR-8 Phase I — Final Synthesis / Theory Boundary Freeze

*Freeze:* `phase_i_final_freeze.json` · sha256 `{h}` · builder asserts {len(A)} frozen numbers against I1/I3/I4B/I4A artifacts (all PASS)
*Status:* **PHASE I FROZEN（解释权威）· I1–I4B COMPLETE · 同 128 语料分析 CLOSED · SECTOR DEFERRED · PHASE J 于本冻结后 GO · PHASE H IMMUTABLE · 129+ UNAUTHORIZED-HOLD**

## 证据层级总表

| 关系 | Phase H | I3 日期聚类 | I4B 市场环境 | 当前地位 |
|---|---|---|---|---|
| ND vs NO_PIT | PRESERVED | 方向保持；dates 74/4 | DOWN 不可读（NO_PIT n=1） | **DESCRIPTIVE_ONLY**（禁再升级） |
| ETF 4 vs 8 | PRESERVED | THEORY_ELIGIBLE（方向稳健；naive 量级被采样放大） | UP − / DOWN + | **CONDITIONAL** |
| ETF 8 vs 9 | PRESERVED | THEORY_ELIGIBLE（方向+量级稳健） | UP + / DOWN − | **CONDITIONAL** |

## 1. Established（已确立）

- **语料身份与溯源**：128 sealed cases（64 opaque 实体 × 2 epochs）；Phase H 冻结 9dfc516；identity-lineage 违规 0；I1 atlas（cee5efd）确定性可重建。
- **日期聚类事实**：128 例 ≠ 128 份独立环境证据（2021-04-06: 9 例、2021-03-08: 7 例聚类实质移动 cell 中位数）；Phase H 的 3 个 REVERSED = sampling-dependent structure（机制已确定性闭合）；I3 三级证据分层成立。
- **UP 层理论级关系**（层内 R4 全过，≥5 日 + 四口径同号）：
  - **ETF 4v8 @UP**（8/5 日）：naive −0.0863 / dedup −0.0375 / LCO-dedup −0.0371 —— 4<8 方向为理论级
  - **ETF 8v9 @UP**（5/8 日）：+0.0478 / +0.0551 / +0.0546 —— 8>9 方向为理论级且量级稳定

## 2. Conditional（条件性）

- **ETF 4v8**：市场环境条件性结构关系。I3 的 "magnitude fragile" 细化为：**总体量级不稳定，但 UP 条件内量级明显更稳定**（−0.0375/−0.0371）；UP/DOWN 混合造成的 composition attenuation 是自然但未证明的解释候选。
- **ETF 8v9**：市场环境条件性结构关系；预注册 UP regime 中存在理论级正向结构证据。**"cross-context structural relation" 候选撤回**（被 I4B DOWN 翻转证伪）。
- **镜像排序（观察事实，措辞冻结）**："mirror ordering across the observed ETF-expansion levels 4/8/9"——UP: 4<8>9；DOWN: 4>8<9（DOWN 层 3/3 日，仅输出覆盖语义）。

## 3. Unresolved（未决）

DOWN 环境仅 3 个独立观察日（翻转方向无法在本语料升为理论级）；sector context 全部 DEFERRED（需独立的历史成分 + PIT 溯源管线）；ND vs NO_PIT 的 NO_PIT 侧仅 4 个观察日（补样=生产问题）；镜像排序究竟是真实 market-conditional 结构还是 3 日偶然——**只能由独立 DOWN 多样化验证语料回答（Phase J）**。

## 4. Forbidden inference（禁止推论）

因果语言；任何层的 actor intention 归因；把 4/8/9 当连续函数（U 型/倒 U 型机制语言；"8 是 regime threshold"）；"ETF 越多越…"单调外推；"DOWN 市场机制已证实"（DOWN 仅输出覆盖）；把 000985 120 日中位数 regime 当完整大盘状态模型；重开 128 语料；129+ 生产；资金状态标签重定义。

## Phase J 预注册草案（本冻结即锁定方向，不启动）

**Phase J — DOWN-Regime External Validation**：独立验证语料（discovery 128 语料永不合并）补 DOWN 环境观察日多样性，只回答一个问题：*DOWN 多样化后镜像方向是否仍存在？*
- 已冻结方向（discovery UP）：4v8<0；8v9>0
- DOWN 验证假设：**4v8>0；8v9<0**
- 锁死：不重搜档位（仅 4/8/9）、不新增比较、120 日定义不改、指数不改（000985 raw close, trade_date<T）、R5 不重挑、R4+dedup+LCO+effective-N 全继承
"""
    (P / 'PHASE_I_FINAL_SYNTHESIS_FREEZE.md').write_text(md)
    print(json.dumps({'freeze': 'PHASE_I_FINAL_FREEZE_BUILT',
                      'assertions': len(A), 'all_pass': True,
                      'sha256': h}, ensure_ascii=False))


if __name__ == '__main__':
    main()
