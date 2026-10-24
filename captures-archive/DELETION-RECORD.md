# captures/ 工作盘删除记录

- 删除时间：2026-10-25（用户确认后执行）
- 删除内容：`captures/batch2..batch16` + `batch9_extra` 共 14 个批次目录（约 26.6G，1502 个文件）
- 前置条件（全部满足后才执行）：
  1. 14 个批次已打包上传百度网盘 `/apps/ss2archive/`（应用目录，网盘内显示"我的应用数据/ss2archive"）；
  2. 每批远端 size 与本地逐字节一致（fs_id 见各 receipt）；
  3. 每批分片 MD5 经协议层 block_list 强制校验；
  4. 逐文件 SHA256 清单留存在本目录（`*.manifest.sha256`），回执见 `*.receipt.json`；
  5. 删除前复查：打包后 captures 零改动（mtime 全部早于清单生成时间）。
- 删除时 captures 全部批次已静态 20+ 天（最后写入 2026-10-04）。

## 恢复流程（任一批次，约 5 分钟/批）

```bash
# 1. 取回 tar（bdpan 下载或网盘客户端手动下载到 captures-archive/）
# 2. 解包还原批次目录 + 清单
tar -xf captures-archive/batchN.tar -C captures batchN
tar -xf captures-archive/batchN.tar -O batchN.manifest.sha256 > /tmp/m.sha256
# 3. 逐文件核验
cd captures && sha256sum -c /tmp/m.sha256 && cd ..
```

## 与 CSR-8 冻结协议的关系

`csr8_phase_h_final_freeze.py` 的 tar 字节复现（`tar -C 仓库根 -czf X.tar.gz captures/batchN`）
依赖本地 captures 存在。删除后如需重放该验证：先按上面流程从网盘取回对应批次再执行。
batch5 的 release 资产（ERR-9）已在上传时回填网盘，其本地复现同样走取回流程。

## 网盘侧

- 目录：`/apps/ss2archive/`（14 个 tar + 1 个探针文件 bdprobe.txt 可忽略）
- 授权：设备码模式，token 30 天自动刷新（refresh_token 10 年），凭据 `/root/.config/bdpan/`
- 工具：`scripts/bdpan_archive.py`（upload/verify/auth/whoami）、`scripts/bdpan_batch_archive.sh`
