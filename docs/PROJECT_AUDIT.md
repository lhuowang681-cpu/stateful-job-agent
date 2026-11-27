# Stateful Job Agent 源码审计与最小修复记录

## V3收尾审计更新（2026-10-21）

从F0保留最新dirty源码逐阶段复用，未重写旧Evidence，未改冻结标签或历史指标。主产品现在是React/FastAPI简历→JD→局部改写→PDF、项目RAG→三模式面试/复盘、岗位关联；独立CLI/Streamlit/MCP/PG-Redis继续各自边界。

| 功能 | 实际状态/分类 | 核心锚点（src/job_agent） | 风险/处理 |
|---|---|---|---|
| 来源/版本/审批/PDF | A，本地UI/测试/真实PDF | resume_workspace/repository.py、rewrite.py、pdf_export.py | 中：C1不升格，中文语义人工/模型待验 |
| JD/Evidence | A，短材料直读；规则是lead | resume_workspace/matching.py、evidence/requirements.py | 中：真实语义质量LIVE_PENDING |
| 公共知识 | A，UI/面试结束复盘 | resume_workspace/public_knowledge.py、public_seed.py | 中：小语料/标签诊断不能作泛化指标 |
| Code-aware检索 | A，UI/项目面试真实读取 | resume_workspace/code_parser.py、code_rag.py | 中：静态边不证明运行/作者，动态解析不完整 |
| 有界协作/工具 | A，规则浏览器+替身合同 | retrieval_interview.py、interview_tools.py、agent_runtime/tool_executor.py | 中：真实LLM决策质量未验 |
| 本地持久任务 | A，真实HTTP/子Worker恢复 | resume_workspace/tasks.py::TaskRepository/IndexTaskWorker | 中：SQLite单机，未迁生产 |
| Qwen/FAISS/MCP | B，独立实现与既有测试 | knowledge/、job_search_workflow.py | 新React默认未配向量，不能宣传全入口使用 |
| PG/Redis/Outbox | B，旧独立后端；当前环境集成阻塞 | backend_service/reliable_worker.py/outbox.py | 高：本轮2失败34跳过，不沿用旧Linux通过结果 |
| OCR/真实模型质量/容器部署 | C或未验收，不等于功能通过 | 见FAILURE_CASES与部署说明 | BLOCKED/NOT_RUN：DLL、授权、环境分别记录 |

实际结果：F3相关114/0/0；F4相关75/0/0；F5相关76/0/0；后续最新针对性61/0/0；最终全量855/2/50，169.92秒，最后相关78/0/0，原始JUnit和skip原因摘要docs/devlog/evidence/v3/regression-summary.json。2 Redis服务缺失失败，34 PG与16模型条件未跑；首次深Windows路径失败与无效参数记录保留。真实公开104文件Worker发布后故障→租约恢复→第二次成功，同键不新建任务，异主404。

公共BM25漏tags已修，仅搜索metadata变动，原quote/hash保留；v1 .50与v2 1.00 Recall的40标签开发诊断均保留，不作为盲评。冻结代码题不变，flat已有全文件召回，复杂方案无召回增益。OCR本机两个ONNX版本初始化失败，cap.ocr=false；不把安装依赖当识别通过。

交付学习路径见learning/，精确阶段差异见FINAL-F1…F6，最终验收以FINAL_HANDOVER/FEATURE_MATRIX为准。以下是旧审计过程，不覆盖当前更新。

审计日期：2026-10-18。对象：本地 `agent-backend-service`，起始 HEAD
`067bfc7d63408e1e6b0ab6c227e863bd08a5857a`。不使用旁边的旧版仓库作依据。
原始完整归档仍保留；本次只修改本地工作副本，不修改服务器项目，不提交 Git。

## 阶段与恢复位置

1. 第一阶段已完成：入口、实现、评测来源已整理；修改前聚焦测试 75 passed。
2. 第二阶段已完成最小修复；未统一重写 UI、RAG 或后端证据系统，详见后文变更表。
3. 最终收尾全量回归：**568 passed / 0 failed / 16 skipped**，Linux 临时隔离服务环境；剩余真实模型条件测试未运行。
4. README、简历及源码指南已同步，上一轮架构冻结并交付。
5. 2026-10-20 用户明确启动长期求职产品升级，保留旧基线；M1 增量及当前验证见文末“新一轮升级”。
6. M2 已接通 React、文档导入、字段解析/核对及版本编辑；相关回归 154 passed、前端 4 passed；真实模型未验收，见文末 M2 记录。
7. 采用用户提供的开发留痕协议，补录 PHASE-01/02、当前架构、决策与继续开发手册；本轮不修改业务功能。

本报告第一至第四阶段保留上一轮过程记录，包括 522/3/50 的历史结果；
**旧基线以“最终针对性收尾与架构冻结”及 `audit/closeout/` 为准；新升级单独记录，不沿用旧成绩**。

隐私边界：不打开 `.env`、私人简历/JD、`data/private/`、真实模型输出或原始私人轨迹。
只检查源码、synthetic fixtures、公开脱敏汇总报告。历史私有数据是否真的按约冻结，
本次不能独立认证；公开 manifest、统计公式和汇总数只能提供有限的交叉证据。

## 第一阶段：实际入口与调用链

### 1. UI：当前普通桌面入口是直接材料 Evidence v2

`ui/app.py:main` → `ui/views/workbench_page.py` →
`ui/new_session_wizard.py:_create_session/create_operation`（调用 `run_initial_v2_live`）→
`ui/runner.py:run_initial_v2_live` → `evidence/pipeline.py:EvidenceV2Pipeline.run`。

Pipeline 执行：

1. `EvidenceSourceStore.snapshot` 保存 raw JD、原始简历和可选 supporting sources；规范化换行、
   保存 raw/content SHA-256，来源落在本次 run 的不可变目录。
2. `RequirementAnalyzer.analyze` 调 LLM 输出 compact requirement candidates；
   Python `_materialize` 为每个候选创建一个 parent 和一个 atom，生成 ID，解析原文引用。
   **当前 UI 不是对每个复合要求进一步生成多个 atom 的独立原子化阶段。**
3. `EvidenceMappingService.map` 把所有非 `raw_jd` 候选材料交给 LLM，不调用向量检索。
4. Python guard 校验 atom 覆盖、link ID、候选来源、唯一 exact quote、内容 hash、offset、等级上限；
   `_materialize` 计算 match status 和 contradiction 标记。
5. `FitAssessmentPolicy.assess` 按固定权重计算 estimated fit、verified coverage、hard gate 与不确定性。
6. `EvidenceArtifactRepository.commit/load_current` 写 artifact hashes、manifest 和原子 current pointer。
7. `EvidenceProjectionService` 分别生成 resume/interview/UI 视图；`runner` 在允许时调用
   `ResumeTailoringAgent.run`，否则保留原始简历并明确标注没有新增事实依据。
8. staging 目录成功后 `os.replace` 发布 session；异常清理 staging，不提交替代 mock 结果。

UI wizard 只传入 JD 和原始简历，没有上传 C2/C3 supporting sources 的连接。
因此这个默认请求中的候选证据应当最多 C1，能显示线索，但通常不能新增可验证简历事实。
`run_initial_base`、`run_initial` 仍保留供兼容/测试使用，不应描述成当前 wizard 的执行分支。

测试依据：`test_ui_live_runtime.py`、`test_ui_evidence_v2.py`、
`test_evidence_requirement_analyzer.py`、`test_evidence_mapping_v2.py`、
`test_evidence_source_store.py`、`test_evidence_projections.py`。

### 2. 普通 CLI、LangGraph 与旧语义证据

`pyproject.toml` 的 `job-agent` → `cli.py:main`。
默认 `--mode offline_rule`：`run_fixture_flow/run_jobs_flow/run_manual_jd_flow` →
`graph.py:_run_selected_job_flow` → 规则 JD、关键词 `nodes/evidence_mapping.py:map_evidence`、
Fit verdict、简历、面试与 answer cards。它没有 embedding，也不是 LangGraph 执行。

