# Job Agent V3 开发轨迹 · 导航页

## 2026-10-23 旧项目快速走查与复习（日课安排）

按用户要求只读参考第二项目，新增[学习复习安排](../learning/STUDY_AND_REVIEW_PLAN.md)：Job Agent默认约1小时、6组旧主线快速走查、核心缺口与新增量深入；实际学后1/3/7天起始复习，三学习日盘点。进度保留0学习验收，复习队列初始空；没有后台提醒。详见[适配记录](STUDY-REVIEW-PLAN-2026-10-23.md)。

## 2026-10-23 搭建回放进度表（独立于产品开发）

按用户粘贴的阶段/子任务格式新增[A—J阶段50子任务进度](../learning/BUILD_PROGRESS.md)与[规格/验收卡](../learning/BUILD_TASK_SPECS.md)。已有代码状态与个人学习进度分开；教学依赖不是原始开发历史。当前学习0/50验收、B1初步讲解中；静态核对50任务/53处符号。详细证据与范围见[进度表记录](BUILD-LEARNING-PROGRESS-2026-10-23.md)。

## 2026-10-23 教材与学习技能更新（独立于产品开发）

用户要求补足具体教学内容并参考jerry-ai-dev学习系列技能。六章案例讲义、三模式项目内学习技能、空白评估记录与新版离线包已生成；原文/历史附录保留。详见[教材更新记录](HANDBOOK-TEXTBOOK-2026-10-23.md)。仅教材/技能静态验证及ZIP校验，未运行新的产品测试或模型调用，新版浏览器排版未复验。

## 2026-10-23 第三轮F0—F5（当前执行）

[本轮有限合同](../tech-specs/expansion/RAG-F0-F5.md)，基线240d1b0。先核真实项目面试用途/F0，再做8代表失败和独立分层评分/F1；最多两组有界dev候选、一次12—20新题正式评分，证据不足贯穿与真实项目/本地模型联合，最后模板/依赖检查及新包。新增付费调用0，项目代码不发云端；人工8题延期/0、16历史资料条件保留。阶段Spec先于实施；[F0](RAG-F0.md)、[F1](RAG-F1.md)、[F2](RAG-F2.md)、[F3](RAG-F3.md)工程与有限检索已记录，F4正式4/10完成、6门禁停止，T2真实项目同引用完整学习已验；24本地生成/云端0。F5两模板/Windows650通过34跳过，Linux新空环境648通过35跳过/门禁、正式main真实socket/5静态资源/纯源审计与三包全部hash已验，[包后证据](RAG-F5-VERIFICATION.md)单列，源包固定54b8dce。新16题一次正式528检索0错，Dense11/12、当前关系优先策略7/12最小支持；默认无Embedding单独已见诊断6/12，不混成新test。F3相关109通过，提示身份补验33通过/1条件跳过，尚非真实模型联合。并行教学导航段落与进度保留。

## 2026-10-23 复核后R0—R5（当前结果）

[本轮总报告](REVIEW-R5.md)、[当前Spec](../tech-specs/CURRENT_SPEC.md)、[30分钟增量](../learning/REVIEW_30_MINUTE_ROUTE.md)、[复现演示](../demo/REVIEW_RUNBOOK.md)。真实基线9dc50ef，R1先3红/11绿再修复；最终全仓1051通过/16缺原始历史资料失败/84条件跳过，Linux空环境604/34及门禁通过。真实DeepSeek非照抄改写与固定来源完整HTTP学习闭环已验，335份src身份相符；冻结90行/100实际调用没有首稿后的文案改善结论。

真实40代码主集+一次10设计补充共50中文问题，来源家族隔离、先dev冻结再新test、真实Qwen/CrossEncoder和固定索引重放；主集E完整gold从14/16降至6/16。自然默认项目范围0/40、手选39/40单列，无答案政策不足保留。人工0，语义支持/教学效果未核。新三包在output/review-20261023/delivery-r5-v1，同目录verification.json给出实际解包/安装/HTTP/门禁结果，旧包不覆盖。并行教材、技能、AGENTS改动不纳入本轮提交。

