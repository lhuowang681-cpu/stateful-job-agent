# Job Agent V3 继续开发手册

## 2026-10-23 第三轮当前入口

当前先读docs/tech-specs/CURRENT_SPEC.md、docs/devlog/RAG-F2.md及RAG-F4.md；第三轮新16一次528检索0错，Dense11/12、修复关系7/12，默认无Embedding后补已见诊断6/12。F3边界贯穿且原R1门禁不变；F4正式10例4完成来源观察/6模型门禁停止，另T2真实完整同来源学习已验；全轮24本地生成；新增云端/付费0，人工0。两模板已跟踪，最终稳定650通过/34条件跳过与离线门禁通过，91.10秒；新包从审核提交生成，包后校验/安装/HTTP记录在交付目录verification.json单列。学习与复现入口为docs/learning/RAG_ROUND3_ROUTE.md和docs/demo/RAG_ROUND3_RUNBOOK.md。下方R0—R5/S0—S8均为旧结果，不用来替代本轮模型证据。

## 2026-10-23 当前复核交接

当前以docs/tech-specs/CURRENT_SPEC.md和docs/devlog/REVIEW-R5.md为准。修复LLM缺失/空逐点评价错误推进与虚假来源观察，保留历史/规则兼容及unknown不重派；统一安装依赖、wheel资源与中文FAISS路径，补齐PDF worker。最终Windows全仓1051通过/16原始历史资料缺失失败/84条件跳过，最终解包Linux空环境609通过/35跳过与门禁通过，前端13测试/构建通过。

真实DeepSeek当前源码非照抄改写/审批和固定引用完整学习HTTP闭环已验，180实际调用usage台账保留；冻结10新例×3×3路径没有首稿后的文案提升结论。真实项目40+10中文候选、真实检索与新进程重放完成；主留出E完整gold6/16、默认入口项目范围0/40、手选39/40，负结果与无答案政策不足保留。人工8题继续延期/0。新三包及复现旁证在output/review-20261023/delivery-r5-v1，学习增量见docs/learning/REVIEW_30_MINUTE_ROUTE.md。

以下为旧轮次历史记录，不能用旧待办、旧HEAD或旧分数替代本轮结果。


本轮复核结果与明确保留条件见上方当前交接。下方S0—S8旧待办按历史理解；不触发重复付费测试或覆盖旧包。

2026-10-23工程收尾：S0—S8核心工程验收完成，人工支持/近重复核对由用户明确延期仍0。相关612/0/4、离线583/0/33及正阈值门禁通过；真实RAG dev/test各630调用0错/新目录新进程各210组合重放文档编码0；四演示含12场景真实恢复通过。三包v2解压后逐字节/CPU门禁/真实HTTP/7 Trace已验，首v1漏模块失败保留。最终三包在output/expansion/delivery-final，以同目录verification.json旁证；当前代码/完整限制与30分钟导读见EXPAND-S8。专用临时验收服务已停、数据保留，旧服务未动。不因人工延期继续扩范围，旧段落状态为历史。

2026-10-23最终回归补录：相关612/0/4，离线583/0/33与正阈值门禁通过；全仓1024/44/54（41旧资源/2旧Redis端口/1无Git），四演示和12场景恢复已过。研究/Trace工程已验，最终三包解压启动检查进行中。人工由用户延期仍0；旧段落中的“测试运行中/未评分”以此及EXPAND-S8最新数据为准。

## 2026-10-23 最新S8检查点

S8已实现：固定72候选/26源，Markdown标题/段落切分chunks-3-markdown-1；真实A—G dev/test各630调用0错误，固定研究索引新目录/新进程分别210组合同引用与候选排序，文档编码0。四正阈值CPU门禁通过，多证据0开发基线仅观察。统一Trace三个原API只读导出/脱敏/用量不翻倍，ACK规则反例5合同通过并走来源学习；三条HTTP演示通过，恢复演示删除后trace404探针首轮误判已保留，修正后矩阵运行中。

先读EXPAND-S8和S8 Spec；正在跑覆盖S7全部模块的相关回归及全仓诊断，然后固定工件进测试fixture、稳定CI/源码学习研究包、解包启动与需求逐项审计。用户明确稍后人工核对、继续工程；human0，不重复催问。不改第二项目/handbook。最后源码身份待最终checkpoint，不用S7 c603代称当前源码。整体Goal仍active。

## 2026-10-22 深化扩展执行检查点（优先于旧冻结描述）

