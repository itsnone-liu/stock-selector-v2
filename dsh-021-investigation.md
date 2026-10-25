# DSH 0.2.1 飞书桥隔离调查

Goal: 定位并修复新版桥无回复，生产旧版保持运行。
Core: 不启动共享 /root/.dsh 的新版；所有执行测试使用独立 home、mock transport 和独立工作区。
Verified:
1. systemctl show: 生产 bridge 与 web 均钉在旧 rc.7 路径，当前 active。
2. /root/dsh-lab/CUTOVER-PLAN-021.md 声称隔离新版真实多轮曾成功；并非已证实新版普遍不可用。
3. journalctl 20:16:43 创建 session-9777d169-caf5-41e0-870e-40706ef81999，20:18:42 dispose 报 format v4 message requires a producer-owned source kind。
4. 新版 /opt/dsh-021/node_modules/@deepseek-ai/dsh-session-format-v3-to-v4/lib/index.js:124-126 明确拒绝 source.kind=plugin。
5. lab dsh-evolve/lib/index.js:849-897 pre-step 注入仍用 source.kind=plugin，turn/start 注入亦如此；有重要可测试兼容假设，尚未确证现场根因。
Open: 实际生产插件与 lab 是否一致；去掉 evolve 或修 source 后能否完成 turn；其余 producer 插件是否也用旧 source。
6. 新鲜 baseline session-0b4e000a 的解码恰好复现事故全部7行：权限三项、inbox seq3、turn/start seq4、出队 seq5，此后无持久化 turn/end（baseline-fresh.decoded.jsonl）。transport 已显示 source schema 错误，persistence 被该错误毒化。
7. 相同 real agent + copied memory，仅 index.js source 修正后固定模型请求成功，三轮含 /new 完成；fresh fixed 进一步通过（三轮5个请求含辅助请求）。副本 review.js 与 llm-refine.js 同样完成8处整体修正。
8. 重启 fixed 独立进程后 resume session-58cfd4f4 成功，两轮完成，模型请求包含真实 bash 结果 TOOL_OK。
9. verify-dsh-probe.py 全部断言通过：原始事故与baseline事件同构、fresh首轮/次轮/new完成、重启resume与工具闭环。
10. 已输出新版专用补丁 .dsh-021-probe/dsh-evolve-v4-source.patch 与 RESULTS.md；.gitignore 排除整个probe目录（包含私有记忆副本）。
11. persistence源码 lib/index.js:211-218：批次校验失败重新入buffer并设置drainPaused，解释为何磁盘停seq5不代表内存无后续事件。
12. external独立home调用真实GLM glm-5.3成功，完成卡片正文 FEISHU_021_REAL_OK（不是loopback）；requests统计为0因计数器仅统计本地server。
13. 独立测试Bot小白马已用全新testbot home启动，job bash-8 / pid1948841，ws ready，180秒自动停止；未连生产Bot，已请用户发消息验证。
14. 读取当前证据文件的独立fork审查确认隔离兼容问题已验证、生产未修复；另一仅继承上下文的fork未看到当前进展，其判断已通过文件复核纠正。
15. 测试Bot180秒窗口无用户入站，已自动停止并收集bash-8输出；不能宣称真实飞书闭环通过。所有bash-1至bash-8均收集完毕，无残留实验进程。两项耗时只读子任务已请求中断，核心证据由主线程和文件审查完成。
16. Round1：隔离插件8处改调用message-source.js，通过installed dsh-llm版本分支：rc7保留plugin wrapper且补summary以满足后续迁移；0.2.x用plugin:dsh-evolve。legacy独立home在真实rc7上3轮含/new通过（5请求）；新版helper再次2轮通过。生产未改。
17. 新增check-dsh-bridge-health.py，验证精确回复正文与完成卡片，rc7三轮、新版两轮、真实GLM均通过；原版broken baseline被负控正确拒绝。该门仅声明isolated agent-to-output，不能冒充飞书E2E。已打包dsh-evolve-dual-version-source.patch。
18. bash-10因与legacy实验争用18791端口失败，已调查EADDRINUSE，等待legacy结束后顺序bash-11重试通过；bash-9/10/11均已收集。
19. Round2：把legacy修复后生成的v0会话复制到migration独立home，新版成功resume原session-cea4b9af（identity比较一致，非fallback新建），连续2轮完成、idle；生成session.v4且原v0保留。解码v4含3个turn/end（1历史+2新），source迁移不再因summary失败。bash-12收集完成。
20. 健康门补齐status存在时idle断言；migration正控通过。RELEASE-CHECKLIST.md记录补丁边界（不追溯修旧历史summary）与待验飞书收发/回调。生产未改。
21. Round3：重新读取测试Bot日志，仍无任何真实用户入站；迁移健康门复跑通过，生产MainPID1945443 active未变。连续Round1/2/3均欠缺用户真实入站与收件确认，不能由mock或Bot自发消息替代，故将goal标记blocked等待用户测试窗口，避免无意义自动轮转。
22. 用户请求开小白马测试，bash-13启动独立Bot pid1950501。真实入站2条：升级后测试，请只回复Ok / 请只回复OK；session-619461df连续2个turn/end completed。
23. 飞书只读消息API回读code0，确认两张app interactive完成卡片正文分别Ok/OK，reply IDs om_x100b62eba5bac8a4df1dfc0f685c3d6、om_x100b62eba388e8a4c051986ada6b2e0。acceptance.json保存机器验收。用户确认已发，未明确确认客户端阅读；不冒充人工收件确认。
24. 隔离真实Feishu→真实GLM→Feishu完成2轮闭环；停止测试job bash-13并收集，生产1945443仍active不变。goal revision2 complete（仅隔离排查修复验证目标，不是生产切换）。
Next: 向用户汇报隔离验收通过；生产升级/权限回调专项属于后续明确授权执行窗口。

Delegation: 4533e2a6-1c31-454b-8be7-408b7b0eb37c 只读追踪内核 inbox/turn 路径。
