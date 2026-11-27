# 关键技术决策

## 2026-10-23 第三轮取舍

关系扩展先保留直接证据，再补剩余预算；静态边不是更强事实。加权2对开发代码/设计有取舍，停止扫描并保留默认1。最小支持与原gold并集使用独立版本，不覆盖旧gold。显式来源状态沿原题/评价/观察传递，不把topic_only当任意QA拒答。真实7B首pilot的错ID/编造quote保留失败，只改提示帮助复制原句，绝不补评价或降低R1。新包取提交集合，历史缺链单列，不扫入并行教学。

## 2026-10-23 复核增量

- Evaluation默认空列表维持历史/规则读取兼容，在在线LLM边界强制完整；不补correct。旧学习来源只读检查并排除，不删除审计历史。
- 真实DeepSeek实验仅使用授权合成材料，凭据仅内存；零自动重试，实际派发/usage/未知失败保留。共享首稿控制随机性，路径成本归因与真实网络调用分开；模型自评不代替人类质量。
- 二进制研究DB不入Git，公开合成SQL可审计物化；新物理hash明确新manifest，原floors/基线不改。隔离安装验证根包/提示资源，不能依赖cwd兜底。普通BM25门禁、确定性算法合同、真实后端与生成测试分层。

## 2026-10-22 S7增量

- 学习观察与原面试同SQLite事务，复用来源校验/图/回答API；不把全部聊天向量化或隐式推断用户能力。PG来源读时重查，不伪造跨库FK或删除承诺。
- 原评价、用户纠正/偏好、多场同条件观察分开；确认/已复核不认定掌握。撤回整题评价停止驱动学习/weakness，历史独立保存；删除抹正文和纠正，tombstone抑制同源题点重建。
- 复用原题/focus/rubric/固定引用来再练习；新ID/空回答/活视图白名单保留，旧请求hash兼容。仅比较同记录条件，纠正/撤回不作基准，学习复盘不同时展示旧topic末次回答比较。
- 明确规则取代伪训练模型：上海日、owner共用、有限建议/可调间隔/暂停；撤回不退复核额度、删除不为配额保留私有控制时间。修复公开视图隐藏controls导致退款的实现问题并做真实重启核对。
- Qwen输出可解析但只有一个要点，保留业务完整性拒绝；不补造评价、不自动重试或宣传学习效果。工程/规则闭环与模型失败分层交付。

## 2026-10-22 S6增量

- task+Outbox在同PG事务，网络发送在外；不做跨PG/Redis分布式提交。稳定event允许重复，原PG条件领取/发布保证不重复有效索引，ACK不当作任务成功。
- 复用旧Redis连接/group/ACK/监控原语，适配当前task定位、游标、有限保留；不继承旧Run。独立Publisher/consumer实际调用原CodeRAG，不造展示专用索引器。
- Publisher逐条租约避免整批慢发送耗尽；12次发送与3次执行分开，最后发送租约丢失也对账收终态。坏/未知/失败安全归档，不存任意正文；队列丢失依据PG明确对账，不宣称零丢失。
- PG持久模式+authority epoch；维护无活动任务并轮换身份，类型A→B→A不能复活旧A。旧模式进程遇fence明确退出，默认SQLite/polling兼容。文本模型unknown保护保留，不套用可重建索引重试。
- 真实进程矩阵v1最后socket就绪竞态时核实同一新PID已活，不盲重启；探针改等待PING后v2全过，原失败保留。原网络/依赖DNS失败保留，随后相同官方hash/锁定依赖获取成功；这些不是业务或语义收益。

## 2026-10-22 S5增量

- 抽项目/索引/任务协议，SQLite保留表合同，PG使用原生事务与独立schema模型；不做占位符翻译，不继承旧Run。一次切换整个项目权威域，不影子双写，代价是需要两后端共享业务合同。
- 编码在事务外；发布锁序project→snapshot→task，generation/config/token/DB时间共同fencing。不可变publication与active指针、项目状态和任务成功同提交；repeatable-read读完整一版。旧发布保存到快照删除，未实现在线回收，不把空间成本隐藏。
- 简历/面试保留SQLite，选中CodeRAG每次重查跨域引用，不传错误连接/伪造分布式事务。源删除后引用失效，不自动提升C1或个人贡献。
- 离线只读备份、空目标、完整反投影hash和稳定ID迁移，拒绝活动任务/损坏hash/非空目标，保留源供配置回滚；源停写是显式操作前提，未提供双写或零停机生产迁移。
- 项目内提取官方索引核hash的PG14.24包，nobody/私有socket/隔离临时实例；缓存包404和直连超时保留。真实HTTP/模型/迁移与规则合同分开报告，PG轮询不冒充S6 Redis交付。