S0—S8开发Goal已建立，按总计划2.0自主推进，仅写job-agent-v3；不修改兄弟项目/根共享计划。
本地无.git，修改前hash见devlog/evidence/expansion/s0-start.json；远端旧agent-backend-service不是当前新版，保留不动。用户提供SSH运行资源后，新版独立放在`/root/autodl-tmp/study/job-agent-v3`，.venv复用job-agent-mcp系统包并隔离新增解析依赖；凭据不入文档。
较早首个增量记录（保留历史，当时尚无重排）：基线相关246、身份首轮47、预热后相关264通过；真实Uvicorn/HTTP/Worker合成链及Qwen3-Embedding-0.6B cuda:0检索通过（6检查/7查询）。后续重排结果见下方最新检查点，人工gold仍待做。
较早增量使用CURRENT_SPEC0.2；当前以0.8及devlog/INDEX最新状态为准。S0—S7的Spec/报告有实际证据与25—30分钟导读，不重复全文阅读旧报告。

最新S7：先Spec1.0，当前Spec1.1/EXPAND-S7含实体/调用/数据字典/30分钟单元。来源观察与面试同SQLite，原图固定题面/focus/rubric/引用再练习；用户纠正/撤回/删除、明确偏好、90天待重核、历史版本同意、上海日有限建议已接线，C1/原评价/活视图/unknown保护不变。最后517通过/4既有参数跳过（JUnit50.353秒）；规则HTTP5检查与PG项目HTTP7检查均通过，前端13与构建通过。浏览器合成2场6观察、纠正/暂停/撤回/偏好/重启留存与额度已验。Qwen7B首评价缺部分要点被拒绝，实际1调用失败记录保留，不称LLM完整学习闭环或教学效果。

最后源码c603ae740483bdd56cbc4148c538858f7f7a07c66ea5086f043dd44349c9fc14；s7-related-v3.xml、s7-http-{rules,pg}-v3.json、s7-http-qwen-v1.json、s7-summary.json为入口。最终合成UI PID112423/loopback8119，旧109328核cmdline后停止；本机SSH转发仅loopback8119。S8清理/交付前核当前PID，不杀旧服务。已发现并修复撤回退款额度及指纹变更重建删除观察，合同在最后517内。下一步S1最终候选与S8统一trace/研究重放/交付；整体Goal仍active，不能因本阶段完成而结束总目标。另一个聊天的handbook不动。
此前基线检查点（已由下条替代）：补UI后全仓839/45/50；45项逐项归因41缺历史资料、2 Redis、1 Git、1本次Qwen兼容回归。最后一项修复且77定向通过，原始失败保留；不自动复制可能含私料的旧评测。S1冻结18原文/32 AI候选（20dev/12test），静态合同9通过，人工0/test未评分。PG/Redis四端口实测无监听，未接产品。完整导航以devlog/INDEX为准，不重复全文读旧报告。

S4检查点保留：两图SharedRunState/逐断言C1门禁/反馈/未知派发/并发恢复已实现；最后435相关通过31.45秒。Qwen7B真HTTP反馈改问，12例×3路径×3重复108行239次生成/6次小消融完成；无可用改稿增益，保留默认简单规则/人工审批，误读/保留原文如实记录。正式/首HTTP源码5869fa62ee11ef62f98839c18eefc9874affc6970ae0684063c785417c80f377；最后控制/435源码9d5b32c054309bccc65ea6ad99cc194f2c959be1298adf0abb75caa154ff9fef。S3锁故障与修复保留。

最新S5检查点：CURRENT_SPEC0.6/EXPAND-S5/Spec1.1已同步。三类仓储已抽离，CodeRAG无SQL；默认SQLite，显式同PG项目/快照/不可变索引/任务。DB时间lease/token/config/generation、指针/派生/任务成功同事务，面试引用走选中CodeRAG。最后455通过/4限定跳过32.34秒，最后源码e5061d03c9756172c3c863bf5f8dce68302bd6089a49b291d4cfd6d2681dea2f（真实模型源码87606396，之后只补配额测试）；rules/Qwen各两进程HTTP、PG重启、独立worker、无SQLite影子、合成CLI迁移/hash/备份回滚及业务dump独立库恢复均已验。CLI迁移样例向量0，fixture向量迁移和真实PG向量重启分开记录。S5所有模型/测试/HTTP进程观察终止，PG实例保留S6。

PG资源：官方索引14.24，镜像包SHA逐一比对后项目内提取，没有系统安装；本轮/tmp/job-agent-v3-pg-s5-20261022（nobody、私有socket、listen_addresses空、55432），数据目录与server_pid见s5-pg-resource-v1.json。原镜像缓存14.23的404及官方包直连超时保留。psycopg3.3.4/libpq18为客户端。环境JOB_AGENT_TEST_PROJECT_DSN只指本轮专属socket/DB；测试建/清自己随机schema，不能指向生产。单业务重放包output/expansion/s5-http-qwen-replay-v1.tar.gz不是完整研究评测索引。