`--mode agent_api`：CLI 先准备上述选择/基线结果，再构造 provider/registry，调用
`AgentGraphRuntime.run_selected_job`。native `StateGraph` 的顺序为：
`_jd_node → _evidence_node → _fit_node → _verdict_route_node`，通过门控后继续
`_resume_node → _interview_node → _answer_cards_node → _mock_interview_node`。
没有 LangGraph 时有显式等价 Python 执行路径；启用 semantic checkpoint 时按节点恢复。

`_evidence_node` 调的是 `agents/evidence_mapping.py:EvidenceMappingAgent.run`，
输出旧 `EvidenceMappingResult/EvidenceItem`。其 guard 验证 requirement 覆盖、重复 ID、禁词，
**没有 Evidence v2 的 source snapshot/hash/quote resolver 或确定性来源等级上限**。
这是仍被 CLI 和后端 semantic task 使用的兼容流程，不是死代码，也不能声称享有 v2 同等保证。

测试依据：`test_agent_graph_runtime.py`、`test_semantic_agents.py`、
`test_llm_agentization_runtime.py`、`test_agent_checkpoint.py`。

### 3. README 的 MCP/RAG 工作流确有实现，但独立于 UI 和普通 CLI

`job_search_workflow.py:JobSearchWorkflow.run` →
`memory_aware_job_analysis.py:MemoryAwareJobAnalysisService.analyze`：读取 `UserState`，
`RequirementAnalyzer` 生成要求，然后逐 atom 调
`GovernedCareerKnowledgeRuntime.query_candidate_evidence`。

后者使用脚本决策 `ScriptedAgentModel` 驱动受治理 `AgentLoop`，执行
`career.query_candidate_evidence`（通过 Registry 注册的 MCP bridge/adapter）。
并非每个检索动作都由 LLM 自主规划。

MCP 服务：`knowledge/career_mcp_server.py:create_career_knowledge_mcp_server` →
`CareerKnowledgeService.query_structured/query_candidate_evidence` →
`CandidateEvidenceRetriever` → `KnowledgeRetriever.retrieve` → embedding query → index.search。

取回 chunk 后，`RequirementEvidenceService.assess_atom_retrieved/assess_retrieved`：
按候选人来源白名单选择文档，核对 document version/hash/offset，保存 snapshot，调用
`RetrievedEvidenceMappingService.map` 逐候选判断 supported/partial/unsupported，
Python 将唯一引用转换为全局 SourceSpan 和等级。取最佳判断时只以 rank 作为同支持等级的 tie-break。
该接口不提供 contradictory 语义类别；不能把 UI mapper 的冲突能力推广到 RAG mapper。

`JobSearchWorkflow` 后续通过受治理 application tracking/lifecycle flow 更新本地状态；
进入面试阶段后调用 `JobSpecificInterviewPreparationService`。此流程有真实与 mock 测试入口，
不是 Streamlit 或 FastAPI 默认使用的统一服务层。

测试依据：`test_memory_aware_job_analysis.py`、`test_requirement_evidence.py`、
`test_retrieved_evidence_mapping.py`、`test_end_to_end_job_search_workflow.py`、
`test_real_model_end_to_end_validation.py`、`test_career_knowledge_mcp.py`。

### 4. 受限 AgentLoop

`agent_runtime/loop.py:AgentLoop.run`：恢复或初始化状态，模型产出 action/finish/input request，
按工具注册、权限、审批、预算执行，记录 observation/trajectory，验证 finish，保存 checkpoint。
`ToolRegistry` 校验输入输出 schema 和工具身份；`PolicyEngine.authorize` 要求 skill/agent/runtime
三个 allowlist 都通过，外部真实工具另有 allowlist，敏感读取拒绝。
审批绑定 action digest、session/run 和 request ID，不能修改参数后复用批准。
`ToolExecutor.execute` 再核对授权 digest，校验输入，执行受信 handler，校验输出。

`BudgetManager` 限制模型/工具调用、活跃时间、token/cost、重复查询和无进展；
等待用户时暂停活跃时间。timeout 是协作 deadline 和拒绝迟到结果，不能杀死任意阻塞 Python handler。
Checkpoint 保存 usage、pending action、已完成动作和非幂等 inflight 标记；不确定非幂等执行恢复时拒绝重放。

测试依据：`test_agent_loop.py`、`test_agent_policy.py`、`test_agent_budgets.py`、
`test_agent_tool_registry.py`、`test_agent_checkpoint.py`、`test_mcp_adapter.py`。

### 5. FAISS 持久化实际存在

`knowledge/faiss_vector_index.py:FAISSVectorIndex` 使用归一化 `IndexFlatIP`，有 add/search/save/load，
load 检查维度和 chunk 数。`InMemoryVectorIndex` 是另一种可注入的确定性测试实现。

`knowledge/durable.py:KnowledgeRepository` 使用 SQLite 保存文档版本、内容 hash、chunk、
active 状态与 ingestion run；`CareerKnowledgeLifecycle` 支持 ingest、delete、rebuild、load。
manifest 检查 embedding 身份/维度、schema/corpus 版本、文档/chunk 数、chunk ID 和索引 checksum。
`source_loader.py` 有 TXT/MD、PDF 和 DOCX loader（不是 OCR）。

`career_mcp_server.py:_service_from_environment` 在配置 `CAREER_KNOWLEDGE_DB_PATH` 时加载 durable
service；否则从 fixture corpus 重新构建内存中的 FAISS。默认不是托管向量数据库。

局限：整库重新 embedding/重建；索引与 manifest 分别替换，随后提交 SQLite，三者不是跨资源原子事务。
失败会留下不兼容快照，`load_index` 能拒绝，但需 rebuild 恢复；不能宣称分布式事务、在线并发写或自动恢复。
`knowledge_documents` 有 `(document_id, content_hash)` 唯一约束，而 `ingest_text` 只对当前版本去重，
历史 A→B→A 回退会再次 INSERT 相同 hash，存在失败风险；本次不擅自更改版本语义。
已创建 `CareerKnowledgeService.retriever` 是快照对象，生命周期修改后需重建/重新绑定 service，不能声称热更新。

测试依据：`test_knowledge_faiss_vector_index.py`、`test_durable_career_knowledge.py`、
`test_knowledge_ingestion.py`、`test_knowledge_ingestion_real.py`、`test_knowledge_candidate_evidence.py`。

### 6. 后端的持久化/恢复链是真实接线，业务流与 UI 有区别

`compose.backend.yml` 分别启动 `persistent_main:app` 和 `worker_main`。
`create_persistent_api_stack` 执行 migration，打开 `PostgresRunRepository`，构造 RunService。
创建 run 时由 repository 在事务内写 run/event/outbox；API 不直接把业务正文推到 Redis。
Worker main 调 `OutboxPublisher.publish_once` → Redis Streams；
`ReliableWorker.receive_and_process/process` claim + lease heartbeat + attempt fencing → 执行 adapter →
提交状态 → ack。`RecoveryCoordinator.run_once` 处理过期租约、丢失唤醒及 outbox reconciliation；
consumer reclaim 处理 PEL。`tool_operations.py` 有非幂等操作账本与 receipt/uncertain 边界。

`TaskRoutedExecutionAdapter` 区分 semantic job flow 和 application assistant。
前者 `SemanticJobExecutionAdapter` 调 `run_semantic_job_flow`，使用旧语义证据，
`worker_main` 当前为它注册的是 demo resume snapshot，不是 UI session。
后者 `build_application_assistant_loop` 使用 versioned CareerSnapshot 和 `ApplicationAssistantMockModel` 脚本控制器，注册 read_snapshot、
search_snapshot_text、write_sandbox_draft；搜索是文本行匹配，不是 Qwen/FAISS RAG，也不是 Evidence v2。
Postgres semantic/Agent checkpoint adapter 真实接在相应执行器中。

`backend_service/main.py`/`create_tracer_stack` 则是内存 tracer，不能混同持久化部署。
ConfiguredHeaderIdentityAdapter 是受信环境中的 header allowlist，不是完整用户认证系统。
本次不连接现有业务数据库，不执行 destructive integration fixture 的 TRUNCATE。