[R0基线](REVIEW-R0.md)；[R1完整性](REVIEW-R1.md)；[R2安装/全仓条件](REVIEW-R2.md)；[R3真实业务与公平对照](REVIEW-R3.md)；[R4真实语料结果](REVIEW-R4.md)；[实施前合同](../tech-specs/expansion/REVIEW-R0-R5.md)。以下S0—S8段落为旧轮次历史，不覆盖本轮数字。

2026-10-23工程收尾：S0—S8核心工程验收完成，人工支持/近重复核对由用户明确延期仍0。相关612/0/4、离线583/0/33及正阈值门禁通过；真实RAG dev/test各630调用0错/新目录新进程各210组合重放文档编码0；四演示含12场景真实恢复通过。三包v2解压后逐字节/CPU门禁/真实HTTP/7 Trace已验，首v1漏模块失败保留。最终三包在output/expansion/delivery-final，以同目录verification.json旁证；当前代码/完整限制与30分钟导读见EXPAND-S8。专用临时验收服务已停、数据保留，旧服务未动。不因人工延期继续扩范围，旧段落状态为历史。

2026-10-23最终回归补录：相关612/0/4，离线583/0/33与正阈值门禁通过；全仓1024/44/54（41旧资源/2旧Redis端口/1无Git），四演示和12场景恢复已过。研究/Trace工程已验，最终三包解压启动检查进行中。人工由用户延期仍0；旧段落中的“测试运行中/未评分”以此及EXPAND-S8最新数据为准。

## 2026-10-23 S8研究与追踪增量（交付检查中）

[EXPAND-S8](EXPAND-S8.md)、[Spec](../tech-specs/expansion/S8-observability-replay-delivery.md)、[只读Trace消费](../evaluation/expansion/TRACE_CONSUMER.md)。72候选/26源，人工用户延期仍0；真实Qwen/CrossEncoder dev/test各630调用0错误，新进程新目录分别210组合引用与候选序一致、文档编码0。Markdown结构切分73相关合同、重放14、Trace相关64、ACK5通过（集合有重叠，不相加）；三HTTP演示通过。恢复矩阵、完整相关/全仓诊断及实际解包交付继续，整体Goal未完成。

## 2026-10-22 S0—S8深化扩展执行（最新）

开发Goal已建立；执行总计划2.0，学习与开发双轨。范围仅本项目，旧冻结状态不限制已授权增量。

S8 in_progress：[实施前Spec](../tech-specs/expansion/S8-observability-replay-delivery.md)。目标为补S1最终72候选/人工状态、固定EvalRun与可重放研究索引、原流程统一追踪、离线门禁与整体交付审计；基线S7 517/0/4，模型失败保持失败。先数据/缓存/重放合同，再真实RAG新进程/追踪/扩大回归，计划报告EXPAND-S8；不碰第二项目/handbook，不自动扩大外围功能。
S0 verified（基线及失败分类，不是全绿）：[Spec](../tech-specs/expansion/S0-baseline.md)、[25分钟报告](EXPAND-S0.md)。相关基线246通过，前端13通过；补UI后全仓839/45/50。45项=41缺历史资源、2 Redis、1 Git、1本次Qwen回归；后者修复且77定向通过，原失败保留。
S1 in_progress：完整身份及18原文/32候选（20dev/12test）静态合同verified，人工0/test未评分；9合同通过。[Spec](../tech-specs/expansion/S1-corpus-contract.md)、[导读](EXPAND-S1.md)。60—80最终集/人工核查/实际EvalRun待做。
S2 verified（工程/真实后端/受控dev诊断）：配置/双路径/预热/重排/统一预算、真实GPU HTTP7检查/7检索/2面试及双进程索引复用通过。最新相关306通过，A—G开发诊断339调用0错误，人工0/独立test未评分，无泛化质量结论。[Spec](../tech-specs/expansion/S2-retrieval.md)、[报告与30分钟新增导读](EXPAND-S2.md)。Dense=Hybrid；重排略改善排序但更慢；关系无覆盖增益且MRR降，负结果保留。

