# FINAL-F0 — 基线与可执行架构

- 日期：2026-10-20
- 基线：main / 067bfc7d63408e1e6b0ab6c227e863bd08a5857a，38项未提交路径；详见 evidence/v3/f0-start.json。
- 状态：DONE（工程审计与基线；环境受阻项目单独保留）；真实模型 NOT_RUN。

## 1. 用户问题与基线

旧产品已有导入、不可变简历版本、JD快照、摘录协作和有限面试。缺PDF、长期岗位、代码知识库及真正工具协作，不能把独立模块存在当成产品接通。
最新版公开源码558个文件已在业务改动前保存哈希与快照；不读取.env和私人运行数据。任务书从用户ZIP仅导入roadmap，没有覆盖源码。

## 2. 架构和备选

保留React/FastAPI、SQLite产品事务、Evidence v2验证内核及已有LangGraph角色。新增能力用显式适配器接入口，避免重写旧内核。
短简历/JD继续直读；公共资料和大代码仓库才检索。PDF优先验证ReportLab确定性渲染，避免为导出增加浏览器服务依赖；需真实中文抽取及渲染后才确认适用。
既有PG/Redis/Outbox作为异步适配候选，不新增Celery或Kafka。Docker当前不可用，真实服务验证须另记客观限制。

## 3. 真实调用链和复用位置

| 能力 | 实际入口/核心符号 | F0判断 | 后续 |
|---|---|---|---|
| 简历导入 | frontend/src/main.jsx::App → resume_workspace/api.py::create_resume_app → ingestion.py::extract_upload → parsing.py::ResumeParser.parse | 已接产品，规则/可选LLM | 复用、补集成 |
| 来源版本 | repository.py::SqliteResumeRepository，contracts.py::ResumeFact | 原文slice/hash/owner，确认仅自述 | 保留门禁 |
| JD | match_api.py::install_matching_routes → matching.py::WorkbenchMatcher.analyze → match_repository.py::MatchRepository | 直读版本与JD，未调用向量检索 | 复用 |
| 摘录协作 | collaboration.py::CollaborationEngine.execute → collaboration_repository.py::CollaborationRepository | 有界Writer/Reviewer，非自由改写，零工具 | 新增独立改写协议 |
| 面试 | interview_collaboration.py::InterviewEngine.execute → interview_repository.py::InterviewRepository | 有反馈路由/活动答案隔离，有限固定题库 | 接工具/项目/复习 |
| 独立RAG | knowledge/bm25_index.py::BM25Index、hybrid_retriever.py::HybridRetriever、faiss_vector_index.py::FAISSVectorIndex | 有代码，未接新React产品 | 用有owner和snapshot的适配器 |
| 旧异步 | backend_service/execution.py::TaskRoutedExecutionAdapter、persistent_bootstrap.py::create_persistent_api_stack | PG/Redis旧服务独立，未接产品 | F5接一条真实任务 |

表中路径默认前缀src/job_agent/，前端路径除外。UI/CLI/旧后端不强行合并。

## 4. 验证

后端：`python -m pytest -q -ra --basetemp=../../work/v3-f0-pytest --junitxml=../../work/v3-f0-junit.xml`，运行中；显式关闭真实本地模型路径，不读取Key。
前端：`npm test`=13通过/0失败/0跳过；`npm run build`通过。日志work/v3-f0-frontend-*.log。

## 5. 对照

冻结规则见docs/evaluation/BASELINES.md。未做V3真实模型质量对照，无提升结论。

## 6. 限制与隔离

当前Python3.12、Node24、LangGraph1.2.16，FAISS/ReportLab/pypdf/PG/Redis客户端可用；Docker、OCR、JS/TS语法插件缺少。不能把客户端可导入说成服务集成通过。

## 7. 阅读顺序（45分钟）

main.jsx导入10分钟 → contracts/repository来源和事务15分钟 → matching与协作10分钟 → BASELINES与任务书10分钟。

## 8. 面试追问

1. 为何不重写？已有不可变版本和确定性来源检查是已验证资产，适配扩展可降低回归风险。
2. RAG是否所有地方都要用？短简历直读更清楚，检索处理公共参考及大代码材料，召回不代表支持。
3. 为什么保存dirty基线？HEAD不能描述未提交代码，文件哈希和快照补足复现。
4. 规则通过能证明模型效果吗？不能，只证明输入边界、流程和确定性性质。
5. 如何避免评测泄漏？先冻结协议/数据版本，开发集与冻结集分离，失败结果不删。

## 9. 下一步

相关基线291通过/0失败/0跳过；前端13/0/0与构建通过。首个全量诊断735/2/50含F1新增PDF8项，纯已有测试727通过；两失败因本地Redis连接拒绝。50跳过详见evidence/v3/f0-f1-test-results.json：34 PG、16模型条件。首次安静模式运行长时间等待已停止，未伪报为通过；诊断设置PGCONNECT_TIMEOUT=2仅约束依赖探测。
冻结40代码题（20跨文件）已登记DATASETS.md和SHA256SUMS；统一引用对象已落evidence_reference.py。已进入F1，继续开发手册需读FINAL-F1而非旧M阶段；付费模型未授权。
