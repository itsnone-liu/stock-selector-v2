# CF-IS v2 — Phase 2A 阶段记录

## 已实施

1. 已将 v2 方案及启动检查点推送 origin/main（67c1a96）。
2. 修正周表日期、收益缺失/精度、完整前向窗口、ISO53周与原子可用时间。历史收益生产者已从源代码和首日横截面复算核对，不再用实时脚本推断。详见 IS2A_TIME_AND_BASELINE.md。
3. 保留真实指数基准独立旁路：is2a_index_baseline.py 读取已有中证全指价格序列；197/246周有可用端点且通过14天断档守卫。2023年春夏长缺口和2026-04-30后的缺失不补造；此为第三方取得的指数价格序列，不是交易所官方数据源或含分红总收益。
4. 宏观事件台账3条：2023年印花税调整、2024年1月降准宣布、2024年9月金融发布会。每条保留权威来源、公开/保守可用/生效日期及时间不确定性；仅用于管线测试，不是无偏事件总体。
5. 事件窗口脚本生成89行：3×(事前8交易周+事件周+事后12交易周)，另2个固定季度日历窗各13周。24条事前周的原子时间代理均早于事件可用时间。事件周混合、事后非信号、回溯episode非PIT分别标明；日历窗不是“无事件”对照。

## 关键修正与结果边界

- 旧 IS1 数字已标部分失效。34个支持增强×去杠杆周，修正后仅20个具有完整连续4日历周结果，不能仍以34作结果分母。当前统计只说明管线可运行，不是介入效果。
- 整周观察最早以次周保守评估时点使用；3周原子可用性未知，usable_at留空。
- axes regime 开发分位档位有回看，episode terminal是最终生命周期结果，均不能直接作为当时交易特征。CENSORED分类不能倒灌成历史决策证据。
- 事件窗用观察交易周计数，atlas前向4周/滚动8周用连续日历周；两种时距明确分开，长假不静默混同。
- 本轮不证明宏观事件关键假说成立，也未产出入场规则。当前大资金层仍为低频/有限股票披露，不能声称四层真实主体均被识别。

## 复现

```bash
python3 scripts/cfis/is0_weekly_sample.py --start 20220101 --end 20261028 --out data/cfis/weekly_full_202201_202610.csv
python3 scripts/cfis/is1_weekly_atlas.py
python3 scripts/cfis/is2a_index_baseline.py
python3 scripts/cfis/is2a_event_windows.py
python3 -m pytest --noconftest tests/test_cfis_weekly.py tests/test_cfis_index_baseline.py tests/test_cfis_event_windows.py -q
```

32项针对性测试通过。系统常规pytest被既有pandas/numpy ABI错误阻断，本批stdlib模块用 --noconftest 验证，未修改环境；不声称全仓回归通过。顺序执行，周表RSS约77MB。data/按仓库策略忽略，脚本、台账、报告、输入/输出SHA256清单 is2a_run_manifest.json 跟踪入库。live数据可能继续增长，指纹用于识别版本变化而非声称永久冻结。

## 下一实施批次

Phase 2A 数据基础与连续小样已形成；进入 Phase 2B 前，先以有限内容类别扩充事件台账（包括风险冲击与低反应事件），修补必要基准缺口或限制适用窗口；大资金证据按披露范围使用。再构建不依赖未来episode终态的卖压衰减/承接/接力路径和A/B/C候选节点，比较修复、滞留、破位与有无事件条件差异。当前无介入建议、无生产变更、无R6-2启动。
