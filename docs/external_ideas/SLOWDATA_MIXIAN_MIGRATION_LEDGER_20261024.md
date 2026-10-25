# 慢频数据（龙虎榜/大宗/两融）官方直采 · 搬米线迁移台账

- 日期：2026-10-24
- 仓库：`/root/project/workspace/stock-selector-v2`（整合/调度）、`/root/project/workspace/tdx-node`（采集端代码）
- 执行人：老刘（决策） + Hermes/米线（实施）
- 状态：**链路已跑通并已挂调度**；`stock-data` 归档仅本地 commit，**push 等老刘批准**

---

## 0. 结论摘要

1. **米线（RainYun KVM，出口洛杉矶 AS979）可直采全部慢频官方端点**，7/7 通过（含深交所 WAF）；
   历史深度到 **2021-01**，与 Windows 归档原件**逐字段 0 差异**（见 §1.3）。
2. 采集端代码**最小 Linux 化**（`TDX_NODE` 参数化 + 去掉 Windows-only 锁检测），新增 Linux 驱动
   `collector/daily_slow_linux.py`：采集 → 体检 → 打包 → 本地 commit → 整合 e5.db。
3. 节奏：**每日 19:40 主跑**（`--window 10`） + **周一 08:00 补「未挂」漏项**（`--catchup --window 21`），
   systemd timer 管理、`flock` 串行、日志落 `/root/slowdata/logs/`。
4. Windows 端降为**备用**；GitHub `stock-data` 保留为**版本化备份**（米线本地 commit）。
5. 遗留：`lhb_crosscheck_tdx`（与 TDX 客户端独立源对拍）**在米线跑不了**——缺 TDX 客户端插件产物，见 §6.1。

---

## 1. 证据链（为什么敢搬）

### 1.1 端点探活：7/7 通过

| 数据集 | 端点 | 结果 |
|---|---|---|
| LHB 上交所主板 / 科创板 | SSE 官方 | 通 |
| LHB 深交所列表 / 明细 | SZSE 官方（有 WAF） | 通（重试 0~1 次） |
| 大宗 上交所 / 深交所 | SSE/SZSE 官方 | 通 |
| 两融 上交所 / 深交所 | SSE/SZSE 官方 | 通 |

### 1.2 历史深度

- 回溯抓取至 **2021-01** 全通；深交所明细钻取（席位/大宗）同样可达。

### 1.3 决定性对拍（米线重抓 vs Windows 归档原件）

- 对拍对象：归档 `stock-data` 内 **2026-09-30 Windows 原件** ↔ 米线重抓同页。
- 结果：**字段集 + 逐字段取值 = 0 差异**（脚本 `/tmp/probe4_diff.py`）。
- 结论：米线直采与既有归档**同源同值**，可直接接替，不需要重新建基线。

### 1.4 「零行」定性（不是风控）

- `2026-09-25`：中秋休市 → 零行正常。
- `2026-10-23`：深交所当日明细**尚未发布**（发布时点问题）→ 归入「未挂」，由周一 08:00 补漏。

---

## 2. 工程改造清单（最小改动，未重构链路）

| 文件 | 改动 | 目的 |
|---|---|---|
| `collector/*.py`（12 处） | `NODE = Path(r'D:\tdx-node')` → `os.environ.get('TDX_NODE')` 兜底 | Linux 可跑，Windows 仍可跑 |
| `collector/block_margin_backfill.py` | 去掉 Windows-only 锁检测 | Linux 无对应机制 |
| `collector/daily_incremental.py` | 新增 `--dates` 透传、`--no-normalize` | 驱动按交易日窗口直调 |
| `collector/make_year_archive.py` | `pack_dataset(keep_if_same=True)`：成员集+逐成员 sha256 全等则**保留旧包**；修 `kept` 键泄漏 + `generated` 日期噪声 | 幂等：省 50s 重压、消 git 假提交 |
| `collector/daily_slow_linux.py` | **新增**（282 行）五步驱动 + `--catchup` / `--dry-run` / `--force-*` | 一条命令跑完采集→整合，每步留时间戳/行数/PID 证据 |
| `src/capital_data/e5_build_db.py`、`e5_lhb_build.py` | `sqlite3.connect(DB, timeout=60)` | 与 R2 19:30 链并发时不因 5s 锁超时失败（见 §6.2） |

### 驱动五步（`daily_slow_linux.py`）

1. **采集** `daily_incremental.py --dates <窗口内交易日> --no-normalize`（COMPLETE 日自动跳过；margin/szse 零行 7 天内可重试 → 天然补漏）
2. **体检** 两个 `backfill_state.json` → 逐日逐数据集 COMPLETE / PENDING（未挂）/ FAILED，写 `$NODE/last_run_status.json`
3. **打包** `make_year_archive.py --stage <stock-data>` 确定性年包 + MANIFEST(sha256)
4. **提交** `git -C stock-data add -A && commit`（**仅本地**）
5. **整合** `stock-selector-v2/scripts/h_slowdata_pull.sh --local` → MANIFEST 闸门 → rsync `data/r2/e5/` → 重建 e5.db（含行数膨胀绊线）

