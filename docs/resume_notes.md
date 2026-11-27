# 简历表述与源码一致性

## V3最终建议口径（2026-10-21）

三条版：
- 基于React、FastAPI与LangGraph实现长期求职工作台，贯通简历解析核对、JD分析、局部改写审批、不可变版本、中文PDF与投递记录；保留原文来源和事实等级，用户接受不替代独立核实。
- 实现公共技术题库与项目Code-aware检索，支持安全ZIP/公开GitHub固定版本导入、Python AST及JS/TS Tree-sitter符号/静态引用索引，按快照/hash/文件行号核验引用；将真实只读检索工具接入项目面试。
- 设计Writer↔Reviewer与Interviewer↔Evaluator有界反馈，工具权限/预算/重复调用控制、活动答案隔离；实现SQLite持久后台索引、租约fencing与幂等恢复，并用公开源码进行独立Worker故障验证。

五条版：
- 基于React、FastAPI与Pydantic搭建长期求职工作台，实现文档解析核对、JD分析、不可变简历版本、人工确认和双模板中文PDF，保留原文引用与用户补充血缘。
- 使用LangGraph实现Writer↔Reviewer局部改写反馈，约束新数字、技术与职责扩大，有限轮次修订后由用户审批，区分来源校验、语义支持和现实真实性。
- 建立原创公共技术题库与私人项目Code-aware检索，支持ZIP/公开GitHub固定版本安全导入、Python AST与JS/TS Tree-sitter解析、符号/静态引用索引和文件行号校验。
- 将受权限、调用预算与指纹约束的真实只读工具接入Interviewer↔Evaluator反馈，支持岗位、源码和薄弱项练习，展示检索目标改变、代码/测试引用和活动参考答案隔离。
- 实现SQLite持久后台索引、请求幂等、租约心跳与事务fencing，完成公开源码的独立Worker故障恢复验证；保留检索对照负结果、环境失败及模型质量待验范围。

以上不得添加真实用户量、生产规模或未经验证的模型提升率。

能力→源码：产品main.jsx/api.py；来源版本repository.py；Evidence适配matching.py；自由改写提案rewrite.py；PDF pdf_export.py；源码code_parser/code_rag/github_import.py；公共知识public_knowledge.py；协作retrieval_interview/interview_tools/interview_collaboration.py；恢复tasks.py和interview_repository.py；岗位long_term.py。以上文件均在src/job_agent/resume_workspace（前端除外）。

可放心讲的是已测试的本地产品/来源校验/实际工具机制/CPU静态检索/本地故障恢复。Qwen/FAISS/MCP与PG/Redis应写“独立模块实践”，不能说所有产品入口都使用。OCR受环境阻塞；Elasticsearch/Milvus/Neo4j/Reranker/私库/OIDC/生产部署不能宣称已接入。

指标：40合成冻结代码题下flat和code_aware文件Recall@5都1.00，MRR .75/1.00，只能按分母讲定位对照，不能宣传召回提升；公共标签诊断不是语义准确率。全量855通过/2 Redis失败/50条件跳过，不能写全量全过。历史R12的93.07%/97.30%保留17JD/101原子旧范围；V3模型质量、真实协作收益和人工教学评审LIVE_PENDING。

下文保留旧审计口径；遇到“尚未接通”以本节和FEATURE_MATRIX当前范围为准，不删除旧实验来源。

依据 2026-10-18 本地源码审计。调用链与限制见
[INTERVIEW_SOURCE_GUIDE.md](INTERVIEW_SOURCE_GUIDE.md)，实际测试与未解决项见
[PROJECT_AUDIT.md](PROJECT_AUDIT.md)。历史实验成绩不能描述成当前修复后的新成绩。

最终收尾：568 passed / 0 failed / 16 skipped（Linux 隔离 PG/Redis 环境）。
这是上一轮冻结基线的成绩。2026-10-20 启动新产品升级，新增的结构化简历/来源/版本 API 是本地增量，
尚未完成产品集成，不沿用 568 或 R12 作为新产品成绩。详见 [升级说明](upgrade/01_STRUCTURED_RESUME.md)。

M1 可新增的能力表述：“实现结构化简历及不可变版本 API，保存前校验用户来源、hash 与字符引用，
通过父版本检查避免并发覆盖，支持指定版本确认及恢复。”对应 `resume_workspace/contracts.py`、
`repository.py`、`api.py` 与 `tests/test_resume_workspace.py`。