测试依据：`test_backend_service.py`、`test_backend_service_persistence.py`、
`test_backend_service_reliability.py`、`test_application_assistant_search.py`。

## 核心能力分级与风险

A=真实指定入口已调用；B=模块/独立工作流已实现并有测试但未接入 UI 主流程；
C=部分能力/保证；D=只有描述没有找到统一实现；E=明确边界缺陷或文档不一致。
同一功能可同时有入口分级和缺陷标签。

| 核心功能 | 状态 | 源码与测试证据 | 风险 | 建议 |
|---|---|---|---|---|
| UI 不可变来源、quote/hash/offset 校验 | A | sources.snapshot/read/resolve_locator；source_store/text_identity tests | 低 | 保留确定性约束 |
| UI JD 原子要求 | A/C | requirements._materialize；requirement_analyzer tests | 中 | 说明当前每候选一个 parent/atom，语义完整性仍靠 LLM |
| UI Evidence v2 直接材料映射 | A | pipeline.run → mapping.map；ui_live_runtime tests | 低 | 小规模材料继续直读 |
| Qwen/FAISS 检索与 MCP | B（独立 workflow 中 A） | career_mcp_server → career_service → retriever；career_knowledge_mcp tests | 中 | 写清入口，不强接 UI |
| FAISS 本地持久化/文档版本 | B/C | durable、faiss_vector_index；durable_career_knowledge tests | 中 | 保留；说明单机快照、失败后校验/rebuild |
| 索引 A→B→A、并发/跨资源原子性 | E/C | durable.ingest_text/commit_version/_publish_snapshot | 中 | 记录边界，单独设计版本回退与事务恢复 |
| 普通 CLI/LangGraph 语义证据来源 | A/C | graph_runtime._evidence_node → agents.EvidenceMappingAgent._guard | 高 | 明示 legacy 保证较弱，不宣传 v2 等价 |
| C1 与 C2/C3 上限 | A/E 已修 | level_policy.maximum_level；source_audit_regressions tests | 原高 | original_resume 不受 artifact 标签升级；raw_jd 上限 NONE；C1 确定性待确认 |
| 生成材料回流拦截 | A/E 已修 | sources._validate_input_policy；alias 回归 | 原高 | 标准化后检查 denied types |
| 下游 resume projection | A/E 已修 | projections.for_resume；冲突/待确认回归 | 原高 | 停止生成新事实，保留 interview 视图 |
| Pipeline prompt 版本审计 | E 已修 | pipeline.run；executed_prompt_versions 回归 | 原中 | 使用真实 prompt version 常量 |
| 无模型测试的可收集性 | E 已修 | qwen_embedding；延迟导入回归 | 原中 | 实际构造时才需要模型依赖 |
| Agent 工具治理/预算/审批/恢复 | A/B | loop、policy、budgets、checkpoint；对应 tests | 中 | 保留；timeout 与 token 计费不是强隔离/预授权硬上限 |
| FastAPI/PG/Streams/Worker/Outbox | A（持久化入口） | persistent_bootstrap、worker_main、reliable_worker；backend tests | 中 | 真实服务测试与内存测试分别报告 |
| UI→后端→MCP→Evidence v2 全统一主链 | D/E | 各入口调用关系未相连 | 高（表述） | 修改 README，不以架构图暗示已经统一 |
| 缺证据与无能力区分 | A/C | gap/unverified statuses；assessment._verdict_label | 中 | gap 只代表材料不足；不能用于能力否定 |
| RAG 冲突证据 | C | RetrievedCandidateEvidenceJudgment 仅三类；retrieved_mapping 优选单条 | 中 | 明示局限；不扩 schema 影响冻结评测 |
| 后端草稿权限名单遗漏 | E 已修 | application_assistant.APPLICATION_ASSISTANT_TOOLS；现有 application_evaluation 暴露 | 原高 | 补回 WRITE_SANDBOX_DRAFT_TOOL，保留审批与沙箱 |
| Application Assistant 评测工具集漂移 | E 已修 | application_evaluation._tool_selection_scores；task-tool 回归 | 原中 | evaluator-v2 区分 allowed/required；原数据与门槛不变 |

## 历史实验溯源

1. UI Evidence v5：`docs/evaluation.md` → `evidence/evaluation/pipeline_live_runner.py`，
   synthetic corpus、多变体 pipeline；不是 README 的 Qwen/MCP 检索评估。
2. README 的 20-query Dense/BM25/RRF 与 8-case Qwen：
   `knowledge/career_benchmark_compare.py`、`tests/test_real_model_end_to_end_validation.py`、
   `docs/evaluations/` 以及 synthetic fixtures。历史结果不能拿 mock 回归重新认证。
3. R12：`eval/unseen_career_holdout_v2/results-final.json`、`report.md`、manifest、gold audit、
   dedup report、stability。公开汇总有 17 jobs / 51 parents / 101 atoms，正例 42、负例 59。
   `_run_gold_atomic` 直接输入人工 gold atoms → Qwen 检索 top5、取 top3 →
   `real_atomic_evidence._judge_atom/_observations/_atom_metrics` → parent aggregation。
   这里的 judge 是独立评测实现，不等于 UI `EvidenceMappingService` 或生产 RAG mapper。
   `_run_end_to_end` 才从 raw JD 经 `MemoryAwareJobAnalysisService` 进入受治理 MCP 和生产 mapper。
4. `scripts/finalize_unseen_holdout_report.py` 直接保留 initial summary 中的 gold atomic 统计，
   合并两次技术续跑的 job results 重算 extraction/E2E；它不是重新跑模型。
   public report 声明 zero semantic retries/post-result gold edits；未读取私有原始记录，不能独立验证此声明。

可从公开数字重建 confusion matrix：TP=36、TN=58、FP=1、FN=6。
Accuracy=(36+58)/101=93.0693%；Supported Precision=36/(36+1)=97.2973%；
Supported Recall=36/42=85.7143%。这些是 **Gold Atomic Evidence 的历史实验**，
不能写成 UI/全系统端到端准确率。raw-JD E2E 完成 16/17，parent correctness=26/51=50.98%。
来源 precision=71.15%、recall=64.29% 也必须保留，quote/provenance validity=100% 不等于语义全对。

## 第二阶段候选方案与决策

| 方案 | 开发/测试成本 | 正确性风险 | 对冻结实验的影响 | 本次决策 |
|---|---|---|---|---|
| 扩充并统一 UI、RAG、后端到同一 mapper | 高；需适配来源、partial/contradiction、投影、checkpoint、UI 输入 | 高；可能削弱现有 quote/等级边界 | 需要新的独立实验，历史结果不再覆盖新链路 | 不执行大规模重写 |
| 保留实际独立入口，修正文档并修小边界 | 低到中；聚焦 guard/projection/版本/可选依赖 | 低；保守拒绝会减少可输出 claim | 不修改冻结数据/指标；语义成绩保留为历史 | 采用 |

原前提“持久化 FAISS 不存在”已被源码否定，因此不再重复实现索引。
本次执行：来源种类等级上限、标准化生成来源拦截、冲突/待确认 projection、
真实 prompt 版本、可选 embedding 导入及必要依赖声明。每项加针对性回归；
不调整 frozen eval、prompt 语义、数据标注、阈值或 metric 定义。

## 测试记录

当前本地 bundled Python 3.12.14 起初没有 pytest/FastAPI/LangGraph/Redis/psycopg/FAISS/Streamlit；
在仓库外 `work/audit-venv` 建立独立环境。安装测试依赖不触碰项目 `.env`。
本地没有配置真实 Qwen 模型或可用 GPU 模型运行环境；专用 PostgreSQL/Redis 端口未运行。
上述真实依赖的测试不记为通过。下面补充实际命令、数量、跳过和失败原因。

### 修改前实际测试（第一阶段完成时）

- `python -m pytest -q --junitxml=baseline-full.xml`：0 个测试执行，3 个收集错误；
  原因是三个 real embedding test 顶层导入未安装的 sentence-transformers，skipif 来不及生效。
