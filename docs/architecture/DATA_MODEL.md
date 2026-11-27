# V3 数据模型与迁移边界

## F2–F7实际存储
- long_term.py：v3_jobs/v3_job_events/v3_job_links保存JD卡片、阶段事件、版本/面试关联；v3_projects/v3_project_snapshots/v3_project_files保存owner/贡献/来源/commit/不可变manifest和文本。
- code_rag.py：v3_code_indexes/symbols/chunks/edges/vectors都依赖snapshot并级联删除；符号/块payload和完整集合有hash，parser升级须重建。vectors为可选真实backend缓存，当前Demo未启用。
- public_knowledge.py：v3_public_entries指current_version，v3_public_versions保存不可变payload/hash与body去重，v3_public_meta初始化标记避免删除后重启自动重新种入。公共题私有rubric只服务内部，不下发活动API。
- interview_contracts.py/InterviewRepository：rw_interviews私有state包含track/固定项目或prior/计划/已答/下一节点/预算/工具指纹和公开trace；row owner与request/state hash校验。新增字段默认兼容旧记录；引用每读重验。rw_interview_answers保存幂等答复键，租约防并发。弱项主题/参考要点从持久已答状态派生，不凭空新建向量“记忆”。
- tasks.py：v3_tasks外键project/snapshot，唯一(owner,request_key)，固定索引版本，status/stage/result/error/lease token/until/attempts。索引发布同事务fencing；只有幂等派生索引自动恢复，无付费副作用。

身份仍是本地可信令牌映射，不宣称完整User注册/OIDC表；长期学习记录复用InterviewState和prior_session关联，公共Question是版本知识实体。没有新增对象存储、消息总线或图数据库。旧PG Run/Event/Outbox保留独立schema，不谎称已迁新产品。

以下为F1保留结构与边界。

保留SQLite已有rw_sources/rw_uploads/rw_drafts/rw_resumes/rw_versions/rw_version_sources/rw_confirmations及match/collaboration/interview表。每次事务新建连接，外键打开，写入BEGIN IMMEDIATE。新表使用CREATE TABLE IF NOT EXISTS增量安装，不删除用户表、不迁移私人资料。

F1新增：

- `rw_pdf_exports`：version外键级联，template/renderer/版本唯一；保存确定性pdf bytes、PDF哈希、简历content_hash。只导出确认版本，历史版不随head变化。renderer版本改变得到新export id，旧文件保留。
- `rw_rewrites`：owner+request_key唯一，request_hash校验输入；resume外键级联；payload/哈希保存原fact、上下文、最多三稿、Reviewer反馈、审批与接受版本。先持久记录调用保留位，未知外部结果不自动重放。
- `EvidenceReference`：scope/owner/project/snapshot/source/hash/path/line/commit/method/kind/supports_claim。检索默认needs_judgment，所有个人来源默认not_verified；不允许无owner的私人引用。

索引/任务/岗位表将在其阶段记录后补入，不能把设计表写成已经运行。
