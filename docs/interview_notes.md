# Interview Notes

本页保留较早的独立 RAG/Runtime 实验问答。2026-10-18 源码审计后的主要材料见
[中文源码指南](INTERVIEW_SOURCE_GUIDE.md)：桌面 UI 不调用向量检索；RAG mapper 只支持
supported/partial/unsupported，不能将 UI mapper 的 contradictory 能力推广到它。
下文历史数字不是本次修复后重新测得的结果。

## 为什么不用 LangChain / LangGraph 全包？

项目关注的不是“能否把节点连起来”，而是 Tool 调用是否经过一致的权限、审批、预算、超时、幂等和轨迹合同。仓库虽然保留 LangGraph 依赖和部分图执行能力，但核心 Agent Runtime、MCP Adapter、Tool Registry、Policy、Approval、Checkpoint 与 Tracker 语义是显式实现的。这样可以独立测试 policy deny、approval pending/resume、duplicate retry 和不确定副作用，而不把这些关键行为隐藏在框架默认值里。

## 为什么 MCP 仍要经过 Runtime？

MCP 解决工具发现与调用协议，不自动解决“当前 agent 是否有权调用、调用多少次、多久超时、结果如何进入轨迹”。本项目的路径是 `Action → Runtime → Registered MCP Tool → Adapter → Bridge → Server`。因此 MCP Tool 与 Internal Tool 使用同一套 Registry、Policy、Budget、Timeout 和 Trajectory；业务代码不能直接创建 MCP client 绕过治理。

## Memory / State / RAG 有什么区别？

- **Memory**：跨请求的用户长期信息，例如目标城市、方向和岗位类型，当前由 `UserStateStore` 管理。
- **State**：某次工作流或业务实体的确定性状态，例如 Action checkpoint、application current stage 与 transition history。
- **RAG / Knowledge**：为了回答当前 requirement 临时检索的外部候选材料，输出是带来源的 `RetrievedChunk`。

三者生命周期和可信度不同：Memory 影响偏好判断，State 驱动恢复与副作用，RAG 只提供待核验上下文。

## RetrievedChunk 为什么不能直接当 Evidence？

Dense score 只表达向量空间相似，BM25 score 只表达词项相关；它们都不证明候选人真的具备某项能力。项目中 `RetrievedChunk` 保留 document/chunk identity、rank 和 retrieval method，Evidence Mapping 还要判断 supported、partial、contradictory 或 gap，并用 exact quote 生成 `SourceSpan`。Kubernetes 与 PDF/DOCX case 证明，如果跳过这一步，相关后端或 ingestion 文本会被过度推断。

## 为什么最后不用 BM25 / RRF？

所有方法使用同一 corpus、query 和 gold labels。Dense 的 Recall@1/3/5 为 0.8241/0.8889/1.0000，MRR 为 0.9167；BM25 是 0.5463/0.6481/0.8889/0.6769；RRF 是 0.7130/0.8889/1.0000/0.8583。BM25 对 `CareerContextAdapter` 精确实体有补益，但对多个 semantic case 退化；RRF 也降低 Recall@1 和 MRR。因此保留实现与实验，但默认链路选 Dense。

## 为什么 Candidate Evidence 要单独建 corpus？

JD 自身与 requirement 几乎同义，若与候选人材料混在同一检索范围里，JD 很容易排在前面并形成循环证明。Candidate Evidence Retriever 只允许 candidate-owned document 进入证据候选；JD 保留为 requirement provenance，但明确禁止成为 evidence source。这解决的是语义边界，不是简单调低相似度阈值。

## Structured output 为什么会失败？

Mock Provider 会精确返回预设 schema，不能暴露真实自回归模型的生成困难。Qwen2.5-7B-Instruct 初始 8 个 case 中有 7 个 schema error，主要问题是 parent requirement 与 atom 的双向 ID 引用增加了生成约束。项目采用同一 Pydantic contract，简化生成形状，明确 JSON-only、字段名与枚举，使用最小 JSON extraction，再做 strict validation 和 fail-closed；最终达到 8/8，不用 mock fallback，也不让 Python 猜业务字段。

## 如何防止 Tool side effect 重复执行？

Runtime 使用稳定 Action identity / digest、checkpoint 与 resume 语义；application tracker 对相同目标状态避免重复 transition。批准恢复时执行的是原 Action，而不是重新生成一份不稳定请求。对于“外部效果可能已经发生但 receipt 未落库”的情况，后端语义进入 `UNCERTAIN`，禁止普通 resume，避免盲目重放。

## approval 和 authorization 有什么区别？

Authorization 是系统规则：tool 是否在 skill、agent 和 runtime allowlist 中，属于 Policy 决策。Approval 是用户对某个具体、有副作用 Action 的确认，并绑定 action digest。即使用户批准，未被授权的 tool 仍不能调用；即使 tool 被授权，写操作也可能需要 approval。读取 tracker 通常是 read-only，而记录岗位和阶段更新属于受治理写操作。

## timeout 为什么不等于远端取消？

本地等待超时只能说明调用方不再等待，不能证明远端进程、MCP server 或外部系统已经停止，更不能证明副作用没有发生。因此 Runtime 把 timeout 当成不确定结果处理，依赖 operation identity、receipt、checkpoint 和后续核验，而不是立即重复执行。这个区分对申请记录或未来外部投递类工具尤其重要。

## 如果继续做，下一步是什么？

优先扩大真实评估覆盖，而不是继续堆功能：增加更多真实但脱敏的 JD、candidate materials 和 adversarial gap cases，测量不同模型与 prompt 版本的稳定性；随后再补持久化 Knowledge index 与可审计的离线重建流程。若要接入真实招聘平台，必须先完成身份、secret、外部副作用 receipt、人工确认和隐私边界，不能直接把当前本地 Demo 宣称为自动投递系统。