下个执行节点：S1最终60—80候选与S8先Spec补统一trace/研究scope/可重放评测索引及整体交付；人工核对仍待，不能自动标人工完成。S5单业务dump已验，不称完整研究重放。源码留痕由scripts/expansion_checkpoint.py生成Python/前端hash与真实diff；不伪造Git历史。
S7工程/规则真实HTTP/PG来源/浏览器verified：[Spec1.1](../tech-specs/expansion/S7-learning-loop.md)、[实体/真实失败/30分钟报告](EXPAND-S7.md)。从已答完成复盘生成来源观察，明确核对/纠正/撤回/偏好、上海日有限复习与原图固定来源再练习。最后517/0/4（JUnit50.353秒），真实规则HTTP5检查/PG项目HTTP7检查、前端13/构建，合成浏览器2场6观察及最终服务重启留存/额度通过。Qwen7B首评价仅部分要点被现有门禁停止，1次真实生成保留失败，不称模型完整闭环或真人掌握。源码c603ae740483bdd56cbc4148c538858f7f7a07c66ea5086f043dd44349c9fc14；整体Goal仍未完成。
S3 verified（工程合同/合成HTTP）：[Spec1.2](../tech-specs/expansion/S3-evidence-pack.md)、[30分钟导读/真实失败](EXPAND-S3.md)。相关375通过20.25秒；真实Qwen+重排与规则各8流程检查/6 pack。两轮/5工具/父deadline/输入上界/引用与隐私已验，个人/运行成果不足与语义待判分开。373通过后真实HTTP仍锁等待，已改私有/公开引用复用当前事务，两项真实提交回归与原失败均保留；没有跳过校验或关闭worker。
S4 verified（工程/真实模型/候选对照）：[Spec](../tech-specs/expansion/S4-collaboration.md)、[30分钟导读与负结果](EXPAND-S4.md)。最后435相关通过31.45秒；共享执行状态/逐断言事实门禁/反馈/未知派发/并发恢复已验。Qwen7B两pilot、真实HTTP反馈改问、正式108行239调用和6次小消融完成，未测到可用改稿增益；默认保留简单规则/人工审批。真实模型有解释误读，人工语义质量未验。原76/2、命令错误和schema错误均保留，不把替身或安全拒绝包装为改写质量。S7—S8 planned。历史855/2/50不是本轮成绩。
基线：本地无.git，修改前794文件hash见evidence/expansion/s0-start.json；远端旧repo保留，独立job-agent-v3验证。
S5 verified（工程/隔离PG/合成迁移/真实Embedding）：[Spec1.1](../tech-specs/expansion/S5-postgres-slice.md)、[ER/时序与30分钟导读](EXPAND-S5.md)。最后455通过/4限定跳过32.34秒；真实PG14.24/rules和Qwen各两进程HTTP/项目面试/PG重启/独立worker/无SQLite影子写、迁移CLI dry-run/完整hash与ID/备份回滚、单业务dump独立库恢复已验。首轮252/1命名回归与包资源失败保留。最后源码e5061d03c9756172c3c863bf5f8dce68302bd6089a49b291d4cfd6d2681dea2f（比真实Qwen HTTP只多配额合同测试）；生产迁移/容量、Redis及完整研究索引未验。
S6工程/真实服务/独立进程/本地Embedding verified：[Spec1.1](../tech-specs/expansion/S6-outbox-streams.md)、[ER/矩阵与30分钟导读](EXPAND-S6.md)。原HTTP task+Outbox同PG事务→独立Publisher/Redis→原索引Worker→原PG发布/任务成功→ACK，单模式+authority epoch/归档/对账。最后487/0/4（37.24秒）；13场景42进程v2已通过，v1最后就绪竞态失败保留，最后源码1be116abf36d714fdc7c05e3ad9967f8b17d9818c406cd0dc3ae9d212a259852，最终v3矩阵13/13通过。真实Qwen独立Publisher/模型Worker/新进程查询已验，前端13及构建通过；文本模型unknown不重放，生产SLA/最终研究重放未验。Redis当前PID以s6-current-services-v2.json及实际socket为准，不能用初始102102盲启。
计划命令：隔离Python `-m pytest tests/test_resume_*.py tests/test_v3_*.py`，另跑合成基线及真实Embedding pilot，分别保留JUnit和JSON。