最新S6：先Spec1.0，当前Spec1.1/EXPAND-S6已含实现/真实ER/时序/30分钟导读。原HTTP→同PG task+Outbox→独立Publisher/Redis/原索引consumer→同PG发布/成功→ACK；模式固定/authority epoch、12次发送/3次执行、有限保留/游标/归档/对账。487通过/4限定跳过37.24秒，前端13与Vite生产构建通过（初次依赖DNS失败保留，随后同锁安装成功）；原矩阵v2 13场景/42子PID全部通过，v1最后socket就绪探针竞态保留。真实Qwen独立Publisher/Worker与新进程检索已验，无SQLite影子。最终补强A→B→A epoch/旧CLI停止后源码1be116abf36d714fdc7c05e3ad9967f8b17d9818c406cd0dc3ae9d212a259852；最后487已过，v3矩阵13/13及同源码Qwen两进程均通过。文本模型不入索引重放。

本轮Redis7.2.16仅UDS `/tmp/job-agent-v3-redis-s6-20261022.sock`、port0、配置/数据output/expansion/redis-s6；经历矩阵真实重启，不能用初始PID102102盲启。当前服务PID从socket info/redis.pid以及s6-current-services记录读取。PG14.24私有socket实例仍在，旧服务未动。源码/节点/子进程以当前文件/ps/JSON为准，不用观察超时猜停止。下一步S7先Spec；S1最终60—80候选/人工与S8完整研究重放/统一验收仍待做，生产SLA/容量未验。

## 2026-10-22 最新学习与优化交接

用户已明确后续补强RAG、协作、数据库/异步可靠性，每天7小时、每周7天，以详细Spec学习流程和设计为主。新增[当前实现总Spec](learning/EXISTING_CODE_SPEC.md)、[6章18任务](learning/DETAILED_LEARNING_STAGES.md)、[独立聊天交接](learning/CHAT_HANDOFF.md)。这些是依现有代码补建的教学说明，不虚构旧开发历史。后续增量先写详细开发Spec，再按真实代码/验证更新记录。下文旧源码熟悉优先或冻结描述按日期理解，当前用户请求优先。

## 2026-10-22 全过程资料汇总

新增根目录 DELIVERY_README.md、docs/learning/OPTIMIZATION_JOURNEY.md，串联原审计、M1–M3C、V3 F0–F7。总包为父目录 Job_Agent_Full_Source_And_Learning_2026-10-22.zip；核验结果见同目录 Job_Agent_Consolidated_Package_Check_2026-10-22.json。仅文档和归档，没有业务代码变更；工程成绩仍为下述 F7 历史结果。历史学习包保留，不用旧 ZIP 覆盖当前代码。打包过程与恢复条件见 devlog/DELIVERY_CONSOLIDATION_2026-10-22.md。

## 当前交付状态：F0–F7本地范围已完成，工程冻结

2026-10-21。最终交付见根FINAL_HANDOVER.md、FEATURE_MATRIX.md、docs/devlog/FINAL-F0…F7.md。LOCALLY_VERIFIED / LIVE_PENDING，不宣称完全生产可用。后续重点为源码理解与AI Agent实习面试准备，未经新指令不再扩展功能。

当前repo outputs/agent-backend-service，main/067bfc7d63408e1e6b0ab6c227e863bd08a5857a dirty；既存改动保留，无commit/push/reset。F0公开基线work/v3-f0-public-source-baseline.zip与f0-start.json保留；最新公开源码/学习包在outputs/Job_Agent_V3_LOCALLY_VERIFIED_Source.zip、Job_Agent_V3_Learning_Reports.zip，包内DELIVERY_MANIFEST与外部sha256可查。

真实浏览器8019：合成PDF文件选择器上传→16字段核对→v1→JD线索/缺口→局部改写审批v2→单独确认→PDF.js与真实下载→新ZIP上传→后台排队/完成→跨文件检索→项目源码反馈/测试追问→复盘→相关AST补弱→完成且不同题不算提升→岗位同卡关联v1/v2及2面试共3条；重启/刷新保留。三种面试均实际答复并结束。第二用户无主用户简历、只有自身1项目。