## 2026-10-22 S4增量

- 两条原图使用同一有界执行/反馈/事件合同，随原payload/checkpoint保存，不开并行权威库。角色拿必要投影而非全部历史；代价是兼容旧状态与明确已知/未知用量，收益为可追踪的源身份和真实反馈消费，不等于语义正确。
- 逐断言C1相对来源与确定性成果/否定/数字等门禁先行，模型语义映射仍未独立验证。Reviewer不能豁免，明确needs_input不被强行改成循环。相同坏稿早停，CAS/lease阻止失效执行覆盖，采纳重查仍新C1。
- 运输未知不清除inflight，不自动重放；完整坏JSON/schema是已知失败。源身份/完整性/合法焦点与父时限由程序检查，模型不能更换owner或写库。
- 独立Reviewer屏蔽作者理由/自我认可，自审路径保留作者视图；同模型和调用上限分别报实际费用/用量。108行239调用未得可用改稿收益，更多审查未胜出，保留简单规则/人工审批默认。真实评价解释误读保留，不把模型互评当真值。

## 2026-10-22 S3增量

- 程序规则做有界计划，不加必调LLM规划器；所有选择的搜索/读取复用原工具计数。两轮不足/输入上界/父deadline显式停止，代价是不能任意扩大上下文，收益是可解释有限花费，不代表语义充分。
- EvidencePack保留候选、待判和不足；命中/路径数不提升成supported，源码不证明本人经历。双角色只共享必要身份与状态摘要，完整pack内部保存，活动视图不公开rubric。
- 原复盘资源直连循环改独立执行预算，保留UI正文和失败trace；不假装属于场内18工具。
- 真实HTTP锁故障后选择复用当前事务校验私有/公开引用，保持同一一致性视图；不选仅加timeout、关闭worker或跳过校验。两项测试确认真实并发写提交，相关375通过；失败原文保留。此修复不等于PG产品切片完成。

## 2026-10-22 S0—S2增量

- S2子增量3：小型多语言本地CrossEncoder先验证真实排序/成本，不直接引入更大模型；固定官方提交/safetensors hash，应用仅离线加载。默认关闭，可逐请求关掉作A—D；logit不是概率。
- 统一两路径预算与版本hash，缺失/坏分数保留原序，整段quote超预算省略而不伪造引用。向量操作异常可词面降级，完整性异常拒绝。
- 固定开发诊断保留Dense=Hybrid、重排小幅排序变化和关系负收益；AI候选/小语料不足以改成普遍最优宣言，独立测试继续封存。AST可能缺import的定位失败补flat对照，不修改gold凑分。

- 远端旧repo缺新版工作台，新建独立job-agent-v3运行本地源码，保留旧repo与来源包。
- IndexManifest复用KnowledgeChunk/SQLite，绑定scope/实际输入/parser/splitter/完整encoder身份，避免每次重编码或只按文件hash缓存。代价是版本合同维护，收益仅身份正确性。
- 显式注入既有Qwen，默认关闭，不引入新向量库。真实GPU pilot已跑，复杂组件收益须公平评测。
- 代码向量事务外计算，同fencing发布事务写入；公共小语料启动双kind预热。未就绪显式重建/降级，代价是启动/任务更慢和重建要求。
- 公共默认策略由service按后端选择，面试工具实际走Hybrid，显式BM25保留作对照。

## 2026-10-22 学习文档组织

为符合用户按详细Spec学习的要求，采用现状总Spec＋分章任务＋教学概览＋独立聊天交接。每任务列场景、代码、步骤、失败、产物和追问；与单一长README相比更易逐项验收。该决定不新增业务架构，教学顺序不冒充原始历史。入口见[详细任务](../learning/DETAILED_LEARNING_STAGES.md)。

## V3 已实施决定

