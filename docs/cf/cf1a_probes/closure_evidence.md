# CF-1A 闭合证据（自动汇总）

生成: 见文件时间戳 · 输入: release_time/*.json (1 份)

## 发布时点结论（T=20261016 各传感器首次可查时点）

| 传感器 | 首次可查时点 | 说明 |
|---|---|---|
| SSE ETF 份额(T) | 采样未齐 | 见采样矩阵 |
| SZSE ETF 份额(T) | 采样未齐 | 见采样矩阵 |
| SSE 两融(T) | 采样未齐 | 见采样矩阵 |
| SZSE 两融(T) | 采样未齐 | 见采样矩阵 |

## 修订复查（10-15 数据于 10-16 晚重查 vs 基线）

```json
{
 "status": "PENDING (等待 10-16 20:05 自动采样)"
}
```

## Backfill 覆盖统计

```json
{
 "sse_etf_scale": {
  "data_days": 246,
  "empty_days": 21,
  "first_data": "20120104",
  "last_data": "20130108",
  "first_empty": "20120102",
  "last_empty": "20130103",
  "long_gaps": [
   [
    "20120120",
    "20120130",
    10
   ],
   [
    "20120330",
    "20120405",
    6
   ],
   [
    "20120928",
    "20121008",
    10
   ]
  ],
  "data_days_by_year": {
   "2012": 243,
   "2013": 3
  }
 },
 "szse_etf_scale": {
  "missing": true
 },
 "szse_margin": {
  "missing": true
 },
 "sse_margin": {
  "missing": true
 }
}
```

## 采样矩阵原始状态

| 文件 | T | 时点 | sse_etf_T | sse_margin_T | szse_etf_T | szse_margin_T |
|---|---|---|---|---|---|---|
| 20261015_evening_replay_check.json | 20261015 | evening_replay_check | 922✅ | -❌ | 756✅ | -❌ |