## 2026-10-22 Spec书籍阅读页

- 按用户请求，将11份现有Spec/学习/验收文档汇为[本地书籍阅读页](../learning/handbook/index.html)，包含六章十八任务、全文搜索和本地阅读进度。
- 本次阅读页操作仅新增阅读页与导航记录；未改业务实现或原Spec，未重新运行历史业务测试。
- 实际生成、浏览器检查和限制见[汇编记录](HANDBOOK-2026-10-22.md)；使用与重新生成见[说明](../learning/handbook/README.md)。

## 2026-10-22 既有代码学习规格补建

- 目标：按现有代码建立可独立学习的实现规格、教学增量与独立聊天交接，服务用户每天7小时的学习计划。
- 范围：只补文档与静态核对；不增加业务功能、不创建虚构历史提交、不复跑或改写历史模型指标。
- 基线：当前为完整源码ZIP解压目录，无`.git`；原交付HEAD仅作来源记录，非本目录Git状态。已有代码与历史记录保留。
- 验收：关键路径/符号核对；文档链接核对；当前实现、历史证据、教学重建和后续计划分开；形成两聊天的独立交接。
- 阶段报告：[既有实现学习规格补建](LEARNING-SPEC-2026-10-22.md)。状态：文档已完成；静态核验见父目录机器记录，不代表业务回归。
- 阅读入口：[当前实现Spec](../learning/EXISTING_CODE_SPEC.md)、[6章18任务](../learning/DETAILED_LEARNING_STAGES.md)、[增量概览](../learning/EXISTING_CODE_LEARNING_PATH.md)、[独立聊天交接](../learning/CHAT_HANDOFF.md)。
- 验证方式：使用标准库AST检查代码锚点、校验本轮新文档的相对链接及参考源码hash；不执行项目业务测试。

2026-10-22 汇总交付：[全过程学习报告](../learning/OPTIMIZATION_JOURNEY.md)、[交付导航](../../DELIVERY_README.md)、[归档记录](DELIVERY_CONSOLIDATION_2026-10-22.md)。仅文档与打包，未增加业务功能或重跑测试；当前验收仍以下表 F7 与 FINAL_HANDOVER 为准。

## V3 当前进展（优先于后续历史M编号）

| 阶段 | 状态/范围 | 实际证据 |
|---|---|---|
| [FINAL-F0](FINAL-F0.md) | DONE工程审计/协议/冻结数据 | 基线291/0/0；全量诊断735/2/50含新PDF8例 |
| [FINAL-F1](FINAL-F1.md) | DONE本地产品/PDF/局部改写 | 310/0/0、前端13/0/0、两模板真实浏览器/逐页渲染 |
| [FINAL-F2](FINAL-F2.md) | DONE岗位/项目权限底座 | 333/0/0；真实服务重启hash一致、第二用户隔离 |
| [FINAL-F3](FINAL-F3.md) | LOCALLY_VERIFIED双知识库/源码检索 | 114/0/0；真实开源及合成索引/UI；40题×5方法 |
| [FINAL-F4](FINAL-F4.md) | LOCALLY_VERIFIED / LIVE_PENDING受限工具/三模式 | 相关75/0/0；浏览器源码反馈→真实工具→测试引用追问 |
| [FINAL-F5](FINAL-F5.md) | 本地运行时验证，后台UI收尾 | 相关76/0/0；独立HTTP与2子Worker发布后故障恢复 |
| [FINAL-F6](FINAL-F6.md) | 本地实验已跑，真实模型/人工质量BLOCKED | 全量855/2/50；检索原始结果/失败保留 |
| [FINAL-F7](FINAL-F7.md) | LOCALLY_VERIFIED / LIVE_PENDING，工程冻结 | 连续PDF/ZIP/三模式/岗位/双用户已验；855/2/50，前端13/build，解压包烟测 |