- F1：保留ResumeFact原文相等约束；语义改写独立提案，接受后新user_statement，血缘与原版不变。替代“改写仍冒充原引用”会破坏来源保证，弃用。代价是要维护审批记录与用户核对。
- F1：ReportLab两模板+OFL Noto嵌入+按需PDF.js同源Worker。真实IAB iframe空白后更换预览，不依赖插件；代价是字体/Worker包体，未引入额外浏览器服务。
- F2：复用SQLite可信owner/事务，岗位事件+版本关联、不可变项目快照。真实重启已验证，不能称生产级PG/Worker验证。
- F3：SQL符号/静态边，精确条件先查符号、再BM25/可配置向量，动态绑定不猜；不新增Neo4j/Elasticsearch。缺Embedding时明确降级，不能伪造语义召回。测试见test_v3_code_parser/code_rag，真实模型效果待验。
- F3/F6：公共BM25索引公开tags，引用仍用原标题/正文；只改搜索投影以保护历史引用。保留v1失败与v2，标签诊断不冒充盲评。
- F4：扩展旧InterviewEngine/Repository，复用原Registry/Policy/Executor，以Schema目标选择派发真实读取；不新造群聊框架或面试库，代价是规划范围有限，语义质量另测。
- F5：v1 PG/Redis合同不同且环境缺失，本地采用SQLite持久任务适配，同事务入队/claim/租约fencing；只自动重建幂等索引，不重放未知模型。新产品生产适配未验。
- F7：仅同topic/rubric/aliases/model/provider的末次回答作参考要点对照；不同题not_comparable，不制造提升率。
- OCR：实际安装公开CPU组件尝试ONNX1.31/1.22.1均本机初始化失败，保留BLOCKED，不接未经验证的死适配，也不外发文档换假通过。

补录日期：2026-10-20。以下依据 M1/M2 真实源码和记录总结，不声称是当时逐分钟的决策日志。
适用范围为当前增量；未来替代应新增决定并链接原条目，保留理由与迁移证据。

## D-001：结构化字段与来源同时保存

- 阶段：M1。
- 问题/证据：旧 snapshot 是 resume_text，缺少新产品字段合同。
- 采用：ResumeDocument/ResumeFact/SourceSpan，来源 owner/kind/hash/字符引用校验。
- 备选：仅 Markdown 或仅 source_id；前者不便编辑，后者不能确认哪一版哪句话。
- 成本/风险：抽取事实更细；来源关系不能证明现实真相，也不能证明任意改写。
- 适用：字段编辑、核对和后续模板输入；不适合作为自动事实认证。
- 锚点：`src/job_agent/resume_workspace/contracts.py::ResumeDocument`、`src/job_agent/resume_workspace/repository.py::SqliteResumeRepository._validate_document`。
- 验证：M1 新增 34 项；`docs/audit/upgrade-m1/verification.json`。
- 状态：已实施。

## D-002：追加版本、独立确认、父版本检查

- 阶段：M1。
- 问题：覆盖丢历史；恢复不能复用旧确认；并发保存可能互相覆盖。
- 采用：独立 version_id/content_hash、追加历史、expected parent + 写事务；确认记录绑定版本/hash。
- 备选：hash 直接作版本身份或原地覆盖；不能完整表示 A-B-A 和用户动作历史。
- 成本/风险：保留更多记录，需要清理/迁移；事务是单机业务保证，不是付费执行 exactly-once。
- 适用：用户编辑/确认/恢复；后续投递绑定可用稳定版本，尚未实际接入投递。
- 锚点：`src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.save_version`、`src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.restore_version`。
- 验证：并发/A-B-A/确认幂等测试及合成 HTTP；M1 verification。
- 状态：已实施。

## D-003：本地业务底座先行，保留旧入口

- 阶段：M1/M2。
- 问题：已有证据/队列/长期模块分散，全面统一会同时改变多个已测合同。
- 采用：独立 resume_workspace + SQLite 产品增量，旧 UI/CLI/RAG/PG 路径保留。
- 备选：直接重写所有入口或新增第二套队列；会扩大回归和状态一致性成本。
- 成本/风险：暂有多入口，未完成统一产品；新 API 不具备旧 Worker 的持久执行保证。
- 适用：单机增量与可运行 Demo；未来统一 PG 需要明确迁移、ID、恢复与验收方案。
- 锚点：`src/job_agent/resume_workspace/api.py::create_resume_app`、`src/job_agent/backend_service/persistent_bootstrap.py::create_persistent_api_stack`。
- 验证：M1/M2 相关测试；旧真实 PG/Redis 验证仅属历史基线。
- 状态：已实施；产品 PG/Worker 适配待做。