- 排除这三个文件的早期广泛运行在长时间没有新增输出后被中断；无完整统计，不记为通过。
- 聚焦 14 个文件首次运行：74 passed / 1 failed，失败为 Windows 260 字符路径限制。
  另有两次 FAISS DLL 初始化收集错误，单列为沙箱环境问题。
- 使用短路径临时目录并在本地独立环境执行同样 14 文件：**75 passed / 0 failed**。
  命令由任务外置 `work/run_audit_tests.ps1 -Name baseline-focused-local -Focused` 保存；
  相应参数列表为本报告第三阶段所附测试清单。未修改生产代码或既有测试以获得此结果。
- 公开 R12 汇总算术检查通过：TP36/TN58/FP1/FN6；E2E parent 26/51。
  只核对公开汇总，未重跑模型或读取私人证据。

## 第二阶段：已实施的修改、原因与副作用

以下都是相对仓库根目录的路径。未修改冻结 eval 数据、标注、gold、prompt 语义或统计脚本。

| 文件 | 具体变更 | 原因 | 潜在副作用/边界 |
|---|---|---|---|
| `src/job_agent/evidence/level_policy.py` | raw_jd→NONE，original_resume→C1，不让 artifact 标签越过来源种类 | 防止简历标签被抬为 C2/C3 | 原先错误标记的高等级证据会被拒绝 |
| `src/job_agent/evidence/sources.py` | normalize_artifact_type 后再拒绝生成材料 | 避免空格/大小写/连字符绕过禁用类型 | 过去被错误接受的别名输入现在失败 |
| `src/job_agent/evidence/mapping.py` | C1 needs_confirmation 由 Python 强制 true | 不依赖模型自报“无需确认” | 已有序列化格式不变；新 C1 flag 更保守 |
| `src/job_agent/evidence/projections.py` | 冲突 atom 或待确认 link 不生成 resume claim；interview 仍保留 | 阻止下游省略风险 | 新简历事实可能减少；不修改 fit 阈值或历史评测 |
| `src/job_agent/evidence/pipeline.py` | manifest 引用实际 requirements/mapping PROMPT_VERSION | 使运行可解释与可追踪 | 新 manifest 版本字符串变化，字段不变 |
| `src/job_agent/knowledge/qwen_embedding.py` | 构造模型时才导入 sentence_transformers，缺依赖清楚报错 | 无模型环境也可收集/跳过模型测试 | 实际 embedding 算法及 query prompt 不变 |
| `src/job_agent/backend_service/application_assistant.py` | 补回沙箱草稿 WRITE 工具的三层 allowlist | 已注册但原本被拒绝，无法走到审批 | 现在可以请求审批；仍不能直接发送/写真实外部目标 |
| `pyproject.toml` | Python>=3.11（已有 datetime.UTC）；声明 MCP/FAISS/numpy 与可选 embedding 依赖 | 安装说明与真实 import 对齐 | 旧 Python 3.10 不再被元数据误称支持；可选依赖额外安装成本 |
| `tests/test_source_audit_regressions.py` | 17 个 synthetic 边界/版本/依赖/审批回归 | 先复现再修复；不读取私有 corpus | 没有真实模型语义新成绩 |
| `.gitignore` | 对新增审计测试添加精确例外 | 原 `tests/*.py` 会隐藏新测试，避免修复丢失回归 | 私有数据忽略规则不变 |
| `tests/test_ui_app_test.py` | 用仓库绝对 app 路径，临时 JOB_AGENT_OUTPUT_ROOT | 新 Streamlit 从调用文件解析相对路径；避免测试接触现有业务输出 | 保留原 assert，不删除或跳过测试 |
| `README.md` | 入口分流、FAISS 已实现能力与局限、指标分母与历史版本、环境依赖 | 消除统一链路和 E2E 指标误读 | 文档收紧声明 |
| `docs/resume_notes.md` | 按已接通/独立实验/不能宣称/历史指标重写 | 避免技术栈和成绩串用 | 简历措辞更准确 |
| `docs/architecture.md`、`docs/interview_notes.md`、`docs/evaluation.md` | 增加当前范围与历史材料说明 | 不让旧说明覆盖本次审计结论 | 历史结果原样保留 |
| `docs/INTERVIEW_SOURCE_GUIDE.md`、本报告、`docs/audit/` | 新增调用链、取舍、逐模块问答、测试证据 | 支持源码面试与中断恢复 | 不包含真实密钥/私人求职文本 |

## 第三阶段：实际测试命令与结果

执行根目录是本次任务目录（`agent-backend-service` 的上两级），实际 PowerShell 命令如下。
`run_audit_tests.ps1` 在测试前切换到本仓库，用独立 venv 的 Python，清空模型路径/真实凭证变量，
设置短 basetemp、`OMP_NUM_THREADS=1` 等原生库环境。它不修改评测断言。

```powershell
.\work\run_audit_tests.ps1 -Name baseline-focused-local -Focused
.\work\run_audit_tests.ps1 -Name regressions-before-fix -Files tests/test_source_audit_regressions.py
.\work\run_audit_tests.ps1 -Name regressions-after-fix -Files tests/test_source_audit_regressions.py
.\work\run_audit_tests.ps1 -Name regression-full
.\work\run_audit_tests.ps1 -Name regression-repaired-workflows -Files tests/test_source_audit_regressions.py,tests/test_application_assistant_evaluation.py,tests/test_end_to_end_job_search_workflow.py,tests/test_durable_career_knowledge.py,tests/test_ui_app_test.py
.\work\run_audit_tests.ps1 -Name regression-final
```

对应 Python 主命令是 `python -u -m pytest -vv --tb=short -o faulthandler_timeout=30`，
加本次独有 `--basetemp` 与 `--junitxml`；Focused 选择下面 14 个文件，Files 则按命令指定。

```text
tests/test_evidence_requirement_analyzer.py
tests/test_evidence_mapping_v2.py
tests/test_evidence_source_store.py
tests/test_evidence_level_policy.py
tests/test_evidence_projections.py
tests/test_evidence_fit_policy_v2.py
tests/test_evidence_artifact_repository.py
tests/test_retrieved_evidence_mapping.py
tests/test_knowledge_faiss_vector_index.py
tests/test_knowledge_candidate_evidence.py
tests/test_ui_live_runtime.py
tests/test_agent_policy.py
tests/test_agent_budgets.py
tests/test_agent_checkpoint.py
```

| 运行 | passed | failed | collection/setup errors | skipped | 解释 |
|---|---:|---:|---:|---:|---|
| 修改前全量收集 baseline-full | 0 | 0 | 3 | 0 | eager sentence-transformers 导入 |
| 修改前聚焦 baseline-focused-local | 75 | 0 | 0 | 0 | 现有测试基线 |
| 新增用例、修复前 | 1 | 15 | 0 | 0 | 16 个用例中 15 个复现问题 |
| 第一批修复后 | 16 | 0 | 0 | 0 | 新用例通过 |
| 第一次全量 regression-full | 506 | 5 | 13 | 50 | 包括 MCP 子进程缺 editable 安装、UI 测试路径、草稿名单和 Redis |
| 修复接线/环境后的相关回归 | 40 | 1 | 0 | 0 | 唯一失败是原 Application Assistant 工具 recall 定义漂移 |
| 最终全量 regression-final | **522** | **3** | **0** | **50** | 575 项；1 个 warning；并非全量通过 |

新增的第 17 个回归（沙箱 WRITE 仍需审批）在最终全量中通过。第一批红/绿结果是此前 16 个用例。
每个模块状态、准确耗时、问题名称和 skip reason 从 JUnit 解析到
[`audit/test-results.json`](audit/test-results.json)，环境版本见 [`audit/environment.json`](audit/environment.json)。

### 最终三个失败

1. `tests/test_application_assistant_evaluation.py::test_application_assistant_eval_runs_real_loop_approval_and_recovery`：
   原本 allowlist 缺 WRITE，导致 `application_eval_approval_missing`；修复后 24 个 case 的执行结果
   符合 expected outcome，审批/恢复/去重相关指标运行成功，但**整体 case 判定仍是 0/24**，
   因为 `application_evaluation.py:318` 将运行时 allowlist 的 3 个工具都当成必须调用，
   而默认脚本只使用 read+write，工具 recall=2/3；不能称为 24/24 评测通过。
   本次没有改统计公式、分母、gold 或控制器来迎合断言。
