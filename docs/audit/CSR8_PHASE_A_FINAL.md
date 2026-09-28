# CSR-8 / Phase A — C4-D Synthetic Final Closeout

冻结任务书：`CSR8_PHASE_C_PRODUCTION_INFRA_FINAL_TASKBOOK.md`
任务书 SHA256：`9aeb636e2cf9dc8e1b59674e62e9b326e78929384cc5a4e03dd72b4d8a5427c7`
冻结 packet hash：`c7848fea4f493695cfd2a9f0a9703811d3a05069120f49f8612fcb5bcabfb900`

## A1 — 基线与范围

- Phase A 起始 HEAD：`44c54c261875a82e756b8449ed57b8c31270860a`。
- C4-D 设计冻结 anchor：`034d152`。
- C4-C public `production_head_hash`：`b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5`。
- 当前实现改动已核对：guard 与 D71 已存在于
  `scripts/csr8_phase_c_annotation_seal.py`；本阶段未修改 `C4-C executor`、
  `c4c_anchor.json` 或真实生产域。

## A2 — prerequisite guard 与 D71

`prove_next_reveal_eligible(sb, sid, ordinal)` 在任何 next-reveal 授权入口前执行并证明：

- C2 sealing log `verify(check_head=True)` 通过；
- requested ordinal 等于已提交 REVEAL 数 + 1；
- 最后提交事件为 `SEAL_ANNOTATION`，无 open REVEAL；
- 后续 proposal / approval / permit / authorization-chain verification 入口均重复证明；
- append `REVEAL` 前的 consumption-side re-proof 保持 fail-closed。

D71 已执行：

- `[R1,S1]` → ordinal-2 proposal 正向通过；
- `[R1,S1,R2]` → ordinal-3 proposal 命中 `G-C4D-AUTHZ`；
- ordinal-3 proposal、approval、permit 均不存在；
- open R2 链上的 consumption-side re-proof 同样拒绝。

## A3 — 独立复现结果

独立机器证据已入库：`tests/test_csr8_phase_a.py` 以子进程真实执行 Phase A synthetic runner，直接断言 D71、D01-D71、C4-C regression、candidate gates、live invariants，并在运行前后比较 `c4c_anchor.json` 字节；说明文档本身不作为这些结论的证据。

执行环境：`/root/.hermes/hermes-agent/venv/bin/python3`。

1. 全量回归：

```text
PYTHONPATH=src /root/.hermes/hermes-agent/venv/bin/python3 -m pytest -q --junitxml=/tmp/csr8-phase-a-pytest.xml
473 passed / 0 failed / 0 errors / 0 skipped（新增 `tests/test_csr8_phase_a.py` 2 项独立证据测试）
```

2. Phase A synthetic final gate：

```text
/root/.hermes/hermes-agent/venv/bin/python3 scripts/csr8_phase_c_annotation_seal.py synthetic
CANDIDATE GATES PASS: order_size=1717 ordinal1_matches_frozen_first=True revealed_prefix=1
D01–D71: 71 PASS
C4-C regression: PASS
C4-D SYNTHETIC AUDIT GREEN
```

报告中的 live invariants：

```text
REVEAL=1 SEAL=0 annotation=0 c4d_domains=absent anchor=absent
mode=synthetic only; real chain/domains untouched
```

3. 候选闸门：

```text
/root/.hermes/hermes-agent/venv/bin/python3 scripts/csr8_phase_c_annotation_seal.py candidates
{"ordinal1_matches_frozen_first":true,"revealed_prefix":1,"size":1717}
```

4. `c4c_anchor.json` 当前 SHA256：

```text
afe7baa5888b973382b534d722492b69fbb8840d24d208984f03b377fd8aeff5
```

工作树、`git diff --stat` 及针对 `data/`、CSR output 与 `c4c_anchor.json` 的变更核对均为空；synthetic 使用临时目录，未创建真实 annotator、receipt、approval、SEAL 或第二次 production REVEAL。

## A4 — HARD STOP

本提交只记录 Phase A 的 guard、D71、synthetic gate 和不变量证据。Phase B 及后续阶段尚未执行；不得创建真实 annotation domain、receipt、SEAL、ordinal-2 production proposal/approval/permit、第二次 production REVEAL 或读取 outcome。

独立审计确认前，不宣布 `C4-D SYNTHETIC FINAL FROZEN`，不进入 Phase B。

[DSH-AUDIT]
STATE: READY_FOR_AUDIT
RUN_ID: audit_20260928142305936
HOST_ID: RainYun-c438TDGn
STAGE: A
ITERATION: 2
HEAD: <本提交哈希由本轮 marker 精确指认>
SUMMARY: Phase A A1-A4：独立机器证据测试绑定核心 runner、D71、D01-D71、C4-C regression、candidate gates、真实生产不变量与 anchor 字节不变；HARD STOP
TESTS: full pytest 473 passed/0 failed/0 errors/0 skipped；独立 Phase A 证据 2/2；synthetic D01-D71 71 PASS