## D-004：解析提议与确定性校验分开

- 阶段：M2。
- 问题：模型直接输出最终简历会混合原文、推断和新增事实；缺失不能靠猜测补齐。
- 采用：不完整 DraftDocument，字段 path + exact_quote 候选，Python 白名单/位置校验和生成 ID。
- 备选：整份生成文本或放宽完整文档必填合同；无法稳定位来源/编辑/缺失问题。
- 成本/风险：引用有效不等于分类/语义正确；规则仅覆盖明确标签，需用户核对和后续真实模型验收。
- 适用：导入/解析阶段；AI 优化建议另建合同，不借真实引用自动添加业绩/技能。
- 锚点：`src/job_agent/resume_workspace/parsing.py::materialize`、`src/job_agent/resume_workspace/fields.py::checked_path`。
- 验证：缺失、模糊引用、伪造 quote/路径与模型替身回归；M2 verification。
- 状态：已实施；真实模型质量未验证。

## D-005：人工补充成为独立自述，接受操作事务化

- 阶段：M2。
- 问题：修改原文会让新内容看似来自旧文件；重复提交可能创建两份简历。
- 采用：changedFields → user_statement → 同一事务接受草稿/追加版本；请求 hash 识别重复或冲突。
- 备选：直接改 source、分开提交来源和版本；破坏不可变关系或留下半成品。
- 成本/风险：来源和版本更多；普通编辑以父版本冲突防重复，未实现所有网络请求的幂等键协议。
- 适用：人工核对/局部编辑；不是自动把自述升级为 C2/C3。
- 锚点：`src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.accept_draft`、`src/job_agent/resume_workspace/repository.py::SqliteResumeRepository._apply_edits`。
- 验证：并发接受、重复/冲突请求、回滚无孤立来源、历史保留；M2 测试。
- 状态：已实施。

## D-006：有界模型调用、逐次同意、无静默替代

- 阶段：M2。
- 问题：反复修复会扩大成本；未知计费调用超时后自动重试可能重复付费。
- 采用：输入 30,000 字符、输出每次 6,000 tokens、总调用最多 2；结构/引用修复一次；传输失败停止。
- 备选：无限修复或失败后用规则伪装模型成功；会掩盖验证失败且不可解释费用。
- 成本/风险：更多显式失败；请求内调用没有跨重启执行账本，费用未知保持 null。
- 适用：当前解析接口；操作者需配置，用户需同意本次发送，材料变化/尝试后前端清除同意。
- 锚点：`src/job_agent/resume_workspace/parsing.py::ResumeParser.parse`、`src/job_agent/resume_workspace/api.py::create_resume_app.parse_source`。
- 验证：模型替身验证预算、一次修复、超时不重试；真实模型未调用。
- 状态：合同已实施；真实质量/费用与持久任务语义待验证。

## D-007：同源 React 与合成 Demo 隔离

- 阶段：M2。
- 问题：单有 API 无法展示实际编辑，私人工作区不宜作为演示数据源。
- 采用：FastAPI 提供构建文件；公开演示只 loopback、临时库、无模型；私有启动器另用私有口令。
- 备选：把旧 Streamlit 全改掉或共享私人库演示；前者扩大范围，后者混淆数据边界。
- 成本/风险：双界面暂存；生产登录与会话未完成，强制退出可能留临时目录。
- 适用：本机演示/开发；不能当作公网多用户服务认证。
- 锚点：`scripts/demo_resume_workbench.py::build_demo_app`、`src/job_agent/resume_workspace/main.py::create_app`。
- 验证：实际浏览器流程、前端 4 项/构建、演示忽略私有配置的测试。
- 状态：已实施。

## D-008：采用用户的阶段留痕协议

- 阶段：M1/M2 后的文档补录，用户明确要求长期保留。
- 问题：只有对话和最终 README 不足以恢复开发、学习实现理由或追溯每一步。
- 采用：根 AGENTS、继续开发手册、INDEX、模板阶段报告、架构/决策和证据；原压缩包全文归档。
- 备选：只在对话承诺记住；不能作为可检索、可入包的恢复依据。
- 成本/风险：需要维护准确性；补录必须标明时间和缺失的历史 Git 快照，不能编造开发时记录。
- 适用：后续各增量；记录随可工作功能更新，助手自主实现，用户事后学习。
- 锚点：`AGENTS.md`、`docs/CONTINUE_DEVELOPMENT.md`、`docs/devlog/INDEX.md`。
- 验证：本次源码锚点/链接/协议完整性及源码未改变检查，见 evidence/backfill-validation.json。
- 状态：已采用；后续阶段持续执行。