M2 已进一步接通 React 与导入/解析/编辑，可写：“基于 React + FastAPI 实现简历工作台，支持文本、
PDF/DOCX 导入、字段原文核对、人工补充与版本确认；解析模块使用结构化输出和字段路径/引用校验，
限制模型调用次数，失败不静默替换为规则结果。”源码：`frontend/src/main.jsx`、`resume_workspace/ingestion.py`、
`parsing.py:ResumeParser.parse/materialize`、`repository.py:accept_draft/edit_version`。
当前验收是 154 项后端相关测试、4 项前端测试及合成浏览器流程，**不是模型准确率**；真实模型未调用。
不能写成四角色完整产品、OCR/ES 已接通、完整 PDF 闭环或 PostgreSQL 产品迁移完成。
详见 [M2 源码与演示](upgrade/02_IMPORT_PARSE_EDITOR.md)。

## 可以写成实现的技术

- **Evidence v2**：不可变来源快照、SHA-256、唯一原文引用解析、字符 offset、来源等级上限、
  C1 与 C2/C3 区分、面向简历/面试的不同投影。桌面 UI 直接处理少量原始材料，未调用向量检索。
- **受治理 AgentLoop**：schema、三层 allowlist、action digest 绑定审批、预算、协作 deadline、
  trajectory、checkpoint/resume、不确定非幂等执行拒绝重放。按入口区分 LLM 决策与脚本控制器。
- **单机知识模块**：Qwen embedding 接口、FAISS IndexFlatIP、SQLite 文档版本、manifest/checksum/
  dimension 校验和显式索引重建。可描述“实现持久化知识模块”，不能说所有入口已接入。
- **异步任务后端实现**：FastAPI、PostgreSQL Run/Event/Outbox、Redis Streams、Worker lease/heartbeat/
  fencing、恢复和操作 receipt。相关事务、故障与恢复测试已在隔离真实 PG/Redis 上通过；
  不代表 PostgreSQL 16 Compose 全部署或生产 SLA。

## 只能标注为独立模块或实验

| 技术/数字 | 允许的范围 |
|---|---|
| Qwen3 + FAISS + MCP | 独立 `JobSearchWorkflow/MemoryAwareJobAnalysisService`，不等于桌面或后端默认路径 |
| Dense/BM25/RRF 对比 | 历史固定 20-query corpus 比较，不能推广为新语料优劣结论 |
| Qwen2.5 的 8-case 验证 | 历史 synthetic 场景；本次未重跑真实模型 |
| 93.07% / 97.30% | R12 历史 Gold Atomic Evidence；人工提供 101 atoms，TP36/TN58/FP1/FN6 |
| LangGraph | 旧语义 DAG 调度；不是所有 AgentLoop 或 Evidence v2 的运行引擎 |
| Application Assistant | 脚本决策 + 沙箱草稿/审批/恢复合同，不是完整自主 LLM 投递系统 |

## 目前不能宣称

- 桌面、CLI、RAG 和异步后端已统一接成完整生产系统。
- C1 简历叙述经过第三方验证，或引用有效就代表经历/语义必然真实。
- RAG mapper 有完整 contradictory evidence 支持。
- 所有输入都严格拆成最小 atom，或缺证据等于候选人没有能力。
- 在线并发向量库、跨 FAISS/manifest/SQLite 原子事务、exactly-once 外部副作用、真实自动投递。
- 真实模型泛化、生产 SLA、多租户安全认证或高并发由本次本地测试证明。
- 将 Application Assistant 的 24-case 确定性合同通过率写成真实 LLM 工具选择准确率。

## 指标怎样用于面试

R12 公开记录有 17 份未参与调优的真实 JD、51 parents、101 人工 atoms。可注明
“历史冻结 gold-atom 轨道 Accuracy 94/101=93.07%，Supported Precision 36/37=97.30%”。
同时披露 Supported Recall=36/42=85.71%、FP=1/59、source precision=71.15%。
raw-JD E2E 完成 16/17，但 parent correctness=26/51=50.98%，不能把 gold-atom 数字写成端到端准确率。

本次只核对公开统计与代码，未读取私有 JD、标注、原始模型输出，未重跑真实模型。
“未参与调优/事先冻结”是历史 manifest 的声明，本次没有独立认证私有原始过程。
其他旧数字有脚本/测试入口，但没有本次原始输出复算，面试时应携带历史报告并明确版本。

## 可复用的中文简历草稿

1. 实现面向求职材料的 Evidence v2：分离模型语义候选与 Python 确定性校验，保存不可变来源与
   原文引用，约束 C1/C2/C3 等级及下游简历投影，避免将来源不足或未解决冲突生成新经历事实。
2. 实现受治理 Agent Runtime，统一工具 schema、权限名单、参数摘要绑定审批、调用预算、轨迹及
   checkpoint/resume；基于 FastAPI、PostgreSQL Outbox 和 Redis Streams 实现异步任务、租约恢复与
   不确定副作用拒绝重放，并通过隔离真实服务上的故障回归。
