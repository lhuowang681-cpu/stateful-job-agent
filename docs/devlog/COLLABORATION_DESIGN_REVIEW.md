# 有界多 Agent 协作方案评审（保留原评审时点）

最新：后续用户已授权并完成 [M3B 原文摘要子集](PHASE-03B-writer-reviewer.md)。下文“未实施”指评审当时，不能覆盖最新实际状态；自由改写、面试协作和对照实验仍为计划。

日期：2026-10-20。用户提供第三方建议并要求评审；本轮仅源码/文档核对与方案记录，不视为已授权重写架构，不调用模型或改变运行代码。

## 判断与实际基线

有界反馈协作可以成为业务中的研究点；workflow-based 与 collaborative 不是严格互斥的技术等级，同一 LangGraph 可编排两种行为。价值需用结果与成本证明。

- 旧主图：`src/job_agent/runtime/graph_runtime.py::AgentGraphRuntime._build_langgraph_if_available`，主要是预定节点和 verdict 分支，没有 Writer/Reviewer 多轮协作。
- 旧动态面试：`src/job_agent/interview/controller.py::AdaptiveInterviewController.next_turn`，AgentLoop 动态决定追问/挑战/切换，包含评估字段但不是独立 Evaluator 对 Reviewer 的协作协议。
- 已有反馈基础：`src/job_agent/interview/copilot_service.py::ApplicationCopilotService.submit_answer` 调用 evaluate_answer，再调用 `_follow_up`，使用 missing_points/unsupported_claims 生成追问；这是一条规则反馈链，不能当作新协作系统已完成。
- 既有测试锚点：tests/test_stateful_interview_copilot.py::test_grounding_follow_up_completion_weakness_and_targeted_retry、tests/test_adaptive_interview_controller.py::test_controller_rejects_live_score_leak。本轮只读核对，未重跑。
- 新工作台 M3：matching.py 的 WorkbenchMatcher/validate_bundle 与 match_repository.py 的 MatchRepository.decide 已接 JD/版本/C1/排序闭环，尚无 Writer↔Reviewer、独立面试 Evaluator 或统一协作 trace。

## 候选实施顺序与合同

1. 优先 M3B：在当前版本/JD/来源/用户核对底座上实现 Writer→Reviewer→有限修订→用户审批。各角色独立目标、输入/输出 Schema 和权限，Reviewer 不写简历，Writer 不审批自己，路由先用确定性规则。
2. 先提出“忠实表达已有自述”与“生成新事实”的独立操作合同；C1 保持 C1，不能通过新协作路径绕过旧新 claim 投影约束。若修改现有证据语义，须单列方案和回归范围，不能默默放宽等级。
3. 核验分开记录来源有效性、语义支持/部分支持/冲突/不确定、证据等级、用户决定。两模型一致不证明事实正确；引用正确不自动证明改写没有改变否定、数字、年限、责任或生产边界。
4. 修订次数、总模型调用/token/耗时预算、重复反馈终止、失败与待用户补证据出口都需明确。可以先设最多两次修订作为待测配置，非现有已实施上限。
5. 人工审批绑定 draft_revision/content_hash；状态持久化、消息去重、旧反馈失效与副作用幂等必须测试。Checkpoint 不是外部模型计费 exactly-once 保证。
6. 业务继续推进 PDF 闭环；模拟面试阶段复用既有评估/追问基础，再接 Evaluator→Interviewer 的类型化决策信息，Evaluator 不直接输出用户可见文本，不提前暴露评分细则/参考答案。

## 通信与追踪的最小范围

LangGraph 状态 + Pydantic 类型消息即可，不增加 Kafka/RabbitMQ/新 Agent 框架。
候选消息字段：message_id、run_id、correlation_id、from/to、type、draft_revision、evidence_refs、payload、budget_usage。
Reviewer 返回问题类型、相关 claim/来源 ID、修改约束和下一步动作；不广播完整简历和所有中间上下文。
Trace 展示实际角色调用、审阅问题、修订差异、路由、验证状态、预算和最终审批；不展示模型隐藏思考过程或私人材料日志。
只存在 message JSON 或两次固定 LLM 调用不等于协作收益已验证；须展示反馈实际改变后续建议/追问。

## 对照实验要求（尚未执行）

A 单 Writer；B Writer→Reviewer 单次顺序审核；C Writer↔Reviewer 有界反馈。
三组共用输入版本/JD、资料权限、最终确定性校验、样本/标注和相同评价规则，不能只给 C 组来源校验。
同时报告等预算对照和实际成本/延迟；保留单 Agent 自修订的等预算控制，区分“多调用一次”与“角色协作”的收益。
分别统计原始输出的事实错误、最终放行错误、拒绝/无法完成比例、岗位要求覆盖和有效修订；不能靠全部拒绝降低错误率。
评估否定、量化/年限、职责归属、技术关系、生产/实验边界、冲突证据；独立标注，不用参与协作的 Reviewer 给自己打最终分。
面试另评追问相关性、薄弱点覆盖、无效追问和提前答案泄漏，不与简历指标混算。记录实际模型/配置/样本量/种子或重复次数/token/耗时，未提升也如实报告。
不变更旧冻结集和 R12 指标定义；新研究数据另行版本化，不预先宣称协作优于单 Agent。

## 官方参考与适用边界

2026-10-20 查阅：
- [LangChain Multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent)：custom workflow 可混合多种模式，多 Agent 不自动必要或更优。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpointer 与跨线程 store 作用不同。
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：恢复可能重执行节点，副作用需幂等；实施时仍须核对已安装版本。

本轮未修改运行源码、未部署协作机制、未重跑业务测试；M3 的 201/0/0、前端 9/0/0 仍是上一阶段的历史验收，不能当成本方案结果。

后续状态（M3C）：用户明确授权核验分层和面试协作，两项本地子集已完成，见 [PHASE-03C](PHASE-03C-verification-interview.md)。原建议的任意问答、自由生成、质量/费用优势仍未被该子集证明；旧评审时点保留。