## D-009：先补强常见 PDF 的结构解析，复用原件和引用约束

- 阶段：M2A。问题：已有 PDF 文字抽取，但依赖标签/管道的规则导致普通简历仍需重填。
- 采用：本地 Line+offset/段落/日期/头部联系方式启发式，表单自动填写，歧义留空提示，核对后保存。
- 备选：强制 LLM 有隐私/配置/费用/待验质量成本；OCR/视觉模型适配扫描与复杂版面，需要另行数据与部署验收。本次保留可选 LLM，不扩展 OCR。
- 收益：无需在线调用即可展示普通简历导入闭环；风险：名字/段落语义仍可能误分组，不承诺任意模板准确率。
- 锚点：`src/job_agent/resume_workspace/local_extraction.py::LocalExtractor.extract`、`src/job_agent/resume_workspace/parsing.py::materialize`。
- 验证：相关后端 174/0/0、前端 6/0/0、构建、合成 PDF 浏览器上传/原文高亮/无补填保存；同一合成样例目标字段 3/25→25/25，不能外推真实准确率。
- 状态：本地增量已验证；真实模型/扫描/复杂栏待验。

## D-010：用当前版本适配 Evidence 内核，保留 C1 边界

- 阶段：M3。问题：原件全文包含已删除字段，旧文件仓库不等于新版本库。
- 采用：当前版本非 personal 字段逐事实 C1 视图、JD 独立；复用引用/等级/语义/投影内核，将分析快照存在 SQLite。
- 备选：原件全文直传或维护文件/SQLite 双仓，分别有版本错误和一致性/删除成本，不选。
- 边界：未直接调用旧 EvidenceV2Pipeline；虚拟来源路径只由只读适配器读取；不将 C1 升级，真实模型待验收。
- 锚点：`src/job_agent/resume_workspace/matching.py::VersionSourceStore`、`src/job_agent/resume_workspace/matching.py::validate_bundle`。
- 验证：27 新增用例含来源/等级/JD禁止/部分语义/限额/超时；相关 201/0/0。状态：本地+替身合同已验收。

## D-011：先实现事实不变的排序建议与持久请求键

- 问题：重点可调整，但引用证明不自动覆盖新句子的语义；模型重试还可能重复计费。
- 采用：仅移动已有条目，逐条核对、接受/拒绝；事务检查 head/事实清单，重试返回原版；分析预留 owner+request_key，模型总计最多 4 次、传输失败停止。
- 备选：自由改写或失败自动重跑，需要更强语义/计费/恢复保证，当前不选择。
- 风险：异常退出 running 需人工检查；排序不是完整内容优化；新请求键是显式新执行，不承诺外部 exactly-once。
- 锚点：`src/job_agent/resume_workspace/match_repository.py::MatchRepository.decide`、`src/job_agent/resume_workspace/matching.py::BoundedProvider`。
- 验证：并发/重复/拒绝/人工编辑失效、浏览器成第二版、15 项 HTTP；状态：本地闭环完成。

## D-012：用完整原句摘录实现首个协作动作

- 问题：原排序不能验证反馈协作；自由润色与现有逐字来源模型冲突。
- 采用：Writer 选原句、Reviewer 评审并反馈、Python 硬门与有界路由、用户审批；最多两次修订，原 SourceSpan、C1 不变，旧新 claim 投影不改。
- 备选：自由改写需独立语义合同，群聊额外增加成本，本轮不选。代价：只能摘录，不能承诺完整优化。
- 锚点：`src/job_agent/resume_workspace/collaboration.py::CollaborationEngine.execute`、`src/job_agent/resume_workspace/collaboration.py::hard_review`。
- 验证：42 新增、相关 243/0/0，浏览器真实反馈/改选/审批与17 HTTP；真实模型质量仍未测。

## D-013：应用 checkpoint 与不确定调用停止重放