证据docs/devlog/evidence/v3/f7-demo-state.json、f5-live-worker-recovery.json、regression-summary.json，脱敏实际轨迹docs/devlog/traces/v3-source-interview.json；截图与正式下载PDF在docs/demo/artifacts。公开包候选解压后只加载包内job_agent，实际种子/前端/PDF输入到导出/完整字体验证成功，见f7-package-smoke.json；现有依赖runtime复用，不称新安装/Docker验证。

最后完整后端907项：855通过/2失败/50跳过，work/v3-f7-final-full.xml/log，169.92秒。2项Redis127.0.0.1:63799缺服务；34 PG+16模型/Embedding/opt-in条件跳过。最后相关78/0/0，24.12秒。前端最后13/0/0、构建通过（v3-f7-ui-final-tests/build），卡片关联数同步/面试日期标签修复已实际浏览器验证。早先Windows深tmp路径失败用短basetemp复核，未改旧业务或删测试；无效basetmp参数未运行测试，保留失败记录。

F3 CodeRAG：Python AST/Tree-sitter静态符号/边，真实Starlette公开固定SHA104文件与CC0合成6文件；不执行源码，不认定用户作者。CodeRAG/公共检索已接真实面试工具及结束review。F4 RetrievalInterviewEngine扩展旧InterviewEngine/Repository，Registry/Policy/Executor复用；owner/project/snapshot服务绑定，18工具/6答/每主题1追问；同题同评价条件才比较末次要点，规则仍仅词面。
F5 tasks.py本地SQLite持久索引队列、心跳/三次恢复、发布同事务fencing；独立HTTP+2子Worker真实发布后故障→lease过期→SUCCEEDED/attempts2，同键去重，异主404。旧PG/Redis v1独立，不宣称已接新产品。

实验：40代码冻结题hash b1e59321b5d6631f3860e3a6fc461b70eed363d0ecf0ef493292ab0f6686edec不变；flat/code_aware文件Recall均1，MRR .75/1，跨文件均20/20，无召回增益。公共40项/39 query是实现后标签开发诊断，v1漏tags .50、v2修metadata 1.00 Recall，旧引用不改，两个结果保留；不称人工语义盲评。

明确阻塞：真实付费LLM/私人外发/私库/远端推送未授权，真实模型/向量/重排/人工盲评和协作收益LIVE_PENDING；OCR尝试RapidOCR+ONNX1.31/1.22.1原生DLL初始化失败，cap.ocr=false；当前无Docker/WSL发行版/PG/Redis，生产迁移/容器启动NOT_RUN。不得借历史R12 17JD/101原子93.07%/97.30%或Linux568/0/16当V3成绩。

开机：Python work/audit-venv，Node Codex runtime；已有frontend/dist，运行 python scripts/demo_resume_workbench.py --port 8019 --persistent --seed。主公开合成口令 job-agent-synthetic-demo-only-2026，第二用户 job-agent-second-demo-user-2026。只用合成/公开资料。当前本轮服务PID75736/session38452；tab7在8019。旧8012–8016非本轮创建，不停。8017/8018本轮历史PDF验证服务，可按精确PID/命令核实后清理，无需动其他Python进程。

后续学习入口learning/00_READ_FIRST→01_END_TO_END→02_MULTI_AGENT→03/04 RAG→05可靠性→06评测/INTERVIEW_QA；resume_notes含3条/5条真实简历稿。付费模型、私人材料外发、私库、推送、破坏性操作仍须明确授权。任何未来升级先读AGENTS、当前矩阵与失败记录，不用旧ZIP覆盖最新版。

以下为历史记录；遇到“尚未开始/止于M3C”等以本节V3最新状态为准。

更新：2026-10-20。用途：跨会话恢复开发，让用户事后能根据真实源码、理由和证据学习。
本文件和根目录 `AGENTS.md` 是后续项目工作的持久入口，不依赖对话摘要保留所有细节。

## 1. 用户的目标与工作方式

- 项目目标是完整的长期求职助手：简历导入/编辑、JD 匹配、受限优化、确认与 PDF，再到岗位、投递和面试历史。
- 代码由助手完成；用户重点理解遇到的问题、设计原因、收益、优势和限制，不要求用户写代码或逐步审批。
- 自主推进已授权的实现、必要测试和文档；每个可独立工作增量留下可学习记录。
- 重大架构替换、私人资料发送/真实模型付费等需要必要信息时再核实，不把日常实现变成人工等待点。
- 不为堆栈堆功能；不引入无关 Multi-Agent、额外数据库/队列；不把计划能力说成已接通。
- 最新用户授权按长期求职目标继续优化；已完成 M2A、M3 的 JD 分析/受限排序及 M3B 摘录式摘要协作首个闭环，后续按本文边界接续。

