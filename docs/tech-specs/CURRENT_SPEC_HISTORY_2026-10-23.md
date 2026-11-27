# Job Agent 当前总Spec

2026-10-23工程收尾：S0—S8核心工程验收完成，人工支持/近重复核对由用户明确延期仍0。相关612/0/4、离线583/0/33及正阈值门禁通过；真实RAG dev/test各630调用0错/新目录新进程各210组合重放文档编码0；四演示含12场景真实恢复通过。三包v2解压后逐字节/CPU门禁/真实HTTP/7 Trace已验，首v1漏模块失败保留。最终三包在output/expansion/delivery-final，以同目录verification.json旁证；当前代码/完整限制与30分钟导读见EXPAND-S8。专用临时验收服务已停、数据保留，旧服务未动。不因人工延期继续扩范围，旧段落状态为历史。

2026-10-23最终回归补录：相关612/0/4，离线583/0/33与正阈值门禁通过；全仓1024/44/54（41旧资源/2旧Redis端口/1无Git），四演示和12场景恢复已过。研究/Trace工程已验，最终三包解压启动检查进行中。人工由用户延期仍0；旧段落中的“测试运行中/未评分”以此及EXPAND-S8最新数据为准。

文档版本：0.9。日期：2026-10-23。该版本号描述文档版本，不是业务软件发布版本。

## 最新S8增量（交付检查中）

固定26原文/72 AI候选（36dev/36test）已冻结，人工核对由用户明确延期、仍0。补Markdown标题/段落结构块和超预算片段标记，索引chunks-3-markdown-1使旧索引提示重建。真实Qwen/CrossEncoder A—G、每split630调用无错误；冻结配置后独立test一次评分，生成回答/语义支持不从检索分数推出。dev/test分别新目录新模型进程210组合重放，引用和候选顺序一致，文档编码0。四项开发BM25正阈值离线门禁已过，多证据0基线明确仅观察。

原SharedRunState/Harness/Tools/EvidencePack/PG任务事件通过三个认证GET路径导出统一JSON/JSONL，ID/hash白名单、old time unknown、根汇总不加子调用；改写导出关闭恢复写入，只有只读检查器。ACK明确反例与否定对照、来源观察/纠正/原图再练习已验，仍标有限确定性规则。详见[EXPAND-S8](../devlog/EXPAND-S8.md)、[消费合同](../evaluation/expansion/TRACE_CONSUMER.md)。完整相关/全仓诊断及解包启动正在验证；总Goal尚未完成。下方S7/更早统计为各阶段历史证据，不替代S8最终结果。

## 最新来源学习闭环（S7）

原InterviewPanel/LearningPanel→learning_api/LearningRepository→原InterviewRepository/图/回答API。已答且完成的来源生成有限观察，实时核owner、版本/hash、固定引用；原评价/用户纠正/单次及多场一致观察分开。确认不认定掌握，不改简历/C1。观察/操作/撤回/明确偏好与面试同SQLite域；项目可在选中PG域，源删除读时失效，无跨库提交承诺。

CAS/请求键控制确认、纠正、暂停、安排、复核、删除及撤回。删除清正文/纠正且同源题点不再生成，源面试/简历FK级联；撤回整题退出学习与weakness，原历史独立保留。90天未核对标过期，新head变化需明确允许原版。队列有新/到期/已复核及排除理由，上海日按owner留存复核控制计额（撤回不退、删除清时间），用户可改1—30天/每日1—20或暂停建议。最多2000观察含tombstone/单场100/页面200/队列20。

再次练习同事务复用原start与图：原题面/focus/完整rubric/固定引用、新题ID和空历史，活动页面不挂载旧回答区；学习身份进入请求/执行绑定，旧hash兼容。只有记录条件相同才给参考比较，纠正/撤回/条件变化不比较。模型同意/可用性/预算/unknown不重放原门禁保留。