3. 独立实践 Qwen3 Embedding、FAISS 持久化与 MCP 候选检索，并区分检索相关性与语义支持；
   历史 17-JD/101-gold-atom 轨道记录 93.07% accuracy、97.30% supported precision，
   同时报告 raw-JD 端到端 50.98% parent correctness 的泛化局限。

### 简历能力与源码逐项对应

| 表述 | 直接源码定位 | 测试/指标来源 |
|---|---|---|
| 来源快照、hash、唯一引用、offset | `evidence/sources.py:EvidenceSourceStore.snapshot/validate_span`、`SourceQuoteResolver.resolve` | `test_evidence_source_store.py` |
| 等级与下游事实边界 | `evidence/level_policy.py:maximum_level`、`projections.py:for_resume/for_resume_agent` | `test_source_audit_regressions.py`、`test_evidence_projections.py` |
| 受治理工具执行 | `agent_runtime/loop.py:AgentLoop.run`、`policy.py:authorize`、`tool_executor.py:execute` | agent policy/budget/checkpoint tests |
| 异步事务、恢复、UNCERTAIN | `backend_service/postgres_repository.py`、`outbox.py:publish_once`、`reliable_worker.py:process`、`recovery.py:run_once`、`tool_operations.py` | persistence/reliability 真实服务测试 |
| 独立 Qwen/FAISS/MCP | `knowledge/retriever.py:retrieve`、`faiss_vector_index.py:save/load`、`durable.py:load_index`、`career_mcp_server.py` | FAISS/MCP 确定性测试；真实模型条件测试未重跑 |
| 93.07%/97.30% | `evaluation/unseen_career_holdout.py:_run_gold_atomic`、`real_atomic_evidence.py:_atom_metrics` | `eval/unseen_career_holdout_v2/results-final.json`，历史 gold-atom 轨道 |

### 最终推荐使用的项目描述

建议使用上述三条；篇幅有限时，第三条可简化为“独立实现 Qwen3 Embedding + FAISS/MCP 的
候选证据检索与来源追踪，分离相关性检索和证据支持判断”。面试材料保留完整历史指标及端到端局限，
不要把未重新验证的历史数字包装为本次成果。

本轮新测的 568 项是工程回归；evaluator-v2 的 24/24 是固定 synthetic 场景的脚本控制器合同结果，
不建议在简历中把它当模型准确率。16 项真实模型条件测试、PostgreSQL 16 Compose 全部署及
生产外部副作用未验收，不能扩写为已完成能力。

## English wording

- Implemented immutable source snapshots, exact-quote provenance validation, source-level evidence caps,
  and conservative downstream projections for a small-corpus career workbench.
- Built a governed tool runtime with scoped approvals, execution budgets, trajectories and checkpoints,
  alongside a PostgreSQL outbox / Redis Streams task-processing backend.
- Developed an independent Qwen3 / FAISS / MCP retrieval workflow. Historical gold-atom evaluation recorded
  93.07% accuracy and 97.30% supported precision on 101 annotated atoms; raw-JD end-to-end parent correctness
  was 50.98%. These results were not rerun after the current source-boundary fixes.

## M2A 导入能力补充（2026-10-20）

可写：基于 pypdf 和本地结构解析实现文字版简历 PDF 自动建档，提取身份、教育和项目等字段；用原文片段/偏移/hash 保留来源，支持人工核对和版本保存。
源码：resume_workspace/ingestion.py::extract_upload、local_extraction.py::LocalExtractor.extract、parsing.py::materialize、repository.py::SqliteResumeRepository.accept_draft，前缀均为 src/job_agent/。
验证：新增 20 项，相关后端回归 174/0/0，前端 6/0/0、构建、合成 PDF 浏览器上传/核对/保存；不是全仓库或真实模型验收。
不可写：任意简历准确率 100%、已接 OCR/视觉版面、多栏可靠解析、已达到商业平台解析水平。单份合成样例 3/25→25/25 不用于简历质量指标。
建议描述：实现简历 PDF/DOCX 导入与结构化建档，结合来源引用校验、人工核对和不可变版本管理减少重复录入；通过相关接口回归及合成浏览器流程验证。
完整调用链与学习路线见 [PHASE-02A](devlog/PHASE-02A-pdf-autofill.md)。

## M3 可用简历表述（2026-10-20）