2. `tests/test_backend_service_reliability.py::test_provider_admission_enforces_fairness_cooldown_circuit_and_fail_closed`：
   测试直接访问 Redis，没有使用缺服务 skip fixture，连接 127.0.0.1:63799 被拒绝。
3. 同文件 `test_provider_admission_is_call_scoped_and_local_errors_do_not_open_circuit`：同样缺少 Redis。

### 50 个跳过（原测试条件）

- Phase 3 PostgreSQL 未运行：20；Phase 4 PostgreSQL 未运行：14。
- QWEN_EMBEDDING_MODEL_PATH unavailable：4；not set：3。
- DeepSeek durable-state acceptance 未显式 opt-in：4。
- DeepSeek agent eval opt-in/API_KEY 未提供：1；DeepSeek stateful eval：1。
- 本地模型显式 opt-in/QWEN2_5_MODEL_PATH 未提供：1；JOB_AGENT_REAL_MODEL_PATH unavailable：1；
  本地 stateful eval opt-in/model path 未提供：1。

上述真实模型、GPU embedding、PostgreSQL/Redis 持久化故障恢复均未在本次环境验证为通过。
FAISS 维度与保存/加载/重建、synthetic embedding、真实 MCP 子进程、规则与 mock 工作流、
quote/hash/offset、partial/gap、投影、工具权限/预算/文件 checkpoint 的可运行测试有实际通过记录。

公开 R12 汇总算术检查脚本在修复前后都通过，并对全部 `eval/` 文件做前后 SHA-256 比较一致。
这证明本次没有修改冻结评测文件，不是重新认证私有数据或重跑语义 benchmark。

## 第四阶段：文档与面试材料交付

- README 已区分所有入口；图只表示独立 RAG workflow，不再暗示统一 UI 主链。
- 持久化 FAISS 实际实现已保留，局限为单机快照/整库重建/不保证跨资源事务和并发写。
- `docs/resume_notes.md` 明确可以写的实现、只能标注的独立实验、不能宣称的能力与历史指标。
- `docs/INTERVIEW_SOURCE_GUIDE.md` 提供中文架构、完整调用链、源码函数/行号、LLM/Python 分工、
  取舍、指标分母和各模块 3～4 个源码追问/参考回答。

### 保留当前实现、需要另行决定的事项

1. **评测工具集定义**：建议以新 evaluator version 明确 allowed tools 与 required tools。
   不能直接把现有 recall 2/3 改成 1.0；需先固定新任务需求和 gold，历史报告保持不变。
2. **统一旧 DAG 与 v2/RAG**：需迁移 evidence schema、冲突、partial、来源等级、checkpoint 和下游生成。
   成本高，影响旧实验可比性；当前只完成如实文档与边界修复，不擅自重写。
3. **知识版本回退/并发事务**：需设计 A→B→A 的版本身份、快照发布失败恢复与 service 重绑定策略。
   当前失败可被拒绝加载，不能宣传完整自动恢复；本次不修改版本存储协议。
4. **真实基础设施回归**：需独立可丢弃 PostgreSQL/Redis 测试服务和 model-enabled 环境。
   不复用业务数据库，因为既有集成 fixture 会执行 TRUNCATE/FLUSHDB。

第一轮交付状态（历史记录）：522/3/50；没有将失败、未运行项或历史模型数字包装为新验证结果。

## 最终针对性收尾与架构冻结

本节为用户明确授权的最后收尾。没有新增业务功能、Multi-Agent、Milvus，
没有统一或重写 UI、CLI、RAG、后端入口。收尾后停止工程修改，下一阶段转为面试准备。

### 1. 三个失败的最终结论与处理

**两个 Redis 用例是缺服务。** 本地无 Docker/Redis 可用，在已授权服务器的全新 `/tmp/`
目录编译 Redis 7.4.6，仅绑定 loopback，另创建 PostgreSQL 14.24 临时实例。
未修改服务器原项目、系统软件安装或业务数据库；临时数据仅为 synthetic fixtures。
Redis 的真实 Lua、限流、公平性、熔断和 fail-closed 路径未被替换。
最初通过 SSH 隧道验证两个原失败用例，结果 **2 passed**。

进一步补跑 PG 故障测试时，SSH 往返约 0.2 秒超过部分用例的短租约/冷却窗口，
出现 7 failed / 43 passed。没有调大 timeout 或放宽断言；把同一份公开源码副本与服务同机运行后，
受影响的 PG/Redis/评测测试 **50 passed**。PostgreSQL 的 fsync 和 synchronous_commit 均为 on。
服务及其临时工作区已在保存结果后停止、删除；原业务项目未改动。

**工具 recall=2/3 是评测实现错误。** 三项独立依据：

1. `ApplicationAssistantMockModel.decide` 的任务轨迹是 read_snapshot → 批准 sandbox write → finish。
2. 冻结 24 场景的 schema 没有搜索要求；历史 Phase C 报告明确记录每个场景两次逻辑工具调用，
   合计 48 次，运行合同也只有 read/write。
3. 原 `_evaluate_case` 将 `APPLICATION_ASSISTANT_TOOLS`（3 项权限名单）直接用作 recall 分母，
   错把可选 search 当成必要动作。

只修改 `backend_service/application_evaluation.py` 的评测实现：

- `_REQUIRED_TASK_TOOLS={READ_SNAPSHOT_TOOL, WRITE_SANDBOX_DRAFT_TOOL}`；
- `_tool_selection_scores`：precision 仍按允许工具计算，recall 按任务必须工具的去重覆盖计算；
- 非法工具仍降低 precision，缺 read/write 仍降低 recall，重复调用不能提高 recall；
- 保留 `precision==1.0`、`recall==1.0` 和原审批、恢复、grounding、去重门槛；
- `read_observations` 使用明确的 READ 常量，不再依赖名单下标；
- 新运行标识 **application-assistant-evaluator-v2**。历史 v1 文件未覆盖，不把两个版本成绩混用。

`tests/test_application_assistant_evaluation.py` 新增 9 个用例：完整必要轨迹、可选 search、
漏必要工具、仅 search、重复 read、非法工具、空轨迹、扩展 allowed 集合不影响任务 recall。
原 24-case 回归及这 9 个用例合计 **11 passed**。24 个场景在 v2 下 **24/24**，
其中 20 个正常完成、4 个预期 UNCERTAIN，均为确定性脚本控制器合同测试，不是 LLM 准确率。

原任务数据与最初下载归档逐字节 SHA-256 相同，证据见
[`audit/closeout/frozen-task-check.json`](audit/closeout/frozen-task-check.json)。
R12、其他冻结 eval 文件和标注也未修改。没有更改 Agent 行为来补一个无必要的搜索步骤。

### 2. 实际执行命令与最终结果

Windows 本地（任务根目录，前轮独立 venv）：

```powershell
.\work\run_audit_tests.ps1 -Name closeout-evaluation -Files tests/test_application_assistant_evaluation.py
.\work\run_audit_tests.ps1 -Name closeout-redis -Files tests/test_backend_service_reliability.py::test_provider_admission_enforces_fairness_cooldown_circuit_and_fail_closed,tests/test_backend_service_reliability.py::test_provider_admission_is_call_scoped_and_local_errors_do_not_open_circuit
.\work\run_audit_tests.ps1 -Name closeout-backend -Files tests/test_backend_service_persistence.py,tests/test_backend_service_reliability.py,tests/test_application_assistant_evaluation.py
```

Linux 隔离副本实际执行（`run_tests.py` 设置源码路径、短临时目录、关闭插件自动加载，
移除模型 opt-in 和真实凭证变量；实际 Python 参数完整保存在 command JSON）：

```bash
venv/bin/python run_tests.py closeout-backend-colocated tests/test_backend_service_persistence.py tests/test_backend_service_reliability.py tests/test_application_assistant_evaluation.py
git -C agent-backend-service init -q
venv/bin/python run_tests.py closeout-full-final
```