最后517相关通过/4既有限定跳过；真实规则HTTP5检查、PG项目HTTP7检查、合成浏览器2场6观察/纠正/暂停/撤回/偏好/重启留存已验，前端13及生产构建通过。真实Qwen7B首评价只给部分要点，完整性门禁停止；不是模型学习闭环成功或教学质量证据。[Spec1.1](expansion/S7-learning-loop.md)、[实体/失败/30分钟报告](../devlog/EXPAND-S7.md)。S1最终候选/人工与S8仍待，整体Goal未完成。

## 当前实现基线

当前来源为ZIP解压V3 F7及[既有实现Spec](../learning/EXISTING_CODE_SPEC.md)，已开始S0—S8扩展。历史验证与本轮实际运行分开。本地无.git；远端旧agent-backend-service缺当前工作台，保留不动；新版在独立`/root/autodl-tmp/study/job-agent-v3`验证。本轮基线794文件hash、真实HTTP和相关回归见[EXPAND-S0](../devlog/EXPAND-S0.md)。不将包内提交当本次Git留痕。

已有来源/版本、匹配、局部Writer/Reviewer、项目快照、AST/BM25/Dense/RRF、工具驱动面试继续保留。默认SQLite/Embedding关闭；显式PG可选择polling或Redis调度。当前原HTTP→PG task/Outbox→独立Publisher/Redis/索引Worker→同PG发布/任务成功→ACK已接通，真实本地Qwen及重启已验；接通不表示语义质量提升。

## 当前检索架构与合同

`main.create_app → RetrievalRuntime.from_env → create_resume_app → CodeRAGService/PublicKnowledgeService → RetrievalInterviewEngine/InterviewTools`。环境示例见workbench.env.example；EMBEDDING=disabled为默认，local_qwen须有本地目录、可用设备与依赖。显式无效配置启动失败；合成demo不自动读私有配置。

代码源先按owner/project/snapshot检查，保持AST/符号/静态边，实际BM25和Dense候选用既有RRF；公共资料不含私有rubric。配置dense时公共service默认Hybrid，未配置默认BM25；HTTP显式method可做单路对照。引用仍绑定原文hash/行号/固定版本，自述不升级独立核实。

索引身份绑定可信scope、实际编码文本/顺序、parser/splitter版本、模型权重配置revision、维度/归一化/query模板/token上限/encoder版本。SQLite复用原表；PG按不可变publication和manifest键存取vectors；旧不完整键不复用。向量载荷完整性与维度/有限值/非零校验保留。

代码向量在build/索引任务的事务外计算，随后在同SQLite事务经原publish_guard发布chunks/edges/vectors；编码失败保留旧索引，旧attempt被fencing拒绝。公共doc/question在启动预热，小语料内存缓存按manifest隔离。正式后端在线查询不隐藏全量文档编码：缺当前向量时dense提示重建/预热，Hybrid明确BM25降级；完整性损坏仍拒绝。

能力接口鉴权后给出真实dense/rerank加载身份、默认方法、构建位置、预算配置和quality_verified=false。默认重排关闭；显式本地RERANK_PATH加载后对Hybrid/code_aware启用，可逐请求rerank=false对照。retrieval_trace-2包含manifest/config身份、两路/融合/重排前后ID、重排logit语义/错误/耗时、字符与token截断、整段quote预算省略和最终引用ID；完整S8事件合同待做。

模型为本地Qwen3-Embedding-0.6B/1024维/l2/cuda:0，最大输入1024 token、batch8；长块可能截断，没有硬中断GPU保证。另已真实运行本地mmarco-mMiniLMv2-L12-H384-v1 CrossEncoder，512-token pair、batch8，Identity激活输出raw logit，只代表排序。模型文件/软件身份固定，加载只本地且无推理外发。公共向量仍内存缓存，重启需预热；新语料/过滤子集未预热显式降级。真实双进程Qwen重启复用与L2范数已验证。