用户提供的压缩包内容已采纳为仓库开发留痕协议。完整原文、原文件 hash 和出处见
[PROTOCOL_SOURCE.md](devlog/PROTOCOL_SOURCE.md)。`CODEX_TASK_PROMPT.md` 仅是可复制的任务模板，
其中的占位“本阶段开发目标”不是已排队的新任务。

## 2. 恢复工作的固定阅读顺序

1. 根目录 [AGENTS.md](../AGENTS.md)：完整执行/记录协议。
2. [开发导航 INDEX](devlog/INDEX.md)：当前阶段、状态、验收和下一步。
3. 当前阶段报告；当前最新为 [PHASE-03C](devlog/PHASE-03C-verification-interview.md)，前置为 PHASE-01/02/02A/03/03B。
4. [当前架构](devlog/ARCHITECTURE_MAP.md) 与 [关键决策](devlog/DECISIONS.md)：确认真实边界。
5. 当前验证记录 [M3C verification](devlog/evidence/m3c-verification.json) 和 [PROJECT_AUDIT](PROJECT_AUDIT.md)。
6. 本手册的续作检查，以及待做任务的实际源码。最后核对用户最新指令。

不要把 `job-agent-harness` 旧项目当成当前源码；当前仓库目录名为 `agent-backend-service`。
从解压包恢复时以包内 manifest 校验内容；从工作区恢复时先查看 Git 状态，避免覆盖用户变更。

## 3. 当前可确定的状态

| 阶段 | 实际完成 | 验证范围 | 未完成 |
|---|---|---|---|
| M1 / PHASE-01 | 结构化事实、来源校验、不可变版本、确认/恢复/身份 API | 历史新增 34 项、相关合并 110 项通过；本地 HTTP 8 检查、合成版本 6 检查 | 当时无新前端/解析；不是 PG 产品迁移 |
| M2 / PHASE-02 | React、文本/PDF/DOCX 导入、规则/可选模型解析、补问、核对/编辑、来源管理、隔离 Demo | 历史相关后端 154/0/0，含新增 38；前端 4/0、构建和合成浏览器流程 | 真实模型质量/费用、JD/优化/PDF、新产品队列集成 |
| M2A / PHASE-02A | 普通文字 PDF 自动填姓名/联系方式/教育/工作/项目，保留引用与歧义提示 | 相关后端 174/0/0（新增 20）、前端 6/0/0、构建与真实浏览器合成 PDF 上传/核对/保存 | OCR、多栏泛化、真实简历质量/模型尚未验收 |
| M3 / PHASE-03 | JD/当前版本快照、Evidence 内核适配、本地预检查/可选模型、条目排序接受拒绝 | 相关后端 201/0/0（新增 27）、前端 9/0/0、构建、合成浏览器/15 HTTP 检查 | 真实模型质量、自由改写、补充 C2/C3、生产 Worker |

历史审计基线 568/0/16 来自 Linux 真 PG/Redis 环境；M1/M2 是另一次 Windows 相关模块验收，
不能混用。测试集合扩展不等于模型质量提升。历史 R12 93.07%/97.30% 也不是新产品解析成绩。

源码基线补录时核验为 `main` / `067bfc7d63408e1e6b0ab6c227e863bd08a5857a`；工作区有既存未提交变更。
原阶段开始时的完整 status 未留存，保持“未核实”；本次补录前后 Git 快照与源码 hashes 在
`docs/devlog/evidence/`。`git diff --stat` 不包含 untracked 新文件，阶段源码包差异用于补足追踪。
没有新的提交/push/reset/rebase 授权，不执行这些操作。

## 4. 以后每阶段必须遵守的留痕协议

### 开始前

- 更新 INDEX：目标、范围、验收条件、已有功能/问题、计划测试命令、阶段报告链接。
- 记录真实 branch/HEAD/status；不确定的内容明确写未核实。
- 检查当前报告、源代码与测试，确定此次增量边界；不为统一入口而无条件重写旧系统。

### 每个独立可运行功能完成时

及时在当前报告更新 5～12 行的功能轨迹：

1. 问题/场景。
2. 方案、关键权衡、至少一个备选及不选原因。
3. 真实 `相对路径::类/函数`，输入/输出或合同。
4. 从 UI/API 到服务/工具/存储/输出的实际调用链。
5. 实际命令、结果、数据/日志证据。
6. 失败、限制和未验证部分。

优先 3～10 个关键锚点，核实符号，避免只列所有文件；及时落盘，方便中断后恢复。
仅总结可验证设计理由与权衡，不输出内部隐含推理过程。

### 阶段结束