唯一总任务书[FINAL_SPEC](../roadmap/JOB_AGENT_V3_FINAL_SPEC.md)，实际逐项状态见根目录FEATURE_MATRIX.md。学习路线：F1改写血缘/版本PDF→F2 owner/快照→F3解析/引用。付费模型、真实质量、PG/Redis产品集成未验收。

## 本轮补录计划

- 日期：2026-10-20。任务：采用用户压缩包的开发留痕协议，补齐已完成 M1/M2 的阶段报告、架构图、决策与继续开发手册。
- 范围：文档、协议和交付包；不开发 M3，不修改业务代码或冻结评测。
- 验收：两份报告按 10 节模板完成；路径/函数可核对；测试与失败记录能追溯；原始协议完整保留；代码 hashes 保持不变；文档与完整源码均可下载。
- 基线：`main` / `067bfc7d63408e1e6b0ab6c227e863bd08a5857a`，工作区含前轮未提交变更。
- 基线证据：[补录开始快照](evidence/backfill-start.json)。原 M1/M2 开始时的完整 Git 状态没有记录，不能事后伪造。
- 报告：[PHASE-01](PHASE-01-structured-resume.md)、[PHASE-02](PHASE-02-import-parse-editor.md)。补录内容已完成，最终静态校验记录见文末。

## 已完成：M2A · 普通 PDF 自动填表

- 用户新要求：导入简历后自动提取姓名、联系方式、教育、项目等，人工以核对为主。
- 范围：复用已有 PDF 文字抽取与来源校验，增强本地结构解析和导入反馈；不提前启动 M3，不接入 OCR/新数据库。
- 验收：普通无标签/空格分栏合成简历能自动填表并保存；字段仍逐字引用；歧义/缺失不补造；原 M1/M2 回归不受损。
- 基线：PDF 上传已存在，但规则依赖标签/管道分隔，每行正文可能误当成项目标题；在线模型接口存在但未实测。
- Git：main / 067bfc7d63408e1e6b0ab6c227e863bd08a5857a，既存未提交状态见 [m2a-start](evidence/m2a-start.json)。
- 计划验证：`python -m pytest -q tests/test_resume_workspace.py tests/test_resume_import.py tests/test_resume_pdf_autofill.py`；相关证据/来源回归；`npm test`、`npm run build`；合成 PDF 上传/保存 HTTP 和浏览器演示。
- 阶段报告：[PHASE-02A](PHASE-02A-pdf-autofill.md)。相关后端 174/0/0（含新增 20）、前端 6/0/0、构建及合成 PDF 浏览器上传/核对/保存通过；真实模型/复杂版式/OCR 未验收。验证见 [m2a-verification](evidence/m2a-verification.json)。

## 最新完成：M3 · JD 匹配与受限排序首个闭环

- 目标：选择已保存简历版本、输入 JD，逐项查看要求/原文/自述线索/缺口/冲突，保存分析快照，接受或拒绝原文排序建议生成新版。
- 范围：复用 Evidence v2 要求分析、映射、等级和投影逻辑；提供明确标识的本地条目/关键词预检查；可选模型受显式同意和总预算控制。不强接 RAG/Worker，不放宽 C1。
- 取舍：先做事实不变的条目排序，不生成自由改写或新业绩；C1 可帮助查找已有经历，但不能变成独立验证的新 claim。保留原文并单独确认新版。
- 基线：M2A 相关 174/0/0、前端 6/0/0；新 React 无 JD 入口。Git 见 [m3-start](evidence/m3-start.json)。
- 验收：JD/所选版本不可变快照、原文校验/隔离；本地预检查不冒充语义支持；同请求防重复模型执行；排序接受幂等、拒绝/并发/旧版本防覆盖；API/前端/合成浏览器闭环。
- 计划测试：先重跑上轮 174 项相关回归，再增加 tests/test_resume_matching.py；前端 node tests/build；实际合成 HTTP/浏览器验证。真实模型/生产服务不具备条件则明确未运行。
- 报告：[PHASE-03](PHASE-03-match-and-rewrite.md)，本地首个闭环已验证。相关后端 201/0/0（新增 27）、前端 9/0/0、构建、合成浏览器/15 项 HTTP 通过；真实模型/自由改写待验收或实现。见 [m3-verification](evidence/m3-verification.json)。未提交/推送。