- 问题：节点后恢复不代表模型未完成或未计费，自动重试可能重复派发。
- 采用：SQLite 节点 checkpoint + 调用前模型预留标记 + lease/token fencing + 同请求只返回记录。未知外部调用保守停止；最新稿/父版本绑定，决定事务幂等。
- 备选：原生 saver/生产 Worker 要适配另一状态和部署，本次不迁移；失败全部自动重放不满足计费边界。
- 锚点：`src/job_agent/resume_workspace/collaboration_repository.py::CollaborationRepository.claim`、`src/job_agent/resume_workspace/collaboration_repository.py::CollaborationRepository.decide`。
- 状态：本地故障注入/恢复合同已验；不宣称生产恢复、原生 saver 或跨系统 exactly-once。

## D-014：核验必须分层，确认不升级C1

- 问题：送审通过容易被理解成真实性核实。
- 采用：只读派生ProposalVerification，将来源/原句/相关性/独立真实性/用户决定/保存版本确认分开；原合同与存储状态不改。
- 备选：仅改文案仍缺机器可检查语义，因此接口和4个后端/2个前端用例一起补。
- 锚点：`src/job_agent/resume_workspace/collaboration_repository.py::CollaborationRepository._view`。
- 状态：接受/拒绝/确认后的not_verified/C1均测试，浏览器已验；不声称现实事实真实。

## D-015：复用题库内核，公开投影隔离面试评价

- 问题：旧应用库不等于新C1版本库；直接返回完整状态会泄题。
- 采用：新版本/JD适配；复用anchor/evaluate_answer；Evaluator私有反馈→Interviewer选择安全focus/action→Python渲染题目。活动API只发小投影，结束后仅已答复盘，有限轮次与请求键/checkpoint。
- 备选：整套旧服务强绑旧verified-claim与application仓库；自由生成问法灵活但泄题/越界面更大，本轮不选。代价：仅六anchor技术练习，不涵盖任意岗位。
- 锚点：`src/job_agent/resume_workspace/interview_collaboration.py::InterviewEngine.execute`、`src/job_agent/resume_workspace/interview_repository.py::InterviewRepository.get`、`src/job_agent/resume_workspace/interview_repository.py::InterviewRepository.review`。
- 验证：30新面试用例，相关291/0/0；浏览器反馈/换题/结束复盘/历史重开；在线替身预算/错误/权限合同。真实模型与质量收益未测。


## S8增量 · 2026-10-23

原LongTerm/CodeRAG/PublicKnowledge→固定合成dev/test DB+公共向量快照→EvalRun逐query→新目录/新进程同scope引用排序重放；文档编码计数0。原SharedRunState/Harness/Tools/Pack/所选TaskRepository→认证只读统一Trace，不建第二运行器或观测平台。旧事件时间unknown、根用量只汇总一次。与临时UUID重建相比，可核固定工件身份；代价是携带可信合成派生数据，hash不是恶意生产者签名。

开发BM25正基线减一题形成四门槛，多证据0基线仅观察；真实模型和人工不进普通CI。复杂重排/关系无全面收益，默认不因独立test成绩反调。用户延期的8题核对保持人工0。细节/ER/30分钟导读与实际结果见EXPAND-S8；最终打包审计尚在进行。


S8收尾：真实最终评测/固定索引新进程重放、原业务只读Trace、四项正阈值离线门禁、四演示、三包v2新目录实际启动均通过，详见EXPAND-S8。人工延期仍0/模型负结果/全仓历史边界保留；最终交付由包内manifest与同目录verification旁证固定。不扩监控平台/新向量库/第二项目。

## 2026-10-23 R0—R5最终增量

评价完整性在在线LLM提交边界强制，历史/规则默认仍兼容；来源学习在写入和读取时排除旧不完整LLM来源。DeepSeek配置经正式main传递，默认LLM关闭；真实固定题库来源学习和非照抄改写HTTP完成，仍不认定语义真值。FAISS改用原生文件流回调支持Windows中文路径，未新增数据库。研究允许明确owner_project_source、空公共研究范围不放松产品非空合同；真实40+10题先冻结/后评分并保留E留出6/16、默认入口0/40负结果。精确源码字节由* -text保留，避免跨平台Git自动行尾转换破坏模型/算法hash。交付仅Git审过路径，AGENTS采用已提交版本、并行教材改动保留。工程/真实业务/候选检索/人工0分层签出，16项旧资料缺失条件不伪造gold。详见REVIEW-R1至R5。
