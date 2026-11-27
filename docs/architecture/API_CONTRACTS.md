# V3 API 契约（随阶段更新）

## F2–F7当前增量
均由resume_workspace/api.py::create_resume_app注册。身份由可信服务映射，下面请求不接受owner字段。

| 路径（前缀/api/v2） | 合同/行为 | 实现 |
|---|---|---|
| GET/POST /jobs；GET/DELETE /jobs/{id} | 岗位/JD不可变快照、revision检查、阶段/备注事件 | long_term.py::LongTermRepository |
| /jobs/{id}/events、/links | 请求键幂等，简历版本/面试必须同owner且版本匹配 | long_term.py安装的路由 |
| GET/POST /projects；GET/DELETE /projects/{id} | 贡献标记自述、快照/配额、删除源与派生索引任务 | LongTermRepository |
| POST /projects/{id}/zip、/documents、/github | 原始ZIP/说明文档/严格公开URL；文件不执行 | project_import/github_import.py |
| POST /projects/{id}/index-tasks | IndexTaskRequest{request_key,snapshot_id}，202，持久后台任务 | tasks.py |
| GET /projects/{id}/index-tasks；GET /tasks/{id}；POST /tasks/{id}/cancel | 私有任务历史/状态，只有QUEUED可取消；不暴露lease_token | TaskRepository |
| POST /projects/{id}/index；GET /projects/{id}/index | 保留同步兼容入口/索引状态，版本过期needs_rebuild，UI默认异步 | code_rag.py |
| POST /projects/{id}/search | CodeQuery snapshot/query/method/limit/expand_relations；相关线索非事实支持 | CodeRAGService.search |
| GET /projects/{id}/symbol、/references、/code | snapshot/name、symbol_id/tests_only、path/start/end；精确引用 | get_symbol/find_references/read_code_range |
| GET/POST /knowledge/search；GET /knowledge/status | 小公共库，只返回公开题/摘要；无HTTP install/rubric接口 | PublicKnowledgeService |
| POST /resumes/{id}/interviews | InterviewStart新增use_retrieval/track及受限project/snapshot或prior_session | InterviewRepository.start |
| POST /interviews/{id}/answers、/pause、/continue、/finish、/resume | expected_revision/问题ID/请求键；暂停与执行恢复分开；在线每次同意 | interview_api.py |
| GET /interviews/{id}、/review | 活动显式投影；review完成门禁，学习资源/缺口/源码引用/可比对照 | InterviewRepository.get/review |

兼容：旧InterviewStart默认use_retrieval=false并保留原请求hash序列化；V3界面显式启用检索。track=project必须固定项目/快照；weakness必须先有已完成prior_session。真实模型适配仍通过LLMHarness，结构化目标派发工具不等同provider原生function-calling协议。
Task状态复用旧RunStatus：QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED；该任务只处理无外部副作用索引，不设置虚假的waiting_user/unknown。模型未知执行由旧面试inflight保护，不由索引Worker重放。进度使用鉴权轮询，不声称实现SSE/WebSocket。

以下为F1保留合同。

沿用 `/api/v2` 产品前缀，V3表示产品范围，不重新创建并行API应用。所有私有路由依赖 `create_resume_app.owner`，身份来自服务端口令映射，不接受客户端指定owner。未授权401，外人/不存在均404，状态/版本冲突409；错误不回显请求体。

| 操作 | 路由 | 关键输入/保证 | 源码 |
|---|---|---|---|
| 简历导入 | POST /imports?filename= | raw≤5MB，不执行附件；抽取与模型解析分离 | ingestion.py::extract_upload |
| 字段解析 | POST /sources/{id}/parse | mode/在线逐次同意；输出草稿/引用 | parsing.py::ResumeParser.parse |
| 接受/编辑/确认 | POST /drafts/{id}/accept、/resumes/{id}/versions/{vid}/edit、/confirm | 原文或新增自述来源、不可变版本、乐观head | repository.py::SqliteResumeRepository |
| JD文件 | POST /jd/extract?filename= | raw≤5MB、文字≤12000；不保存为候选事实 | api.py::extract_jd |
| JD分析 | POST /resumes/{id}/matches | version/hash/request_key/mode/JD，快照绑定 | matching.py::WorkbenchMatcher.analyze |
| 局部改写 | POST /resumes/{id}/rewrites | 单个项目/实习bullet路径，version/hash/key/JD/mode | rewrite.py::RewriteService.start |
| 改写审批 | POST /rewrites/{id}/decision | action、expected_parent_version_id、expected_draft_hash、user_reviewed=true | RewriteService.decide |
| 正式PDF | POST /resumes/{id}/versions/{vid}/pdf | expected_content_hash、classic/compact；仅确认版 | pdf_export.py::PDFRepository.export |
| PDF历史 | GET /resumes/{id}/pdfs、GET /pdfs/{id} | owner检查、缓存bytes哈希、级联删除、inline文件 | PDFRepository.list/download |

上述源码默认前缀src/job_agent/resume_workspace。JSON默认no-store，文件也不写第三方URL；页面内PDF.js只读本机已下载的字节。

改写审批不是覆盖原始引用：新文字通过 `_apply_edits` 形成新 user_statement，run中保留 source_fact、entry_context、历稿/评审、最终版本ID。C1与not_verified不随审批提升。来源对齐、语义支持和独立真实性是不同维度。
