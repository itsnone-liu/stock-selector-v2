# C3 Design Erratum — Frozen Price Source and Chart Value Shape

- 状态：窄语义勘误，待用户确认后生效；不改 C1/C2
- 基线：C3 DESIGN v1.0 FINAL FROZEN @ `3308de9`
- 触发：C3-AUDIT-FIX1 审计发现仓库不存在可绑定的 TDX 个股日线面板；
  `DATA_PLAN_TDX_INTEGRATED.md` §2 明确日线 OHLCV 的研究窗冻结 SoR 是
  `baostock hfq/unadj`，TDX 仅作交叉验证（`CROSSCHECK_PENDING`）。

## 唯一变更

C3 chart source contract 从：

```text
frozen TDX unadjusted panel
```

窄改为：

```text
frozen BaoStock unadjusted panel
source root: data/adjustment_baostock/per_stock/
source manifest: per-file canonical SHA256 + source contract
adjustflag: 3 (unadjusted)
```

这不是用 BaoStock 静默顶替 TDX；是明确记录当前 Phase-B 冻结 SoR 与 C3 实际可绑定
输入一致。TDX 交叉验证状态不被提升为 TDX SoR。

## Chart schema 变更

annotation-visible `price_panel.values` 不再携带 BaoStock OHLCV 全行；只保留冻结定义
要求的 close series：

```yaml
price_panel:
  source_id: baostock_unadjusted_v1
  start_date: start(T)
  end_date: T
  dates: [date]
  values: [unadjusted_close]
```

`dates` 与 `values` 一一对应；`values[i]` 是 BaoStock `unadj` 行的 close（index 4）。
其余 open/high/low/volume/amount/turn/pctChg 不进入 annotation-visible packet。

## 不变项

- `CHART_LOOKBACK_TRADING_DAYS = 120`；`start(T)` 仍只由 T+冻结交易日历决定；
- hidden `window_start` 不参与 chart；blindness fixture 不变；
- 六个 gate ID、coverage equality、C1/C2 binding、isolated preflight 边界不变；
- C3 public artifact 仍只允许 commitment + boolean summary；
- source manifest/hash 必须由 G-C3-CHART 绑定；单 bit 改动 FAIL-CLOSED。

在用户确认本窄勘误前，任何新 C3 commitment 均不得视为有效；`9614791` 继续
保持 `AUDIT BLOCKED`。