全量底层命令为 `python -u -m pytest -vv --tb=short -o faulthandler_timeout=30`，
加隔离 basetemp/JUnit 路径，无 ignore/deselect。源码归档不含 `.git` 历史，首次全量有一个
`git check-ignore` 环境错误（567 passed / 1 failed / 16 skipped）；只在隔离副本执行 `git init`
后重跑，得到最终结果，没有改测试。

| 收尾运行 | passed | failed | skipped | 说明 |
|---|---:|---:|---:|---|
| 评测修正及负向回归 | 11 | 0 | 0 | 原 2 个测试 + 新增 9 个用例 |
| 两个原 Redis 失败 | 2 | 0 | 0 | 真实 Redis，经隧道 |
| 跨主机后端回归 | 43 | 7 | 0 | 延迟超出短窗口；保留记录 |
| 同机后端与评测回归 | 50 | 0 | 0 | 原门槛、原时间设置 |
| 最终全量 | **568** | **0** | **16** | 共 584 项，33.778 秒，无警告 |

完整 JUnit、日志、实际命令、服务/依赖版本和已测源码 hashes 存放在
[`audit/closeout/`](audit/closeout/closeout-full-final.xml)。
最终环境是 Python 3.11.15/Linux、PostgreSQL 14.24、Redis 7.4.6；
不是仓库 Compose 中 PostgreSQL 16 镜像的完整部署验收。已测源码 hash 与本地交付源码一致。

另运行实际评测脚本（非真实模型）：

```powershell
$env:PYTHONPATH='.;src'
python scripts/evaluate_application_assistant.py --output-dir C:\Users\1\Documents\Codex\2026-10-18\ssh-p-27392-root-192-168-2\work\ce
```

报告见 [`application-evaluator-v2.json`](audit/closeout/application-evaluator-v2.json)。
该 JSON 是新 v2 的确定性结果，与历史 R12 语义成绩完全分开。

### 3. 原 50 个跳过与剩余验证缺口

| 分类 | 原数量 | 收尾处理 | 最终状态 |
|---|---:|---|---|
| PostgreSQL 环境缺失 | 34 | 新建隔离真实 PG/Redis，同机跑原测试 | 原 34 项现在全部执行通过 |
| Qwen embedding 路径未配置 | 7 | 保留原 skip 条件，不下载/替换模型 | 7 skipped，真实 embedding 仍未重验 |
| DeepSeek live 显式 opt-in | 6 | 4 durable + 1 agent + 1 stateful；未启用真实凭证/调用 | 6 skipped，真实决策验收未重验 |
| 本地 Qwen generation 显式 opt-in/路径 | 2 | 未启用 agent/stateful 真实模型运行 | 2 skipped |
| 真实模型 E2E generation path | 1 | JOB_AGENT_REAL_MODEL_PATH 未配置 | 1 skipped |

剩余逐项名称、原 skip reason 见 [`remaining-skips.json`](audit/closeout/remaining-skips.json)。
这些是条件性测试，而非被删除的失败；它们同时构成本轮真实模型/外部 provider 集成验证缺口。
GPU 或依赖安装存在不等于已跑模型测试。不能宣称所有真实模型测试通过，不能宣称新 R12 成绩。

已通过：确定性来源校验、要求/映射合同、投影、FAISS 本地持久化/维度/重建、MCP 子进程、
权限预算与 checkpoint，以及实际 PG/Redis 上的事务、Outbox、租约/fencing、恢复、审批、receipt/UNCERTAIN。
未完成：16 项真实模型条件测试、PostgreSQL 16 Compose 全部署与生产负载/外部副作用验收。
UI/RAG/CLI/后端保持独立边界，不声称已统一接通。

### 4. 冻结交付

最终建议简历与每条能力的源码映射见 [`resume_notes.md`](resume_notes.md)。
完整 JD 调用链及逐模块问答见 [`INTERVIEW_SOURCE_GUIDE.md`](INTERVIEW_SOURCE_GUIDE.md)。
完整当前代码包包括源代码、测试、文档及公开 fixtures，排除真实 `.env`、私人材料、Git 历史、
虚拟环境、数据库和运行输出；包内 manifest 提供逐文件 SHA-256。
测试临时服务已经关闭。至此停止工程修改，不自动开启新一轮开发。

## 新一轮升级：2026-10-20，M1 结构化简历与版本

用户明确撤销此前仅做面试准备的范围限制，要求升级为完整长期求职产品，涵盖单次简历优化/PDF
与后续岗位、投递、面试历史。用户无需编写代码，由助手实现并逐步解释问题、方案、收益与限制。
完整目标与分步验收见 [升级路线](upgrade/ROADMAP.md)。旧冻结源码包和实验结果保留。

### 当前实际交付

| 文件 | 本轮变更 | 风险和边界 |
|---|---|---|
| `src/job_agent/resume_workspace/contracts.py` | 统一结构化个人信息/教育/经历/项目/技能；字段关联来源 span；版本、确认合同 | 只接收抽取事实；不是任意语义改写，也不证明用户经历的现实真实性 |
| `src/job_agent/resume_workspace/repository.py` | 来源 hash/owner/kind/原文范围校验；事务保存、CAS 父版本、不可变版本、确认、恢复与删除 | SQLite 本地增量，不是 PG 产品迁移；新表不与既有状态双写 |
| `src/job_agent/resume_workspace/api.py` | 服务端 token 身份解析；来源和版本 API；跨用户 404；验证错误不回显私密值 | 单独 API 工厂，未接入旧 v1 后端/Worker 或新前端 |
| `src/job_agent/resume_workspace/main.py` | 环境中私有 bearer token 的本机启动器；默认 loopback | 单用户开发入口，不能称完整生产登录系统 |
| `scripts/demo_resume_versions.py` | 合成材料版本确认、重排、恢复、持久化重开演示 | 无模型，无完整产品 UI，不使用私人数据 |
| `tests/test_resume_workspace.py`、`.gitignore` | 新增 34 项边界/API 测试，明确保留新测试文件 | 未删除、更改旧测试或降低评测门槛 |
| `docs/upgrade/`、README、现有指南/简历说明 | 区分升级目标、已实现 M1、历史基线；解释源码和取舍 | 不把目标架构写成已经接通 |

新增数据流：`create_resume_app` 服务端识别 owner → `SourceCreate` 规范化来源 → `add_source`
保存 hash → `ResumeDocument` → `_validate_document` → `_append` 事务保存 → `confirm_version`
绑定版本/hash → `save_version` 带当前父版本 → `restore_version` 新增历史版本。
全部确定性 Python 逻辑。原始简历/用户补充只提供自述事实，确认不升为 C2/C3。
JD 和参考资料来源被拒绝进入个人事实字段。旧 `EvidenceV2Pipeline` 和其他生产逻辑未改。

### 本轮验证（独立于旧 568/0/16）

| 范围 | passed | failed | skipped |
|---|---:|---:|---:|
| 开发增量前，既有来源/长期状态/应用评测聚焦回归 | 33 | 0 | 0 |
| 新增简历版本测试 | 34 | 0 | 0 |
| 新增 + 既有证据/状态/后端合并回归 | **110** | **0** | **0** |

第三行包含前两行中的用例，不能相加成测试总数。新增/API 回归有一项 Starlette/AnyIO 弃用警告。
首次受限沙箱运行在 Windows asyncio 本机 socketpair 创建时阻塞并被中断；
在允许 loopback 的环境原样重跑通过，未修改或跳过 API 测试来规避环境问题。

实际命令（任务根目录）：

```powershell
.\work\run_audit_tests.ps1 -Name upgrade-m1-existing-before -Files tests/test_source_audit_regressions.py,tests/test_career_store.py,tests/test_application_assistant_evaluation.py
.\work\run_audit_tests.ps1 -Name upgrade-m1-tests-network -Files tests/test_resume_workspace.py
.\work\run_audit_tests.ps1 -Name upgrade-m1-regression -Files tests/test_resume_workspace.py,tests/test_source_audit_regressions.py,tests/test_career_store.py,tests/test_application_assistant_evaluation.py,tests/test_backend_service.py,tests/test_evidence_source_store.py,tests/test_evidence_mapping_v2.py,tests/test_evidence_projections.py,tests/test_evidence_requirement_analyzer.py
```