按 [_PHASE_TEMPLATE.md](devlog/_PHASE_TEMPLATE.md) 完成 10 节：目标、基线、方案、调用链/代码图、
功能轨迹、复现验证、同口径效果、风险/下一步、30～60 分钟学习路线、5 个真实面试追问及回答要点。
同步 INDEX、ARCHITECTURE_MAP、DECISIONS；保留差异和证据，更新 README/简历范围。
最终汇报优先为：完成情况 / 重点改动 / 可复现验证 / 尚未完成 / 先读文件 / 需要用户决策事项。

无对照就写尚无结论，不编造提升率。Mock/规则/局部单元/真实模型/真实服务/浏览器手工验收分别表述。
已有授权才提交；未提交以 HEAD + diff/快照记录，不自动覆盖工作区或推送。

## 5. 恢复运行和验证

以下为从源码重建的步骤；安装依赖不等于测试已经通过。历史实际命令在相应 verification.json。
此前协议补录仅改记录；最新 M3C 改核验/面试适配并完成相关回归291/0/0、前端13/0/0、构建和合成浏览器/两阶段HTTP，未重跑全仓库/生产服务。

```powershell
# 在项目根目录，Python 3.11+
python -m pip install -e ".[dev,workbench]"
# 包含 frontend/dist 时可直接启动隔离合成 Demo
python scripts/demo_resume_workbench.py --port 8016
```

默认本机 8012，可用 `--port 8013` 避免旧进程占用；M2A 旧演示 8013，M3 历史演示 8014，M3B 历史演示8015，M3C 最新演示在 `http://127.0.0.1:8016/`。重启服务才能加载新 Python 代码；不要只刷新旧 8012 页面就认为后端已更新。
公开演示口令仅见脚本/第 2 步说明，不能拿它替代私有工作区口令。
脚本使用临时库且不配置模型，不读取私人工作区配置。正常退出清理；强制停止可能有临时遗留。
服务是否仍在运行需实际检查，不能从浏览器 ambient URL 或旧截图推断。

重建前端（Node 22.12+，此前实测 24.19.0）：

```powershell
cd frontend
npm ci --ignore-scripts
npm test
npm run build
cd ..
python -m pytest -q tests/test_resume_workspace.py tests/test_resume_import.py tests/test_resume_pdf_autofill.py tests/test_resume_matching.py
```

私有工作区使用 `resume_workspace.main:create_app` 和私有环境口令；模型需显式 enable/key 及每次发送同意。
完整启动步骤见 [M2 说明](upgrade/02_IMPORT_PARSE_EDITOR.md)，不在日志写入真实令牌。
API 测试需要本机 socketpair；沙箱不允许 loopback 时申请必要权限，不改代码绕开逻辑。
真实模型、PG/Redis 需要对应条件，缺条件写未运行，不将历史结果当本次通过。

## 6. 必须保护的边界

- 原始简历/人工补充是用户自述；用户确认不自动升级成 C2/C3。
- JD 和公共参考资料不能作为个人经历；检索相似度不代表证据支持。
- 原文不可改写；人工新增/修改独立保存，引用需验证 owner、kind、hash、字符范围。
- 新入口通过当前版本的 C1 事实视图复用 Evidence v2 要求/映射/等级/投影内核；未调用旧文件型 pipeline，未接 RAG/Worker/四角色统一流程。
- 不改变冻结 eval、标注、指标公式来凑分；真实模型历史结果按原范围保留。
- 不读取/输出/提交 `.env`、私人简历/JD/语料、真实 Key、原始敏感轨迹；使用合成或公开脱敏证据。
- 完整交付包排除 Git 历史、凭证、私人附件/库、runtime 数据、虚拟环境和依赖缓存；保留 manifest。

## 7. 下一阶段从哪里继续

M3 首个闭环已完成：看 PHASE-03、match_contracts.py、matching.py、match_repository.py 和 MatchingPanel.jsx。
分析只取所选版本的非 personal 字段，JD 独立；全部 C1，自述确认不升级，旧 Resume 投影仍无 C1 claim。
本地条目/术语预检查不代表语义判断；模型接口经替身测试，真实质量/费用未验收。
当前建议只调整原有条目顺序，不新增/改写事实；显式接受、事务检查 head、事实清单一致、追加未确认版本。
相同 owner/request_key 防重复执行；运行中/失败键不自动重发。异常退出 running 需人工检查，不能宣称 Worker 自动恢复或外部计费 exactly-once。