两检索路径共用RetrievalSettings：每路20候选、融合30、重排30、最终请求≤20（默认5）、关系≤8、整段quote预算24000字符；重排每段输入≤6000字符且pair≤512 token。预算省略完整段，不伪造截断引用。RRF k=60。CodeRAG保持符号优先，关系仍有界；纯Hybrid不混入符号/关系，用于隔离算法对照。

重排失败/缺分数/非有限值显式保留原序和分数，不编假得分；向量操作失败时Hybrid显式BM25降级，strict Dense报错，hash/引用/向量形状的完整性错误仍硬拒绝。可选重排与默认关闭Embedding都能回滚，不改来源、审批或C1。

冻结20dev上真实A—F共306次调用无错误，A—D同块/同预算/同K；额外flat BM25隔离切块，原始结果与负结果保留。此数据为AI候选、仅17可回答（代码子集8），已知语料域控制，不是自动路由或人工语义质量。小样本Dense=Hybrid、重排仅首位/MRR略升且更慢、关系未增覆盖且MRR下降；独立test未评分，不宣传泛化收益。

## 当前有界证据交接

鉴权evidence/retrieve或RetrievalInterviewEngine→InterviewTools.retrieve_pack→规则计划→原Registry/Policy/Executor→引用校验→EvidencePack。私有owner/project/snapshot服务绑定；公共固定条目版本。最多2搜索/5工具/8000字符整段quote/20秒协作时限/32768模型输入token预留上界，场内18工具继续有效。大段省略保留原因，可在同计数内读取完整有限行；不伪造截断引用。子工具取父deadline和自身timeout的较早者，不保证GPU硬中断。

Pack保留两轮、显式读取、可信范围、候选/语义待判/缺失/停止原因。没搜到不等于语料无答案；个人贡献和运行成果不能凭源码认定。limited_source_only不等于supported，C1仍未独立核实。内部持久化最多10包，Evaluator/Interviewer消费同一身份与状态摘要；活动HTTP字段白名单不公开完整pack/rubric。执行State/事实审查已接下节S4，语义充分性仍待核对。

完成复盘资源单独post_review执行，最多2工具，不冒充场内18次；保留UI正文与独立trace。状态事务内私有/公开引用校验复用当前DB连接，修复真实后台worker提交与嵌套读的锁等待。375相关回归及真实模型/纯规则各6 pack和8流程检查通过，原373通过但HTTP失败记录保留；未新跑全仓或浏览器。[详细报告](../devlog/EXPAND-S3.md)。

## 当前协作增量

两条原图现在携带SharedRunState，节点消费可信源身份/最新反馈/证据ID/预算与有界事件，并随既有仓储payload/checkpoint保存。模型只见必要投影；Writer历史裁到最近一稿，Reviewer只见原事实和当前稿。改写增加逐断言C1摘录映射与中文成果/否定冲突等门禁；相同坏稿提前停，Reviewer明确needs_input不被改成重试。CAS/lease防过期执行覆盖，采纳重查父版/草稿/事实与审查，仍是新C1。

面试逐要点状态/回答引文和同feedback_id驱动后续动作；活动视图仍白名单。完整事实省略明确context_incomplete，错误/不确定不算covered。运输未知保留model_inflight且不自动重放，已知坏JSON/schema另行失败；相同topic不足以比较，需同题面/引用/评价条件。

最后相关435项通过；新增离线文本provider不改旧Transformers适配，真实Qwen7B两个pilot/HTTP已跑，反馈改变追问，未批准改写不能采纳。12例×3路径×3重复108行/239次真实调用完成，未得到可用改稿增益，额外审查更耗调用；保留负结果，继续简单规则/人工审批默认。小消融6次/事后口语控制均已跑，不能声称独立泛化或正常改写质量达标。评价模型实际有解释误读，明确model_semantic_unverified，人工盲审仍未验。[实际报告与30分钟导读](../devlog/EXPAND-S4.md)。

## 项目域持久化与任务（S5）