## 最新完成：M3B · Writer/Reviewer 有界协作

- 用户已同意继续实现评审方案，先做简历协作，不开启面试协作/新框架。
- 合同：从所选版本的项目/工作描述逐字摘录到摘要，保留全句含否定/年限/职责范围和 C1 来源；不放行自由润色或新事实，不改变 ResumeFact/旧投影语义。
- 目标：LangGraph 编排 Writer→Reviewer→确定性路由→最多两次修订→用户逐条审批；展示真实类型消息和修订差异，版本/JD/草稿 hash 绑定。
- 持久化：复用 SQLite，节点后保存应用级 checkpoint；同请求幂等/互斥；未确定的外部调用不得自动重发；不宣称原生 checkpointer/Worker/计费 exactly-once。
- 基线：M3 相关 201/0/0、前端 9/0/0；本次先复跑，再新增协作、权限、预算、恢复、审批版本冲突与注入测试。Git 起点见 [m3b-start](evidence/m3b-start.json)。
- 验收：至少一条基于实际输入的退回/修订/再审轨迹；来源硬校验不可被模型同意覆盖；同意后只复制已有原文摘要并生成未确认新版；拒绝/重试/跨用户/旧反馈/恢复有测试。
- 计划命令：上一轮 201 项相关回归加 tests/test_resume_collaboration.py；node 前端测试/构建；合成 HTTP 与浏览器。真实模型和三组质量实验不具备条件则记录未运行。
- 报告：[PHASE-03B](PHASE-03B-writer-reviewer.md)，摘录式摘要本地闭环完成。最终相关后端 243/0/0（新增 42）、前端 11/0/0、构建和合成浏览器/17 HTTP 检查通过；真实模型与质量对照未运行。见 [verification](evidence/m3b-verification.json)。未提交/推送。

## 当前产品状态

新产品已接通导入/自动填表/版本、JD 本地预检查/可选证据模型适配/受限排序，以及 M3B 原文摘要的 Writer↔Reviewer 有界反馈、轨迹与逐条审批。M3C 增加核验分层、岗位→面试快照、评估/选题协作、结束复盘和历史重开；自由改写、PDF、长期投递仍未完成。
M1 历史相关回归 110/0/0；M2 历史相关回归 154/0/0、前端 4/0；真实模型未验收。
上列为 M1/M2 历史记录；新增 M2A 的相关回归 174/0/0、前端 6/0/0，详见 PHASE-02A。

## 开发进度