“将版本化简历与 JD 分析接入 React/FastAPI 工作台，复用证据引用与等级校验，支持逐项原文核对、分析快照和已有条目排序建议的接受/拒绝；用持久请求键、调用预算和事务版本检查防止重复执行与覆盖。”
源码：resume_workspace/matching.py、match_repository.py、match_api.py、frontend/src/MatchingPanel.jsx。完整前缀 src/job_agent/（前端除外）。
测试范围：27 新增，相关后端 201/0/0、前端 9/0/0、合成浏览器/15 HTTP。能写接口/来源/版本/幂等实践，不能写真实模型精准率、已统一 RAG/Worker/四 Agent、完整自由改写或录用概率。
本地条目/术语定位只能叫预检查；可选模型已接旧 Evidence 内核但真实质量/费用未验收。

## M3B 建议最终项目表述（当前范围）

**长期求职助手 · 简历事实与版本工作台（持续开发）**

- 基于 Python/FastAPI/Pydantic 与 React 实现简历 PDF/DOCX 导入、结构化建档、原文核对及不可变版本管理；通过来源类型、hash、字符偏移和用户隔离限制无依据内容。
- 将版本化简历接入 JD 分析与证据等级校验，支持分析快照、原文线索和已有条目排序；使用 LangGraph 实现摘要 Writer/Reviewer 有界反馈、结构化交接和逐条人工审批，当前仅完整原句摘录。
- 通过持久请求键、调用预算、应用级 checkpoint、执行租约及事务 head 检查控制重复执行和覆盖；完成相关后端243项、前端11项及合成浏览器流程验证，真实模型质量仍待验收。

| 能力 | 真实代码（后端前缀 src/job_agent/） | 简历边界 |
|---|---|---|
| LangGraph 两角色反馈与三稿上限 | resume_workspace/collaboration.py::CollaborationEngine.execute | 可写有界协作实践；不能写已证明优于单 Agent |
| 结构化交接/角色约束 | resume_workspace/collaboration_contracts.py；collaboration.py::OnlineRoles.invoke | 不称为自由群聊、两个不同模型或旧 AgentLoop 工具协作 |
| 事实与人工版本审批 | resume_workspace/collaboration.py::hard_review；collaboration_repository.py::decide | 原句复制、C1不升级；不是自由润色/外部事实证明 |
| 状态/租约/未知模型停止重放 | resume_workspace/collaboration_repository.py::claim/checkpoint | 应用 checkpoint，不能写原生 saver、Worker 集成或外部 exactly-once |
| 验证数据 | docs/devlog/evidence/m3b-verification.json | 243/11是工程用例数，17 HTTP是独立检查；不写成模型准确率 |

独立 RAG/FAISS、旧 PG/Redis 和 R12 继续按历史范围描述，不能拼成新 React 的统一生产链。PDF 导出、OCR、自由改写、面试协作尚未接通。
真实模型、成本对照和全产品端到端未验收；93.07%/97.30%仍只对应原 R12 gold-atom 范围，不用于新摘要或多 Agent 成绩。详见 [PHASE-03B](devlog/PHASE-03B-writer-reviewer.md)。

## M3C 当前建议使用的项目描述

**长期求职助手 · 简历与面试协作工作台（持续开发）**

- 基于FastAPI/Pydantic与React实现简历PDF/DOCX导入、结构化建档、原文引用校验及不可变版本管理，将JD分析、受限摘要建议和人工确认串入可运行工作台。
- 使用LangGraph实现Writer/Reviewer摘要反馈和Evaluator/Interviewer面试协作；通过结构化消息、角色Schema、有限轮次和合法动作控制协作，支持岗位快照转面试、动态追问、结束复盘与历史查看。
- 区分来源可追溯、相关性建议与事实独立核实；以持久请求键、事务版本检查、执行租约和应用checkpoint控制重复执行，活动面试采用服务端公开投影隔离参考要点。相关后端291项、前端13项及合成浏览器流程通过，真实模型质量尚待验收。

源码对应：核验分层resume_workspace/collaboration_repository.py::_view；面试interview_collaboration.py::InterviewEngine.execute；存储/防泄题interview_repository.py::answer/get/review；前端MatchingPanel/InterviewPanel；后端前缀src/job_agent/。
能写：有限技术题库的有界协作、工作台业务接入、状态/权限/投影保护。不能写：自由生成任意面试、已证明多Agent优于单Agent、真实模型准确率/录用概率、完整PDF导出/长期投递/生产Worker统一主链。
旧Qwen/FAISS及PG/Redis仍为独立模块/旧后端实践；R12的93.07%/97.30%属于原gold-atom统计，不能当新面试成绩。291/13是工程用例数，两个HTTP阶段重复项不能相加为新样本量。完整依据见 [PHASE-03C](devlog/PHASE-03C-verification-interview.md)。
