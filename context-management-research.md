# dsh 长会话上下文管理调研报告

## 1. 主流工具怎么做
- **Claude Code 三级压缩**（源码分析）：① MicroCompact 每轮清除旧工具输出（FileRead/Bash/Grep/Glob/WebSearch 等可再生产物，Agent/MCP 结果不动），无 LLM 调用，回收 10–50K；② Session Memory 用后台持续更新的会话记忆替代摘要调用，保留近 10K–40K tokens；③ Full Compact：LLM 生成 9 段结构化摘要（用户意图/技术概念/文件代码/错误修复/所有用户消息/待办/当前工作等），触发阈值＝窗口−min(输出上限,20K)−13K（200K 模型≈167K，83%）；连续失败 3 次熔断；压后回注最近 5 个文件（≤50K）。
- **OpenCode**：自动压缩默认开；保留最近 15K tokens 原文＋摘要，后续压缩增量更新旧摘要；摘要请求复用正常请求的 prompt cache。触发 96–99%（最后手段，prunable 下限 20K）。
- **Gemini CLI**：默认约 50% 窗口即压（激进求稳）；两段式"摘要＋二次自检"；保留约 30% 尾部原文；提示词内置注入防护。
- **Roo Code**：智能压缩默认开，阈值滑块（默认 100%，文档建议 80%）；首条消息永不压缩；被压内容打 condenseParent 标签可回溯而非删除；超窗错误自动截 25%、重试≤3。**Cline**：自动摘要替代旧的滑窗截断，保留技术细节/代码变更。
- **Aider**：不自动压缩，只报错并给建议，人工 /compact。7 款中 6 款为"Extract 摘要替换"模式，OpenHands 独用事件溯源（append-only＋压制标记，可回放）。

## 2. context rot 证据与压缩时机
- Lost in the Middle（Liu 2023）：U 型位置曲线，中部信息检索显著最差。
- Chroma《Context Rot》（2025-07，18 模型）：即使极简任务，性能随输入变长非均匀劣化；NIAH 满分≠长上下文可用。
- Anthropic 工程博客：LLM 有"注意力预算"，上下文是收益递减的有限资源；长任务三法＝压缩/结构化笔记/子代理。
- 经验阈值区间：50%（Gemini 求质量）～90%（Codex 硬顶，可下调 model_auto_compact_token_limit），Claude 83–89%。求稳应取低端。

## 3. 分层记忆
- **Letta/MemGPT**：context＝RAM、外存＝磁盘。四层：消息缓冲(FIFO)→core memory（常驻、字符上限、agent 可自编辑）→recall memory（全史检索）→archival（向量库）；sleep-time agent 空闲期后台整理。
- **mem0**：抽取＋固化两级流水线，ADD/UPDATE/DELETE/NOOP 去重更新；user/session/agent 三作用域；论文称较无记忆基线准确率+26%、p95 −91%、token 省 90%（arXiv 2504.19413）。
- **Cognee**：ECL 管道（extract–cognify–load），知识图谱＋向量混合，可全本地。
- 何时外置：跨会话的事实/偏好/项目知识外置、按需检索注入（量级 ~4K）；会话内工作集才留在 context。

## 4. 防爆护栏
- 预算扣减：有效窗口＝窗口−输出预留（Claude 预留 min(输出上限,20K)——输出预留是最常被漏掉的项）；多级预警（−20K 警告/−13K 自动压/−3K 阻塞）。
- 压缩请求自身爆窗：Claude Code PROMPT_TOO_LONG 重试——按轮次分组丢最老组，最多 3 次。
- 模型切换校验（对应 luna 事故）：切换前按目标模型窗口/tokenizer 重估现有上下文，超限先压缩或截断再切；Claude Code 有 CLAUDE_CODE_AUTO_COMPACT_WINDOW 按环境固定压缩窗口。
- 兜底：Roo 检测多家 provider 超窗错误→自动截 25%→重试 3 次。

## 5. 变慢原因与缓解
- TTFT：prefill 随长度增长（Epoch AI 实测百万 token：GPT-5.6 二次、Claude 5 近线性）；agent 输入:输出≈100:1（Manus），延迟被 prefill 主导。
- 缓存失效：每次压缩毁掉 KV 前缀缓存（隐藏成本）；Manus 称 KV 缓存命中率为生产 agent 第一指标，上下文应 append-only（只追加不改写前缀）；Claude Code MicroCompact 热缓存路径用 cache_edits 删旧工具输出而不破缓存，时间型压缩专挑缓存已冷时机。
- 缓解：稳定前缀（system＋工具定义＋早期对话不动）；摘要请求复用同一前缀（OpenCode）；工具输出截断/引用化；子代理隔离大上下文、只回传 1–2K 摘要（Anthropic）。

## 对 dsh 的落地建议
1. 三级管线：工具输出清理→增量摘要→全量 compact，阈值≈窗口−输出预留−13K；
2. 模型切换闸门：切前校验＋自动压缩，杜绝 luna 型爆窗；
3. 摘要模板抄 Claude Code 9 段＋保最近 ~15K 原文（OpenCode/Gemini 实证）；
4. 缓存友好：append-only、压缩挑缓存冷点；
5. 跨会话记忆外置（dsh-evolve 已有，可对齐 mem0/Letta 分层）。

## 来源
- Claude Code 压缩系统源码分析: https://github.com/openedclaude/claude-reviews-claude/blob/main/architecture/11-compact-system.md
- OpenCode Compaction 官方文档: https://dev.opencode.ai/v2/docs/compaction/
- Gemini CLI 压缩(ChatCompressionService/两段式): https://github.com/google-gemini/gemini-cli/pull/12001 ; https://github.com/google-gemini/gemini-cli/pull/16914
- Roo Code 智能上下文精简: https://docs.roocode.cn/features/intelligent-context-condensing
- Cline Auto Compact: https://docs.cline.bot/features/auto-compact
- Aider Token limits: https://aider.chat/docs/troubleshooting/token-limits.html
- 七款 agent 压缩对比(阈值表/KV缓存成本): https://codex.danielvaughan.com/2026/04/10/context-compaction-showdown-coding-agents/
- Chroma Context Rot: https://research.trychroma.com/context-rot
- Lost in the Middle: https://arxiv.org/abs/2307.03172
- Anthropic Effective Context Engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Letta/MemGPT: https://docs.letta.com/concepts/memgpt/ ; https://www.letta.com/blog/sleep-time-compute
- mem0: https://github.com/mem0ai/mem0 (arXiv 2504.19413)
- Cognee: https://github.com/topoteretes/cognee
- Manus Context Engineering(KV缓存/100:1): https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- Epoch AI 长上下文延迟: https://epoch.ai/publications/long-context-latency-scaling-gpt-vs-claude