| 阶段 | 业务目标 | 状态 | 验收证据 | 报告 |
|---|---|---|---|---|
| 01 / M1 | 结构化事实、来源、不可变版本 API | 局部增量已验证 | [M1 verification](../audit/upgrade-m1/verification.json) | [PHASE-01](PHASE-01-structured-resume.md) |
| 02 / M2 | 导入、解析、人工核对与 React 编辑 | 本地增量已验证；真实模型未验收 | [M2 verification](../audit/upgrade-m2/verification.json) | [PHASE-02](PHASE-02-import-parse-editor.md) |
| 02A / M2A | 普通文字 PDF 自动填写简历字段 | 本地合成闭环已验证 | [M2A verification](evidence/m2a-verification.json) | [PHASE-02A](PHASE-02A-pdf-autofill.md) |
| 03 / M3 | JD 快照/证据内核适配/受限排序接受拒绝 | 首个本地闭环完成；真实模型和自由改写待验收/实现 | [M3 verification](evidence/m3-verification.json) | [PHASE-03](PHASE-03-match-and-rewrite.md) |
| 03B / M3B | 原文摘要的 Writer/Reviewer 反馈、恢复和逐条审批 | 本地闭环已验证；真实模型和质量对照未验收 | [M3B verification](evidence/m3b-verification.json) | [PHASE-03B](PHASE-03B-writer-reviewer.md) |
| 03C / M3C | 核验分层、岗位到面试协作/复盘 | 本地产品闭环通过；真实模型未验 | [M3C verification](evidence/m3c-verification.json) | [PHASE-03C](PHASE-03C-verification-interview.md) |
| 04 / M4 | 模板/预览/中文 PDF 与版本绑定 | 未开始 | 未运行 | 待阶段开始建报告 |
| 05 / M5 | 岗位/投递/面试长期闭环 | M3C技术练习子集已接；完整长期闭环未实现 | 仅M3C范围 | 长期闭环另建报告 |
| 06 / M6 | 产品 PG/Worker/RAG/OCR 集成与对照 | 未开始 | 未运行 | 待阶段开始建报告 |
| 07 / M7 | 全产品 E2E、真实模型验收和完整交付 | 未开始 | 未运行 | 待阶段开始建报告 |

### 编号对应

输入模板默认 01 为导入、02 为 JD 匹配。此前已经按 M1“底座”、M2“导入/编辑”分步实现，
所以本项目报告按这两个真实增量编号。**PHASE-02 不是 JD 匹配已完成**；JD 在 PHASE-03 完成首个闭环，详细边界以上表为准。
模板原文与默认四阶段保存在 [协议原文](PROTOCOL_SOURCE.md)，今后以本页七增量映射为准。

## 开始学习与继续开发

先读 [继续开发手册](../CONTINUE_DEVELOPMENT.md)，按 PHASE-01 → PHASE-02 学习。
重点代码：

1. `src/job_agent/resume_workspace/contracts.py::ResumeDocument`：结构化事实。
2. `frontend/src/main.jsx::App.parse`：当前用户入口。
3. `src/job_agent/resume_workspace/parsing.py::ResumeParser.parse`：规则/模型与预算。
4. `src/job_agent/resume_workspace/parsing.py::materialize`：引用与字段校验。
5. `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.accept_draft`：人工核对、来源和事务。

演示：项目根目录 `python scripts/demo_resume_workbench.py`；完整步骤见
[M2 演示说明](../upgrade/02_IMPORT_PARSE_EDITOR.md)。模型关闭、临时 SQLite、公开演示口令与私有模式分开。
旧 M2/M2A 演示为 8012/8013；M3 最新验收运行在 8014。使用 `--port 8014` 启动交付脚本，旧进程不会自动加载新 Python 代码。

## 最大风险与当前边界

- 在线模型已接接口但未实测质量/费用；测试替身和合成样例不能替代真实模型实验。
- 新 React 已通过版本适配复用 Evidence v2 内核；RAG、旧 Worker、四角色 LangGraph、自由改写尚未统一接通。
- 私人资料、来源等级、冻结标签与指标定义必须保护；不在日志写 Key 或原始私人材料。
- Git 工作区未提交；原阶段 Git start 未留存，快照只能证明公开文件内容，不能伪造提交历史。
- 无有效同口径质量对照，不能编造升级提升率。

## 本轮补录校验

静态校验与源码未改证明：[backfill-validation.json](evidence/backfill-validation.json)。
补录 Git 起终点：[开始](evidence/backfill-start.json)、[结束](evidence/backfill-end.json)。
阶段源码包差异：[phase-snapshots.json](evidence/phase-snapshots.json)。
旧首轮测试计数核对：[summary-reconciliation.json](evidence/summary-reconciliation.json)。
上述是文档/追溯验证，不冒充重新跑过业务回归。

