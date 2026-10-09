# Erratum：shadow_portfolio p3_target 口径（2026-10-09 裁定）
1) RISK_HOLD 0.25 未乘 BEAR 0.5 → 应 0.125（与 R2-10/11 验证模拟 base*=m 一致；BUILD 同病 return 0.2 未乘）
2) UNDERCUT_TEST 未减半 → 应 ×0.5（验证模拟 if not sup: st*=0.5）
3) 盈利跳档属持仓跟踪层，首日静态快照无浮盈，未实现为正确行为
处置：10-08 封存（sha 59fa827d）保留原样不重封；新口径自 10-09 生效。
影响面（10-08 若按新口径）：CONFIRM×UNDERCUT 4只 0.25→0.125；RISK_HOLD×IN_SUPPORT 87只 0.25→0.125；RISK_HOLD×UNDERCUT 18只 0.25→0.0625；BUILD 在非BEAR也应乘 m。