---

## 3. 部署形态

```
/root/slowdata/node/            # NODE（运行期数据根，新建）
├── collector -> /root/project/workspace/tdx-node/collector   # 软链：单一代码源
├── manifests -> /root/project/workspace/tdx-node/manifests   # 软链
├── lhb/{raw,backfill_state.json}
├── blockmargin/{raw,backfill_state.json}
└── last_run_status.json

/root/slowdata/stock-data/      # STAGE（版本化归档 git 仓，含 MANIFEST.json / YYYY 年包 / csv）
/root/slowdata/logs/            # collect.log / catchup.log
```

> `collector` 走软链 → **仓库即唯一代码源**，改代码只需改 `tdx-node/collector/`，调度与手工跑自动同步。

---

## 4. 调度（systemd）

| 单元 | 时间 | 命令 | 日志 |
|---|---|---|---|
| `slowdata-collect.timer` | **Mon..Fri 19:40** | `daily_slow_linux.py --window 10` | `/root/slowdata/logs/collect.log` |
| `slowdata-catchup.timer` | **Mon 08:00** | `daily_slow_linux.py --catchup --window 21` | `/root/slowdata/logs/catchup.log` |

- 两个 service 均：`Type=oneshot`、`Environment=HOME=/root TDX_NODE=/root/slowdata/node`、
  `WorkingDirectory=/root/slowdata/node`、`TimeoutStartSec=3h`、`Persistent=true`（错过自动补跑）、
  `flock -w 1800 /run/slowdata-collect.lock`（主跑与补漏**串行**，不并发打官方端点）。
- 已 `systemctl enable --now`；首次触发：**2026-10-26 08:00（补漏）**、**2026-10-26 19:40（主跑）**。

---

## 5. 验证记录

### 5.1 T1 单日对拍（归档 vs 重抓）

- 逐字段全等（同 §1.3）。

### 5.2 T1b 全链干跑（幂等）

- 打包阶段 **全 KEEP**（年包与既有归档逐成员 sha256 全等 → 保留旧包，无重压、无 git 噪声）。
- e5 幂等核验通过：`margin/block/lhb` 行数 **4579500 / 198598 / 84170** 前后一致。

### 5.3 T2 当天实操（16 个交易日：20260923..20261023）

- 目的：覆盖归档断档 **1009~1023**，一次补齐。
- 结果：**<待回填>**

---

## 6. 遗留项

### 6.1 `lhb_crosscheck_tdx` 在米线不可跑（缺 TDX 客户端产物）

- 该脚本输入其一为 `NODE/tdx-tq-v773/PYPlugins/data/lhb*.json`（**通达信客户端插件产物**）。
- 米线：全盘无 `lhb*.json`、无 `tdx-tq-v773`；`tdx-protocol/realclient` 只有行情/财务/capital 类 op，
  **没有龙虎榜 op** → 该独立源在米线**结构性不可得**。
- 另一输入 `NODE/lhb/csv/lhb_seats.csv` 由 `lhb_normalize.py` 生成（米线可产，但主跑用 `--no-normalize`）。
- **处置**：该闸门维持 **Windows 侧 / 周期性人工对拍**；米线侧等价证据 = §1.3 归档字节级对拍。
  （如需在米线保留该闸门：把 Windows 的 `lhb*.json` 定期同步过来即可，成本很低。）

### 6.2 与 R2 19:30 日更链的 e5.db 并发

- 事实：R2 日更链 19:30 启动，**10-23 实际运行到 20:42**；慢频 19:40 会重建 e5.db → 窗口重叠。
- 处置（已做，最小改动）：两个 builder `sqlite3.connect(..., timeout=60)`，写者最多等锁 60s 再失败。
- 待观察：若仍有 `database is locked` 失败，备选方案 = 主跑挪到 **21:00**（同时能捞到更晚发布的深交所明细）。

---

## 7. 待老刘批准事项

1. `stock-data` 归档（本地 commit）**是否 push 到 GitHub**。
2. `tdx-node` 采集端 Linux 化改动 + 新驱动 `daily_slow_linux.py` **是否 push**。
3. §6.1 是否要把 Windows 的 `lhb*.json` 同步到米线以恢复交叉核对闸门。
4. §6.2 主跑时段是否维持 19:40（或改 21:00）。

## 追加：老刘 2026-10-24 三项定案（当晚执行）