另在项目目录执行 `python scripts/demo_resume_versions.py --output-dir ../../work/upgrade-m1-demo`，
6 项版本检查全 true；通过 `work/smoke_resume_http.py` 启动本机 Uvicorn，8 项真实 HTTP 检查全 true，
最后关闭临时服务。无真实模型、外部 API 或私人简历调用。
日志、JUnit、运行环境、等价 pytest 命令、合成报告与新增源码 hashes 保存在
[`audit/upgrade-m1/verification.json`](audit/upgrade-m1/verification.json)。
25 个公开 `eval/` 文件与旧冻结包 hashes 相同，没有修改历史评测数据/标签。

未运行：本轮全仓库真实 PG/Redis 回归；新产品 LLM/embedding/OCR/ES/PDF/React E2E；
产品 PG 迁移与生产鉴权。后续 M2 首先接文本/PDF/DOCX 导入、结构化解析与用户核对界面，
再按路线逐步接匹配、建议、PDF、长期状态和任务/检索集成。

源码学习、设计取舍和 5 个参考问答见
[`upgrade/01_STRUCTURED_RESUME.md`](upgrade/01_STRUCTURED_RESUME.md)。此处是阶段交付，不是完整升级已完成。

## 新一轮升级：M2 导入、解析与 React 编辑工作台

本轮用户同意继续第二步。产品目标未改变：先接通可用增量并解释源码，不提前宣称统一多 Agent、
检索、PDF 或长期投递闭环已经完成。

| 文件 | 实际变更 | 原因与剩余边界 |
|---|---|---|
| `resume_workspace/ingestion.py` | 5 MB 上传、TXT/MD/PDF/DOCX 抽取，PDF 页数/加密/无文字检查，DOCX 展开限制 | 复用已有 loader；未实现 OCR、复杂版式保证或解析进程硬隔离 |
| `resume_workspace/parsing_contracts.py`、`fields.py` | 不完整草稿、候选字段、人工核对合同和字段路径白名单 | 缺失先提问；不能让模型写任意属性/来源等级 |
| `resume_workspace/parsing.py` | 本地规则与可选模型解析；exact quote/offset 校验；最多两次总调用（修复一次）；provider/model/version/usage 元数据 | 模型接口接通，真实模型质量未验收；不把规则冒充模型 |
| `resume_workspace/repository.py` | 原始附件/hash/元数据、草稿持久化、接受幂等、补充来源、局部编辑、来源列表和删除保护 | 用户操作事务化，原文与补充不混淆；本地 SQLite，未接旧 Worker/PG |
| `resume_workspace/api.py`、`main.py` | 导入/解析/草稿/编辑 API；在线处理显式同意；同源前端构建；私有口令启动 | 不暴露 Key/私人错误值；生产身份/跨进程任务仍待验收 |
| `frontend/` | React 简历上传/粘贴、原文引用定位、表单编辑、补问、确认/恢复、来源管理；响应式布局；锁文件 | 同一产品界面接通 M1；岗位/面试菜单明确待接入；未借展示假装后端已统一 |
| `scripts/demo_resume_workbench.py` | 独立 loopback 合成演示，临时库、固定公开演示口令、无模型配置 | 演示与私人工作区隔离；正常退出清理数据，非生产登录系统 |
| `tests/test_resume_import.py`、`.gitignore`、`pyproject.toml` | 新增 38 项测试；声明 workbench 的 PDF/DOCX 可选依赖；忽略 Node 构建缓存 | 未改变冻结标签、旧指标定义或原测试条件 |
| README、指南、简历说明、`upgrade/02_IMPORT_PARSE_EDITOR.md` | 新增可启动 Demo、实际调用链、取舍和问答；区分真实模型未验收与已测合同 | 保留旧 568 和 R12 的历史范围 |

执行链：React `App.parse` → `api.import_file` / `add_source` → `extract_upload` → 既有 `load_source`
→ `save_upload` → `parse_source` → `ResumeParser.parse` → `local_candidates` 或 `LLMHarness.invoke_structured`
→ `materialize` 校验引用与字段 → `save_draft` → 用户核对 → `accept_draft` / `_apply_edits` / `_append`
→ `confirm_version`。局部编辑使用 `edit_version`。本轮未修改旧 Evidence v2、CLI/RAG、Worker 的业务执行链。

### 实际测试与演示

| 运行 | passed | failed | errors | skipped |
|---|---:|---:|---:|---:|
| M2 修改前聚焦回归 | 40 | 0 | 0 | 0 |
| 初次导入/M1 回归 | 65 | 0 | 2 | 0 |
| 修正参数显示 ID 后，同一输入/断言回归 | 66 | 0 | 0 | 0 |
| 增加边界后合并回归 | 153 | 0 | 0 | 0 |
| 最终合并回归，含演示隔离测试 | **154** | **0** | **0** | **0** |
| 前端数据转换与 Unicode 单元测试 | **4** | **0** | **0** | **0** |

首次 2 errors 来自大文件测试参数生成超长 ID，触发 Windows `PYTEST_CURRENT_TEST` 环境变量
32767 字符限制；给参数设置短名称，文件仍为 5 MB + 1 byte、原断言不变。没有改产品限制来凑通过。
一项旧 Starlette/AnyIO 弃用警告保留。各行有重叠，不能累加。

最终后端命令（任务根目录）：

```powershell
.\work\run_audit_tests.ps1 -Name upgrade-m2-final-demo -Files tests/test_resume_import.py,tests/test_resume_workspace.py,tests/test_source_audit_regressions.py,tests/test_career_store.py,tests/test_application_assistant_evaluation.py,tests/test_backend_service.py,tests/test_evidence_source_store.py,tests/test_evidence_mapping_v2.py,tests/test_evidence_projections.py,tests/test_evidence_requirement_analyzer.py,tests/test_knowledge_ingestion.py
```

前端目录执行 `npm install --ignore-scripts --no-fund` 生成锁文件；之后执行 `npm test`、`npm run build`。
实测 Node 24.19.0、React/React DOM 19.3.1、Vite 8.3.4。默认 npm 镜像审计端点不支持，
改用 `npm audit --json --registry=https://registry.npmjs.org` 检查同一锁文件，报告本次 0 个已知漏洞。

实际浏览器验证粘贴/解析/补充/保存/确认/编辑/恢复；上传无姓名合成 DOCX，缺失拒绝后补充保存；
刷新重新连接后保留版本，来源管理显示引用保护；桌面 1280px/窄屏 390px 及 Unicode 引用检查通过，
最终检查后重置视口。没有把这些手工浏览器步骤虚报成自动测试数量。
正式交付的 `demo_resume_workbench.py` 也实际启动并重复完成主要版本流程，明确显示模型关闭和临时演示。
最终保留 `http://127.0.0.1:8012/` 演示供用户体验；它只在本机运行、仅有合成材料。

日志、JUnit、最终构建、前端测试、安全审计、来源 hashes 与截图见
[`audit/upgrade-m2/verification.json`](audit/upgrade-m2/verification.json)。
没有运行真实模型/embedding/OCR/ES/PDF 或新的 PG/Redis 产品集成，也未重跑全仓库真实服务回归。
25 个公开 eval 文件与冻结基线保持相同；没有产生新模型 benchmark。

阶段说明、运行步骤、逐函数链路和面试解释见
[`upgrade/02_IMPORT_PARSE_EDITOR.md`](upgrade/02_IMPORT_PARSE_EDITOR.md)。下一步是 M3 JD 匹配与受限建议。

## 用户协议接入与 M1/M2 文档补录（2026-10-20）

用户要求把提供压缩包的留痕协议用于后续开发，并补齐已完成的两步。已将原协议写入根
`AGENTS.md`，新增 [`CONTINUE_DEVELOPMENT.md`](CONTINUE_DEVELOPMENT.md)、
[`devlog/INDEX.md`](devlog/INDEX.md)、两份 10 节阶段报告、当前架构图和 8 项重要决策。
六份原始文档的全文和 hash 在 `devlog/PROTOCOL_SOURCE.md` 保留。