后续先完善真实模型与代表性合成/授权样例验收，再设计受限表达建议及其语义/数字/时间线校验；不要把排序描述成完整自由改写。
补充 C2/C3 证据需要独立可信类型和来源适配，不能只凭用户选择等级。随后推进既定 PDF/长期投递路线。
暂不为了匹配强行引入 ES/OCR/新队列。每次先更新阶段计划，保留冻结数据和历史包；不自动调用付费模型或发送私人资料。

## 8. 交付和恢复检查

继续前核对：最新用户要求、AGENTS、INDEX、阶段报告、实际代码、已测源码 hashes、未运行列表。
交付前核对：协议及手册入包、报告锚点有效、相对链接有效、旧包保留、当前源码与基线未被误覆盖。
本次补录有完整原文归档、M1/M2 快照 diff、静态校验报告；它们不能替代将来改代码后的测试。

## 9. 协作方案的授权与实际落实（最新）

用户于 2026-10-20 提供 Writer/Reviewer、Interviewer/Evaluator 两条反馈闭环建议并要求评审。
结论和候选次序见 [协作方案评审](devlog/COLLABORATION_DESIGN_REVIEW.md)：优先在 M3 后续补受限 Writer↔Reviewer，再随模拟面试复用已有 evaluate_answer→follow_up 基础。保留 PDF/长期求职业务主线，不从零再建一套面试或自由群聊框架。
该评审当时只读；用户随后明确“可以，继续”，已授权 M3B 摘录式摘要子集，未授权无限扩张架构。C1、原文核验、审批版本绑定、预算、幂等和独立对照评测均需保护；workflow 与 collaborative 不是严格互斥的技术等级。
后续按用户最新指令决定实现范围，先建阶段计划和验收，不把建议消息示例或预期收益当作真实运行结果。

### M3B 恢复与下一步检查

- 当前交付：Writer→Reviewer→确定性 Supervisor→最多两次修订→人工审批；仅完整经历原句复制进摘要，C1 不升级。见 PHASE-03B。
- 当前事实：42 新测试，相关 243/0/0、前端 11/0/0、构建及合成浏览器/17 HTTP。未跑全仓库/真实模型/生产服务/单 Agent 对照。
- 核心文件：collaboration_contracts.py、collaboration.py、collaboration_repository.py、collaboration_api.py（均在 src/job_agent/resume_workspace/）；frontend/src/CollaborationPanel.jsx。
- SQLite rw_collaborations/rw_collaboration_decisions；应用 checkpoint，非原生 LangGraph saver/旧 Worker。模型未知结果不自动重放，费用/未知 token 为 null，不承诺 exactly-once。
- 保留旧 UI/CLI/RAG/后端边界。M3 排序与 M3B 摘录是两个操作，不强行串成统一大图；后者从所选版本/JD 开始并有自己的快照。
- 当前完整源码包：outputs/job-agent-upgrade-m3b-collaboration-source.zip（工作区 outputs，同目录有 SHA256/包验证 JSON）。源码包不包含私人数据、凭证、虚拟环境、运行库和 Git 历史。
- 后续仍优先完整产品主线：PDF、长期投递、基于已有面试基础的协作；每次先建计划。真实模型验收需明确模型配置、授权样本和发送同意，不能自动读 Key 或发送私人简历。
- 本轮工程修改到此停止；下一轮以用户最新指令为准，不因评审文档中的候选项自行启动群聊/检索/队列开发。

## 10. 最新M3C：核验分层与面试协作

- 用户明确授权“2和3都做”，两项已完成本地闭环。恢复时先读PHASE-03C、m3c-verification.json，旧M3B的未接面试记录是当时状态。
- 核验字段由来源/完整摘录/相关性/独立真实性/用户接受/该次保存版本确认分别派生；C1/旧投影不变，用户确认不代表事实已经核实。
- 面试入口：MatchingPanel沿用保存JD→InterviewPanel→interview_api；也能在面试面板直接输入JD。绑定当前选择版本，match分析版可不同，但不复用旧版支持结论。
- 核心：resume_workspace/interview_contracts.py、interview_collaboration.py、interview_repository.py、interview_api.py（前缀src/job_agent/）。复用旧QuestionAnchorLibrary/evaluate_answer，不迁移旧应用/verified-claim库。
- 活动API只给公开问题/答案/安全交接，不返回rubric/评价/关注点；结束后review仅已答内容，结束不可恢复继续答。不是前端隐藏而服务器照发。
- 三主题、每主题一次追问、2～6答题轮；在线每答最多两次、全场最多12次模型预留；单次900输出token、材料JSON30000字符、无自动重试。规则演示不等于真实模型协作质量。
- SQLite rw_interviews/rw_interview_answers；请求/回答键、问题/修订检查、lease/token与应用checkpoint。未知模型禁止重放；未接原生saver或旧Worker，不宣称exactly-once。
- 最终相关291/0/0，新增34（核验4+面试30）；前端13/0/0；真实浏览器和活动14/14、结束15/15 HTTP通过。两阶段含公共重复项，不相加为29个独立用例。全仓库/真实模型/生产服务/同预算实验未运行。
- 当前完整源码包：工作区outputs/job-agent-upgrade-m3c-interview-source.zip，配套.sha256及m3c-package-verification.json；旧包保留。
- 下一产品主线：绑定已确认版本的模板/预览/PDF，再逐步做岗位、投递和长期面试记录；不因已有技术练习就称完整长期闭环。本轮不继续扩大题库/群聊/总线。
# 当前继续入口：Job Agent V3 FINAL-F0–F7（2026-10-20）