## 配套材料

- [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md)：当前真实调用链。
- [DECISIONS.md](DECISIONS.md)：已实施与待验证的关键取舍。
- [_PHASE_TEMPLATE.md](_PHASE_TEMPLATE.md)：后续阶段模板。
- [CODEX_TASK_PROMPT.md](CODEX_TASK_PROMPT.md)：任务补充模板，不能自动触发新任务。
- [PROTOCOL_SOURCE.md](PROTOCOL_SOURCE.md)：用户压缩包的六份原始文档完整归档。

## 协作方向方案评审（历史，后续 M3B 已实施摘录子集）

用户提出两条协作路线，原 [候选设计评审](COLLABORATION_DESIGN_REVIEW.md) 是当时的只读记录；后续授权后的摘录子集见 PHASE-03B。面试协作、自由改写和对照收益仍未实施/验证。

## 最新完成：M3C · 核验分层与面试反馈协作

- 用户明确授权两项：拆清“核验通过”，随后接面试协作，保留简历→岗位→面试与后续 PDF/长期投递主线。
- 范围：原文来源、完整摘录、岗位相关判断、事实独立核实、用户接受/版本确认分层展示；不改变 C1/旧投影。
- 面试：复用现有 QuestionAnchorLibrary/evaluate_answer，绑定当前版本和 JD，Evaluator 的结构化缺口影响 Interviewer 追问/换题；最多六轮、每主题一次追问，零工具，有可见交接与结束后复盘。
- 隐私：活动面试只返回问题/答案/脱敏路由，不返回参考答案/评分要点；复盘仅结束后开放。自述不变成独立证明，未检出不代表没有能力。
- 可靠性：SQLite checkpoint/请求键/乐观版本与租约；未知模型调用不自动重放；不新加框架或重写旧面试系统。在线需配置与每次同意，本轮不调用真实模型。
- 基线：M3B 相关243/0/0、前端11/0/0、17 HTTP。先复跑并加现有面试模块测试；起点 [m3c-start](evidence/m3c-start.json)。
- 验收：分层状态准确；面试可从岗位入口发起，反馈真实改变下一题，预算/恢复/并发/防答案泄漏/跨用户有测试；浏览器闭环；文档/源码包同步。
- 报告：[PHASE-03C](PHASE-03C-verification-interview.md)。两项本地产品闭环完成；最终相关291/0/0（新增34）、前端13/0/0、构建、合成浏览器和两阶段HTTP（14/14、15/15，含重复检查）通过，真实模型/全仓库/生产服务未跑。见 [verification](evidence/m3c-verification.json)。下一主线仍为PDF和长期投递。
# V3 FinalScope 执行状态（优先于以下历史M编号）

最新：FINAL-F0工程基线DONE；[FINAL-F1](FINAL-F1.md)本地产品闭环DONE（310/0/0、前端13/0/0、实际双模板PDF浏览器预览）；[FINAL-F2](FINAL-F2.md)长期岗位/项目IN_PROGRESS。
真实模型、PG/Redis整合和F3–F7均不能标完成。F0全量诊断735/2/50的依赖失败与跳过仍保留。

- 当前FINAL-F0：以最新版dirty源码为基线，公开快照/哈希已保存；后端全量基线运行中，前端13/0/0及构建通过。
- 总任务书：[JOB_AGENT_V3_FINAL_SPEC](../roadmap/JOB_AGENT_V3_FINAL_SPEC.md)。顺序F0基线→F1产品/PDF→F2长期状态→F3双知识库→F4真实工具协作→F5可靠性→F6冻结实验→F7全链验收。
- 当前报告：[FINAL-F0](FINAL-F0.md)，协议：[BASELINES](../evaluation/BASELINES.md)。旧报告是已发生的历史，不当作V3全链验收。
- 不调用付费模型/外发私料/访问私库/远端推送；依赖缺失逐项记录，不阻止其他安全实现。