M1/M2 是事后补录；原阶段开始时的完整 Git 状态未记录，明确标为未核实。补录核验
`main`/`067bfc7d63408e1e6b0ab6c227e863bd08a5857a`，未提交；提供原源码包 manifest 对比和代码 diff，
不伪造提交历史。默认模板的第二阶段是 JD，本项目第二步是导入/编辑，已明确映射，JD 为计划第三步。

核对原 M2 首轮 JUnit 时纠正汇总 JSON 的 64：共有 66 个唯一用例，65 通过，1 个用例
setup/teardown 产生 2 个 error 事件；旧的简单相减公式错误。原 JSON 备份、原 JUnit hash 和
修正依据见 `devlog/evidence/summary-reconciliation.json`。原始日志/测试/冻结 eval 不改，最终 154 项通过结果不变。

本轮只做文档/协议/汇总准确性和交付包工作，未重新运行业务回归、真实模型或真实服务测试。
校验依据在 `devlog/evidence/backfill-validation.json`：源码锚点、相对链接、模板章节、协议完整保留、
M1/M2 历史证据与当前业务源码未改。后续开发按继续手册和根协议执行。

## 2026-10-20：M2A 普通 PDF 自动填表

已有 pypdf 导入不是缺失功能，实际问题是本地结构解析依赖标签/管道。新增保守结构定位、上下文/歧义保护及 UI 字段统计；原件、逐字引用、owner/kind/hash/offset、核对和版本接口保留。
最终相关回归 174 passed / 0 failed / 0 skipped（新增 20）；前端 6/0/0、构建与合成 PDF 浏览器上传/核对/无补填保存通过。未重跑全仓库、真实模型、OCR、生产 PG/Redis。
初轮临时目录/沙箱通信失败、3 个解析失败及一次错误测试路径均记录，未删除失败用例或改冻结数据。
源码/调用链/学习路线/限制见 [PHASE-02A](devlog/PHASE-02A-pdf-autofill.md)，实际日志与环境见 [verification](devlog/evidence/m2a-verification.json)。

## 2026-10-20：M3 首个 JD 产品闭环

当前版本/JD 快照、既有 Evidence 内核适配、本地预检查/可选模型接口、原文查看、受限排序接受拒绝已接新 React。无新事实生成，C1 不升级，旧源校验/投影/冻结评测不改。
阶段前 174/0/0；最终相关 **201 passed / 0 failed / 0 skipped**（新增 27），前端 **9/0/0**、构建、真实合成浏览器和 15 项本机 HTTP 通过。首轮新测试方法名写错导致 1 失败已修正，断言保留。
来源/调用链/决策/学习路线见 [PHASE-03](devlog/PHASE-03-match-and-rewrite.md)，命令/环境/hash 见 [verification](devlog/evidence/m3-verification.json)。真实模型质量、自由改写、C2/C3 产品输入、RAG/Worker/PDF/全仓库回归未验收。

## 2026-10-20：协作式多 Agent 建议评审（仅文档）

用户要求评审两条有界反馈闭环。核实现有主图/动态面试/规则评估追问/新 M3 各自边界；原型建议、拟议实验与已实现能力分开记录。见 [协作方案评审](devlog/COLLABORATION_DESIGN_REVIEW.md) 和继续手册第 9 节。未改业务源码，未重跑测试，未将协作或收益标为已完成。

## 2026-10-20：M3B 最终审计与交付

用户随后同意实施协作；上一节“仅文档”是先前评审状态。当前已完成摘录动作的本地闭环，未替换旧 Evidence/AgentLoop/Worker。

| 功能 | 状态 | 代码依据 | 风险/处理 |
|---|---|---|---|
| 原文摘要协作和轨迹 | A，React/API 规则闭环；在线合同已测 | collaboration.py::CollaborationEngine.execute、CollaborationPanel.jsx | 中：规则不代表模型语义或质量收益 |
| 全句/路径/重复/容量/来源硬门 | A | collaboration.py::hard_review、repository.py::_validate_document | 容量 distinct-count Bug 已修；现实真实性仍待核对 |
| 稿件与版本审批幂等 | A | collaboration_repository.py::CollaborationRepository.decide | 旧稿、head 变化、并发接受均测试；新版未确认 |
| 应用 checkpoint/lease/未知调用停止 | A，本地合同；生产 C | collaboration_repository.py::claim/checkpoint、collaboration.py::execute | 非原生 saver/Worker，未知模型不自动重放 |
| 自由润色、面试协作、对照提升 | D，计划 | 方案评审/PHASE-03B | 未实现或未实验，不作简历已完成项 |

改动：新增 collaboration.py/contract/repository/api 四文件（前缀 src/job_agent/resume_workspace/）；api.py 安装路由；新增前端面板/状态帮助函数、main.jsx 独立 key 和样式；42 个合成新测试；独立 HTTP 验证脚本。未改旧证据语义、冻结标签或评测公式。
潜在影响：每个新工作台 app 新建两张 SQLite 表并导入既有 LangGraph；在线同步最多六次预留调用，长任务需查看历史，可能超过页面等待时间。schema 不变，无新外部依赖。
实际结果：先201/0/0，后243/0/0；前端11/0/0、构建、合成浏览器/17 HTTP。首轮容量测试35/1→修正36/0；首轮日志被覆盖，只保留当时执行输出记录。另修浏览器重复 key；一次 Vite 参数错误日志保留。
完整命令/源码锚点/限制/学习/五题问答见 [PHASE-03B](devlog/PHASE-03B-writer-reviewer.md)；环境、JUnit、hash 与实际 Git 在 [verification](devlog/evidence/m3b-verification.json)。未跑全仓库、真实模型/生产 PG/Redis 或质量对照。

## 2026-10-20：M3C 核验分层与面试协作收尾

用户明确授权两项，已在新React/API完成本地闭环；旧内核与入口不重写。

| 核心功能 | 状态与依据 | 风险/建议 |
|---|---|---|
| 核验分层 | A：collaboration_repository.py::_view、ProposalVerification、CollaborationPanel | C1 not_verified独立于接受/确认；4个新后端测试 |
| 岗位→面试快照 | A：MatchingPanel/InterviewPanel、interview_repository.py::start | JD与match完全一致；面试当前版单独绑定，不继承旧版支持结论 |
| Evaluator→Interviewer反馈 | A：规则入口；在线合同已测；interview_collaboration.py::InterviewEngine.execute | 六anchor技术题库，真实语义质量与收益未验 |
| 活动防泄题/结束复盘 | A：interview_repository.py::get/review/finish | 明确公开投影，未结束409，结束后不能继续；非只前端隐藏 |
| 状态/幂等/租约 | A：本地合同；生产集成C，answer/claim/checkpoint | 应用checkpoint，未知模型不重放；非原生saver/Worker/exactly-once |
| 完整PDF/长期投递/任意岗位面试 | 尚未完成 | 保留产品路线，不将有限技术练习称完整系统 |

修改：新增resume_workspace/interview_contracts.py、interview_collaboration.py、interview_repository.py、interview_api.py；api.py接路由；协作contracts/repository增加只读核验视图；前端Matching/Collaboration/main及新InterviewPanel、样式/状态；测试与HTTP脚本。
副作用：新工作台新增两张SQLite表、加载既有题库/旧评估模块；在线每答最多两次，最多12次模型预留。同步HTTP可能超页面等待时间；同键返回状态，不自动重发。没有新外部依赖或旧事实格式迁移。
实际先257/0/0，最终291/0/0（34新增），前端13/0/0、构建、合成浏览器/刷新历史通过；HTTP活动14/14、结束15/15含重叠公共项。未跑全仓库/真实模型/PG/Redis生产服务/质量对照，未改冻结标签与旧指标。
源码/10节复盘/学习路线/5题见 [PHASE-03C](devlog/PHASE-03C-verification-interview.md)，真实JUnit/命令/环境/hash见 [verification](devlog/evidence/m3c-verification.json)。