`main/独立v3_task_worker → persistence_from_env → ProjectPersistence → 原项目/任务路由与CodeRAG`。PROJECT_BACKEND默认sqlite；postgresql须显式DSN/schema，非法配置不降级。三类协议把CodeRAG中的SQL抽走；PG复用原生psycopg事务模式，单独schema/模型，不继承旧Run。简历/审批/岗位/面试仍SQLite，无影子项目/索引/任务双写。

PG项目owner/当前快照复合FK、快照文件hash和不可变publication完整派生行；固定锁序project→snapshot→task。新请求提高desired_generation；claim token/DB时间lease/config身份共同fencing。向量在事务外编码，publication/active指针/项目状态/任务SUCCEEDED/事件同一事务。读取指针/完整载荷在同一repeatable-read事务；删除级联域内所有派生，历史发布按快照生命周期保存。面试引用使用选中CodeRAG重查，SQLite连接只在同域复用。

隔离PG14.24真实服务、HTTP ZIP/任务/检索/项目面试、不同进程与PG重启、独立worker、无SQLite影子数据已验；Qwen1024维持久向量新进程复用。合成迁移只读备份/稳定ID/hash核对/空目标导入/原备份回滚已验，拒绝活动任务与损坏数据；源停写是前提，不是零停机生产迁移。单个业务dump恢复到独立数据库已验，最终研究评测索引留S8。[ER/时序/实际限制及30分钟导读](../devlog/EXPAND-S5.md)。最后455通过/4限定跳过32.34秒，非全仓或生产验收。

## Outbox与Streams（S6）

新增index-dispatch-2迁移保留S5 DDL/hash。task与Outbox同事务；四字段消息只含authority/event/task/generation，scope从PG重取。Publisher单条10秒租约、最多12次发送和有界退避，避免整批等待过期；Worker重用原IndexTaskWorker.process_claim/CodeRAG/心跳，原PG代次/config/token/DB时间发布门禁不变，三次执行/恢复后明确终态。

复用旧Redis transport连接/group/ACK/监控原语，新增持久重领游标、近似MAXLEN10000、缺group重建。ACK不删除Stream；Redis信息丢失依PG未完成任务/Outbox显式对账，最后发送租约丢失也能收终态。坏/未知/失败消息归档定位+安全码+digest（最多1000条），不存正文；CLI inspect/reconcile可查可处理，失败重建用新请求键。lag/pending/保留、发送/耗尽和任务失败分开报告。

同schema在PG固定polling或redis；Redis模式拒绝内嵌轮询。维护切换要求无QUEUED/RUNNING，轮换authority作为执行代次，即使A→B→A旧进程仍被fence并需重开。私有main与独立CLI同配置，SQLite仍默认；生成模型沿用S4未知结果保护，不入索引重放队列。真实PG/Redis、原HTTP、独立进程故障、真实Qwen链及前端构建已有证据；不等于生产SLA/零丢失。完整ER、时序、矩阵与30分钟导读见[EXPAND-S6](../devlog/EXPAND-S6.md)。

## 固定检索评测合同

当前评测合同已增加固定CorpusSnapshot/EvalCase/GoldSpan：18原文、32 AI候选（20开发/12独立测试），家族/gold来源跨集及quote/hash不符被拒绝。生成器拒绝覆盖不同的冻结内容。指标分开any-gold Hit、gold覆盖、all/any充分性、MRR、引用有效；支持/最终业务质量未评时null。9项静态合同通过。人工标注0，测试集只静态校验，尚未跑检索评分；详见EXPAND-S1。

## 扩展阶段状态