## 最新检查点（覆盖本节后续早期F0“运行中”描述）

F0工程审计/冻结协议完成，F1本地闭环完成，当前F2实施中；必须继续F2–F7，未满足完整交付。
F1最终310通过/0失败/0跳过（work/v3-f1-final.xml/log），前端13/0/0及build通过；真实在线Writer/Reviewer未调用，结构化Provider接口仅替身验收。
全量诊断work/v3-f0-full-diagnostic.xml/log为735通过/2Redis缺服务失败/50跳过（34PG+16模型条件），包含新增PDF8项；最初安静运行停止，没有称全通过。明细docs/devlog/evidence/v3/f0-f1-test-results.json。
新增PDFRepository/render_pdf，开放Noto字体随包嵌入，PDF.js同源Worker解决IAB空白插件问题。F1两模板/长链接分页/历史owner/删除和改写三稿六调用/硬门禁/审批血缘已测试。原ResumeFact原文相等不变。
浏览器tab7当前8018，临时合成演示，server PID31500/session2749；8017是本轮旧预览验证server PID19152/session2695，可在不再需要时仅停止本轮该进程，勿停止其他8012–8016。截图docs/demo/artifacts/f1-browser-pdf.png，PDF样例与逐页联系表同目录。
F2已新增long_term.py与project_import.py并注册API，但尚未测试/接UI，不可标完成。下一步：岗位/项目面板、owner/重启/版本和ZIP安全测试，修复后F3源码索引与GitHub安全导入。
F3 Tree-sitter0.26.0/JS0.25.0/TS0.23.2已安装，尚无索引主链。Code冻结集40题（20跨文件）在tests/fixtures/v3_frozen，SHA256 b1e59321b5d6631f3860e3a6fc461b70eed363d0ecf0ef493292ab0f6686edec，不改标签。
源码基线快照work/v3-f0-public-source-baseline.zip只读保留；新代码不能用旧源码包覆盖。字体17.8MB需在最终完整源码包显式包含，许可/来源assets/OFL.txt、FONT_SOURCE.json；历史包装脚本默认大小限制需注意。


最新用户授权完整实现docs/roadmap/JOB_AGENT_V3_FINAL_SPEC.md，保留此前全部源码/学习记录，不再按旧“止于M3C”边界执行。
当前F0：已完整阅读AGENTS与最终任务书，roadmap从用户ZIP导入，未覆盖源码；公开基线558文件/38dirty路径，HEAD 067bfc7d63408e1e6b0ab6c227e863bd08a5857a。详见docs/devlog/evidence/v3/f0-start.json与FINAL-F0.md。
全量pytest正在运行（work/v3-f0-pytest.log / v3-f0-junit.xml），前端13通过、build通过。真实模型路径显式移除，不调用付费模型。
下一步：登记全量基线/跳过原因，冻结合成检索与故障集，再开始F1实际PDF与产品编辑，持续推进F2–F7。保留原ResumeFact原文相等约束；语义改写使用独立提案和人工确认血缘。
环境：work/audit-venv Python3.12；Node24在Codex runtime；FAISS/ReportLab/pypdf已装，Docker/OCR/JS语法插件尚缺。旧演示进程可能占8012–8016，勿终止不属于本轮的进程。
不得读.env/私有DB或输出私料。未经用户明确授权不得付费模型、私料外发、私库访问、远端推送/破坏操作。客观阻塞逐项记录并继续其他任务。


第三轮包后实际收尾：固定54b8dce的三包已完成全部hash/CRC/解包、Linux空安装与正式main实际socket/静态资源、648通过35跳过及门禁、纯源审计。详见docs/devlog/RAG-F5-VERIFICATION.md；产品源码与F4 337份map一致，正式4/10完成、评分弱点与人工0不改。后续只按明确新范围继续，不自动追加模型或参数扫描。