1. **全量重建（服务器侧）** — 36 个年包（2021-01-04→2026-10-23）全量解到 `$NODE` raw 树，
   `make_year_archive` 逐组文件数核验 **36/36、0 差异**（lhb_raw 66766 / block+sse 1404 /
   block.szse_detail 54732 / block.szse_list 3380 / margin.sse 1427 / margin.szse 115894）。
   随后跑三支 normalize 全量重建 csv：
   - `lhb_seats.csv` 245M / 954551 行；`lhb_daily_stock.csv` 21M / 98262 行；覆盖 1404 天、`failed_or_incomplete_days: []`
   - `block_trades.csv` 50M / 199617 行；`margin_daily.csv` 803M
   → **驱动去掉 `--no-normalize`**，`daily_slow_linux.py` 采集步默认含全量 normalize；
   `--no-normalize` 降级为应急开关（仅 raw 不全时用）。
   新增 **3.5) csv 同步**：NODE csv → `STAGE/csv` + 刷新 `MANIFEST.json` 的 csv 段 sha256。
   **口径**：默认只收 lhb 组（DATASET_META.json + lhb_seats.csv + lhb_daily_stock.csv），
   与老归档 csv 段一致；block_trades / margin_daily（合计 ~850M）留在 NODE 不版本化，
   下游零消费（`h_slowdata_pull.sh` 闸门原文「e5/csv 目前代码零消费」）；`--csv-all` 可强制全收。

2. **主跑时段 19:40 → 21:00** — `slowdata-collect.timer` 改 `Mon..Fri 21:00:00`
   （避开 R2 19:30→20:42 链，并能捞到更晚发布的深交所明细）。catchup 仍为周一 08:00。

3. **lhb*.json 定期同步** — 新增 `/root/slowdata/bin/sync_tdx_lhb.sh` +
   `slowdata-lhb-sync.timer`（周日 10:00 / 周一 07:30）。经 tailscale 从 Windows
   拉 `D:/tdx-node/tdx-tq-v773/PYPlugins/data/lhb*.json` → `$NODE/tdx-tq-v773/PYPlugins/data/`；
   不可达则 SKIP（退出 0，不影响主链），写 `$NODE/last_lhb_sync.json`。
   驱动新增 **6) 交叉核对**：有 lhb*.json 就跑 `lhb_crosscheck_tdx.py`，无则跳过。
   **一次性前提**：Windows 侧把米线公钥写进 `C:\ProgramData\ssh\administrators_authorized_keys`。

## 磁盘

本轮 raw 全量落盘 + csv 全量重建使 NODE 增加约 3.7G（raw 2.65G / csv 1.08G）。
零风险清理（journal 3.7G + npm）后：101G used / **16G free / 87%**。
待老刘定夺的大头：`captures` 27G、`output/research` 6.8G。

## 2026-10-25 08:18 收尾核验（米线侧）

- 磁盘：老刘已清理，`/` 由 87%/剩 16G → **62%/剩 46G**（净释放约 30G）。
- 慢频资产清点无损：`node/lhb/raw` 549M、`node/blockmargin/raw` 2.1G、`node/lhb/csv` 265M、`node/blockmargin/csv` 816M、`stock-data` 889M；`e5.db` 301,318,144 B。
- `sync_tdx_lhb.sh` 端到端试跑：Windows（100.84.28.40）当前**不在线/未放免密** → `result=SKIPPED`，**exit=0 不脏主链**。
- 修补：脚本原仅在成功分支写 `last_lhb_sync.json`，SKIP 时留空文件；现改为两分支都写状态（SKIP 写 `result=SKIPPED`），试跑后文件 99 B 内容正确。
- 定时器矩阵确认：`slowdata-lhb-sync` Sun 10:00 / Mon 07:30、`slowdata-catchup` Mon 08:00、`slowdata-collect` Mon–Fri 21:00。
- 未做：三仓本地 commit 仍**未 push**（等老刘发话）。

## 2026-10-25 08:40 push 受阻与修复（GitHub 100MB 上限）

- 老刘批准 push。tdx-node（2→含新修复共 3）、stock-selector-v2（1）直推成功。
- stock-data 被拒：**`csv/lhb_seats.csv` 244.33MB > GitHub 单文件 100MB**（GH001 pre-receive hook）。
- 否决 LFS：seats csv 每日一版（每版 ~244MB 新对象），免费 LFS 额度几天就爆。
- 定案：**seats csv 撤出 git 归档**。它是 lhb_raw 的派生品，可由 raw 全量重建；canonical 副本留 `NODE/lhb/csv/lhb_seats.csv`。
- 修复动作：
  1. tdx-node `861d856`：csv_sync 排除 `lhb_seats.csv` + 自动清 STAGE 残留防复发；
  2. stock-data 重写待推 2 commit 为 1 个（`16f5815`，soft reset→撤文件→MANIFEST csv 段剔除→force-with-lease），origin csv/ 现只剩 DATASET_META + lhb_daily_stock（21.5MB，增速 ~15KB/日，十几年内安全）；
  3. 旧历史存 `backup/20261025-pre-rewrite` 分支。
- 核验：`git fetch -q` 后 `status -sb` = `## main...origin/main`（0 ahead 0 behind）；origin csv/ 2 文件；MANIFEST csv 段 sha256 实核验 ALL_OK；新 commit 内 >100MB 文件 = 0。