| 阶段 | 状态 | 目标 | 阶段Spec/证据 |
|---|---|---|---|
| 既有实现教学补建 | 文档完成，静态核验已运行 | 总体流程及6章18个旧任务 | [任务索引](../learning/DETAILED_LEARNING_STAGES.md)、[阶段报告](../devlog/LEARNING-SPEC-2026-10-22.md) |
| S0 | verified（基线/失败分类，不是全绿） | 源码/环境与真实HTTP基线 | [Spec](expansion/S0-baseline.md)、[报告](../devlog/EXPAND-S0.md) |
| S1 | in_progress；身份/首批32候选静态合同verified | 60—80最终集/人工gold/实际EvalRun待做 | [Spec](expansion/S1-corpus-contract.md)、[报告](../devlog/EXPAND-S1.md) |
| S2 | 工程/真实模型/开发候选诊断verified；独立语义质量待验 | 已接线/预热/重排/统一预算及开发对照 | [Spec](expansion/S2-retrieval.md)、[报告](../devlog/EXPAND-S2.md) |
| S3 | 工程/合成HTTP verified，语义支持待判 | 有界计划/2轮/受限读取/EvidencePack/不足分层/真实并发修复 | [Spec](expansion/S3-evidence-pack.md)、[报告](../devlog/EXPAND-S3.md) |
| S4 | 工程/真实模型/候选对照verified；生成质量无增益/人工未验 | 共享State/事实约束/未知派发，108行239调用/6次小消融，435相关通过 | [Spec](expansion/S4-collaboration.md)、[报告](../devlog/EXPAND-S4.md) |
| S5 | 工程/隔离PG/合成迁移/真实Embedding verified | 项目→快照→索引→任务同PG域、原API/重启及回滚；455通过/4限定跳过 | [Spec](expansion/S5-postgres-slice.md)、[报告](../devlog/EXPAND-S5.md) |
| S6 | 工程/真实服务/独立进程/本地Embedding verified | 487通过/4限定跳过；13场景/42进程故障矩阵已跑；最终authority往返fencing及同源码v3矩阵13/13通过 | [Spec](expansion/S6-outbox-streams.md)、[报告](../devlog/EXPAND-S6.md) |
| S7 | 工程/规则真实HTTP/PG来源/浏览器verified；LLM完整闭环失败保留 | 517通过/4既有跳过；来源观察/明确控制/有限复习/固定题再练习 | [Spec](expansion/S7-learning-loop.md)、[报告](../devlog/EXPAND-S7.md) |
| S8 | planned | 最终题集/完整研究trace与重放/统一交付 | 按依赖小增量实施，先Spec后代码 |

## 总Spec更新规则

每个增量结束，将已核实变化合并进本页/对应主题章节，更新入口、数据合同、调用/状态流、能力边界和学习顺序，并链接增量Spec、实际代码及验证记录。实现但未验证的内容标implemented_unverified；未做内容保持planned/deferred。

基线文档保留原日期。新增较大主题时独立成章，在本页串联。当前说明不能只堆阶段链接却仍把旧架构当最新状态。

此前相关基线246、预热后264、前端状态逻辑13、评测静态合同9通过；不是相加后的新套件成绩。全仓首采集缺Streamlit2 errors；补UI后839/45/50（59.79s），45项=41缺历史资源/2 Redis/1无Git/1本次Qwen回归，后者已修复定向通过；原失败保留，没有宣称全仓全绿。未新跑浏览器/前端构建。

S2历史子增量3相关306通过17.76s，真实重排HTTP7检查/7查询/2面试入口及真实模型双进程重启通过；身份测试随机chunk排序空操作断言的305/1原失败保留。后续协作与PG见S4/S5实际结果；独立语义泛化/人工及Redis切片仍未验。

追加G flat BM25后开发诊断339调用/0错误，20dev/12独立test未评分。所有统计保留AI候选及小语料限制。临时fixture业务UUID新建，最终可重放索引/scope身份需S8补，当前不承诺bit级重现排名。

## 学习方式

Job Agent边优化边学，每个增量前回看相关旧Spec，结束后按实际变化复述设计、失败和取舍；旧任务索引按需补课。用户尚未完成的学习任务不代为标记已掌握。

[变更记录](SPEC_CHANGELOG.md) · [增量模板](INCREMENT_SPEC_TEMPLATE.md) · [聊天交接](../learning/CHAT_HANDOFF.md)
