# 一次请求如何走完整系统

1. `frontend/src/main.jsx::App`上传 → `api.py::import_file` → `ingestion.extract_upload`复用文本loader → `ResumeParser.parse`本地规则或明确同意的模型 → 原文范围校验 → 保存草稿。
2. 人工核对 → `SqliteResumeRepository.accept_draft/edit_version` → SQLite事务追加不可变版本。所有字段保留来源，手工修改另建C1补充；不会伪装原始简历内容。
3. `MatchingPanel.jsx` → match_api安装的analyze → `MatchRepository.begin`固定JD/版本 → `WorkbenchMatcher.analyze`直接读取短上下文，在线复用Evidence内核要求拆解/映射/校验/投影。规则模式仅词面lead，不提供支持结论；JD抽取不进入候选人个人材料池。
4. `RewritePanel.jsx` → `RewriteService.start` → Writer/Reviewer有界反馈 → `hard_constraints` → 用户decide → 新自述+新未确认版本；原版不变。
5. `ConfirmVersion` → `PDFRepository`确认/hash/owner Gate → ReportLab/Noto两模板 → 保存版本绑定PDF → PDF.js同源worker显示实际PDF → 历史下载。
6. `ProjectsPanel.jsx` → ZIP/GitHub快照 → index-tasks202 → 持久Worker → AST/Tree-sitter/符号边 → CodeRAGService.search → 引用校验。
7. `InterviewPanel.jsx` → `InterviewRepository.start` → `RetrievalInterviewEngine.prepare`真实检索 → 用户回答 → LangGraph evaluator/interviewer/route → scoped工具读取 → 反馈追问 → 完成review → 公共资料与薄弱项新场次。
8. `JobsPanel.jsx` → `LongTermRepository`岗位卡片/投递事件/版本和面试关联。数据库保存业务事实；Agent状态保存运行步骤；任务队列安排后台执行，三者不混同。

LLM可用于解析、原子拆解/语义映射、Writer/Reviewer、Evaluator/Interviewer。文件抽取、owner/hash/offset校验、预算、路由上限、事务、审批、PDF、静态解析与规则Demo由Python执行。真实外部模型尚未授权，Demo显式不调用。
