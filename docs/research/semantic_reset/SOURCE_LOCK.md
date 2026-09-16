# SOURCE_LOCK（P0 语义恢复：来源锁定）

日期：2026-09-16。复刻对象与依据：

## 主参考源（本仓复刻依据）

`/root/.hermes/hermes-agent/week_surge.py`（584行，v4.0，2026-06-11）
- LEGACY_FORENSICS.md 全部行号引用基于此文件；
- 含形态B效率比较（t_eff/l_eff）、形态A、周一至周五分支、v4.0 veto；
- 差分验证：`tests/test_legacy_source_differential.py`，900/900 判定一致
  （monday 178/178，tuesday 153/153，midweek 388/388，friday 181/181）。

## 同源变体（未混入复刻，单独记录）

1. `/root/tdx_data/week_surge.py`：更早的简化版——"双阳+上周涨幅>前周+上周量>前周"，
   无 t_eff 效率公式。**不是**本次复刻对象。
2. `/root/.hermes/hermes-agent/realtime_quotes.py`：盘中实时版——周一分支
   "上周开盘→实时价"合并语义、周二递归+双阴递进缩量。EOD 复刻不含合并语义；
   如需盘中复刻另立 `source_variant=legacy_realtime`，不得与 EOD 拼接。
3. `release_2026-08-07/day_trade.py`（v4.1）：折算用日历星期 5/(weekday+1)，
   veto 用"过去4周任一周"基线。不同年代版本，不复刻进 legacy_eod。

## 复刻版本命名

- `legacy_reconstructed_v1_eod`：本仓 `signals/weekly_features.py`，
  已通过 900/900 差分；仍需旧实时版单独验收后才可注册 `legacy_v0`。
- `current_v1`：v2 仓库重构现状（决策层 weekly_momentum.py revised 模式），冻结对照用。
