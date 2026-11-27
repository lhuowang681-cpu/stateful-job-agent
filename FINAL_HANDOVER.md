# Job Agent V3 最终交付

交付范围：**LOCALLY_VERIFIED / LIVE_PENDING**。2026-10-21。F0–F7的本地产品、实际源码检索/有界协作、后台索引恢复、工程回归、连续演示和技术学习材料已实施；以下客观阻塞项明确保留，不能称全部生产能力完成。

仓库：`C:\Users\1\Documents\Codex\2026-10-18\ssh-p-27392-root-192-168-2\outputs\agent-backend-service`。
基线main，HEAD `067bfc7d63408e1e6b0ab6c227e863bd08a5857a`，交付为当前dirty工作树，没有提交/push/reset/覆盖旧包。F0源码快照/哈希记录保留；最终公开包的DELIVERY_MANIFEST.json逐文件SHA256标识实际交付内容，不用旧HEAD冒充新增代码已提交。

## A. 逐项验收

| 项目 | 结果 | 实际证据与边界 |
|---|---|---|
| F0审计/复用/冻结 | PASS | FINAL-F0、f0-start；40代码题hash不变，旧标签/实验保留 |
| 简历PDF/DOCX/文字解析核对/版本 | PASS本地 | 真实浏览器选择合成PDF→16项字段→人工核对→v1；来源/offset/hash/owner确定性校验 |
| JD/证据主链 | PASS接口/本地预检查；真实语义LIVE_PENDING | 直读短材料，已有Evidence内核适配；规则只找lead，JD不进入个人材料，C1不升格 |
| 局部Writer↔Reviewer/人工审批 | PASS机制；真实LLM质量BLOCKED | 独立Schema/有界修订/硬约束/新自述血缘；浏览器接受v2；拦截扩大事实的替身/规则测试不称真实LLM收益 |
| 中文PDF/两个模板/历史 | PASS | 两模板6/5页长样例逐页检查；F7实际确认v2→PDF.js→下载，1页可选文字、含新表述、hash一致 |
| 岗位/投递/版本/面试 | PASS本地 | 同岗位关联v1、v2源码场次和v2补弱场次共3条；已投递事件、重启/刷新保留；修正卡片关联数显示同步 |
| GitHub/ZIP/贡献/快照 | PASS公开/合成范围 | 真实公开Starlette固定SHA+许可；真实浏览器上传6文件ZIP；不执行源码；私库NOT_RUN |
| 公共知识库 | PASS机制/UI | 原创10摘要10题，版本/去重/来源/许可，公开题无rubric；岗位选题/结束复盘真实检索 |
| Python/JS/TS/TSX Code-aware RAG | PASS已测解析/引用范围 | AST/Tree-sitter、SQL符号/静态关系、精确函数/调用/测试引用；动态边保守，非运行时调用图 |
| 真向量/Hybrid/Reranker | NOT_RUN | 接口可注入真实Embedding，Demo未配；dense拒绝、hybrid明确BM25降级，不能宣传语义召回效果 |
| 三模式面试/有界工具/复盘补弱 | PASS本地规则/替身机制 | 浏览器job/project/weakness均实际回答并结束；反馈选目标→真实工具→测试引用；最多6答/18工具、活动答案隔离、暂停/历史 |
| 补弱前后对照 | PASS保守合同 | 同题/rubric/aliases/provider/model方比较末次要点；源码→概念题不同条件，浏览器明确not_comparable，不造提升率 |
| SQLite后台索引/幂等/恢复 | PASS本地真实服务 | 排队→Worker→索引完成；独立HTTP+2子Worker发布后故障/租约恢复、attempts2、同键同任务、异主404；写事务fencing |
| PG/Redis新产品集成 | BLOCKED/未适配 | 旧v1后端独立保留；当前2 Redis连接失败34 PG跳过，不拿历史Linux成绩替代 |
| 扫描OCR | BLOCKED | RapidOCR公开CPU组件实际尝试，ONNX1.31/1.22.1均本机原生初始化失败；cap.ocr=false，不接未经验证死代码 |
| 冻结/诊断检索实验 | PASS指定范围 | 40代码冻结题×5方法、公共40项标签诊断前后结果均保留；语义人工gold不足，不外推 |
| 真实模型/人工盲评/三组消融 | BLOCKED / LIVE_PENDING | 未获得付费/私人外发授权，无独立人工质量gold；没有虚构模型效果或费用 |
| 本地部署/连续浏览器 | PASS | 8019已实际运行并重启；合成PDF→v2→导出→ZIP→后台索引→三面试→岗位关联→第二用户隔离 |
| Docker/公网生产/账号系统 | NOT_RUN/未完成 | 容器文件已提供，本机无Docker/WSL发行版；本地令牌映射不是OIDC/注册；未云部署/私库/自动投递 |

更细状态CODE_PRESENT/WIRED_TO_UI/MOCK_TESTED/LIVE_TESTED/E2E_VERIFIED见FEATURE_MATRIX.md。

## B. 改动、理由和代价

| 核心文件（src/job_agent/resume_workspace，前端另列） | 具体变化/原因 | 潜在代价 |
|---|---|---|
| pdf_export.py / PDFPreview.jsx | 确认版PDF持久化、两模板/Noto嵌入、同源PDF.js；真实iframe空白后换预览 | 字体17.8MB及worker包体，必须保留OFL |
| rewrite.py / RewritePanel.jsx | 独立局部语义提案、Writer/Reviewer、硬门禁与审批为新C1 | 规则不穷尽中文语义，真实模型/人工核对必要 |
| long_term.py / project_import.py / JobsPanel/ProjectsPanel | 岗位事件/版本面试关联、不可变源码快照、ZIP防护/配额 | SQLite单机、项目规模限制，贡献只自述 |
| github_import.py | 严格公开URL/DNS/固定SHA/无凭据；保留API403与完整SHA成功路径 | 私库不支持，公开API配额会失败 |
| code_parser.py / code_rag.py | AST/Tree-sitter/静态边、符号/BM25/可选向量、完整性与引用门禁 | 动态不完整、解析器升级重建；当前无真实语义向量 |
| public_seed.py / public_knowledge.py / KnowledgePanel | 小授权语料、公开题DTO与私有rubric分离，修正BM25漏公开tags | 小库/标签诊断不证明泛化 |
| interview_contracts/repository/collaboration/api、retrieval_interview/interview_tools | 兼容旧请求hash/检查点，受控真实读取、三模式/暂停/保守对照 | 规划有边界，规则只词面，真实效果待验 |
| tasks.py / code_rag.build publish_guard / ProjectsPanel | 持久任务、claim/心跳/恢复上限、同事务fencing、后台进度 | 单机轮询，不宣称旧PG/Redis链已接产品 |
| eval_v3_*.py / verify_v3_*.py | 固定代码实验、公共诊断前后、真实Worker故障、浏览器后只读断言 | 不是人工模型质量评测 |
| README/architecture/evaluation/devlog/learning/resume_notes | 当前与旧入口、真实与未验、负结果、源码学习路线同步 | 历史记录保留，阅读以V3当前节优先 |

原Evidence确定性来源/等级/投影没有因RAG接入而放宽。原冻结数据/私有材料不改，不执行导入代码，不新增无关中间件。

## C. 最终测试与真实证据

业务代码最后修改后的全量：
```text
python -m pytest -q -ra --basetemp=<本轮新建的短目录> --junitxml=../../work/v3-f7-final-full.xml
855 passed / 2 failed / 50 skipped，pytest输出169.92秒
```
PGCONNECT_TIMEOUT=2仅缩短依赖检测；没有绕过Redis或改标签。2失败分别是test_backend_service_reliability中的provider admission公平/熔断与call-scoped合同，Redis127.0.0.1:63799连接拒绝。50跳过按真实原因：34 PG未启动；16真实模型/Embedding路径/显式opt-in条件未具备。它们不是通过。
此前全量853/3/50的深Windows文件路径失败已用短临时目录复核，未改旧业务；首次误拼--basetmp未执行测试，不计通过。

最后复盘/关联相关：`pytest tests/test_workbench_interview.py tests/test_v3_interview_tools.py tests/test_v3_tasks.py tests/test_v3_long_term.py -q …`，78/0/0，24.12秒。最终岗位显示修复仅改前端，之后`node --test src/model.test.js`13/0/0、Vite build通过；浏览器新增第三条关联时卡片同步显示3，面试选项显示日期/中文状态。
原始全量/相关JUnit与日志在工作区work/v3-*.xml/log；公开归纳与各skip原因在docs/devlog/evidence/v3/regression-summary.json（附原始文件SHA256），不会把未跑写通过。

可复现独立验证：
```text
python scripts/eval_v3_code.py
python scripts/eval_v3_public.py
python scripts/verify_v3_local_recovery.py
python scripts/verify_v3_demo_state.py
```
最后一个只读核对已经在浏览器建立的指定合成档案，需要先按Demo脚本操作；不是替代浏览器的伪E2E。证据：f5-live-worker-recovery.json、f7-demo-state.json、devlog/traces/v3-source-interview.json及docs/demo/artifacts截图/下载PDF。Worker首次CLI缺ROOT路径失败、GitHub403、OCR失败、公共漏标签与检索无召回增益均在FAILURE_CASES.md留存。

## D. 模型与指标口径

Demo实际模型调用0，没有付费请求，没有私人材料外发、私库访问或远端推送。真实provider接入层可配但LIVE_PENDING；token/费用未知的字段为null，不虚构0成本在线结果。公共资料和包内源代码均有来源/许可，源码只读。
40合成冻结代码题：flat/code_aware文件Recall@5均1.00，MRR .75/1.00，跨文件完整20/20；没有文件召回增益，不能外推复杂语义。公共40项只有39种query，tag派生诊断，v1 BM25 .50与v2 1.00 Recall均保留；标签gold不是人工语义准确率。Dense/Reranker/真实协作消融未跑。
旧R12 93.07%/97.30%仅17JD/101原子范围，不能用于V3。简历三条/五条可直接选用docs/resume_notes.md；不能宣称OCR/ES/Milvus/Neo4j/生产SLA或模型提升。

## E. 启动、交付包与学习

当前服务http://127.0.0.1:8019，主口令`job-agent-synthetic-demo-only-2026`；第二口令`job-agent-second-demo-user-2026`。它们是公开合成演示身份，不用于私人资料。服务重启：
```text
python scripts/demo_resume_workbench.py --port 8019 --persistent --seed
```
完整安装/私人本地配置/workbench.env.example/未运行的容器命令见docs/demo/DEPLOYMENT.md。已有frontend/dist随源码包提供，环境安装workbench依赖后可直接启动，不必重新装Node。

源代码包：`Job_Agent_V3_LOCALLY_VERIFIED_Source.zip`；学习包：`Job_Agent_V3_Learning_Reports.zip`，位于仓库父目录outputs。公开白名单包含当前源码/测试/前端构建/全部本轮学习与技术记录/带许可样例/字体；排除env/真实Key、私人材料、运行数据库、git/venv/node_modules、模型权重。DELIVERY_MANIFEST.json含逐文件hash，外部.sha256校验整包；交付脚本执行CRC与内容一致性核验。

1小时学习：00_READ_FIRST（10分钟跑Demo）→01_END_TO_END（10分钟）→02_MULTI_AGENT（10分钟）→03_PUBLIC_RAG/04_CODE_AWARE_RAG（10分钟）→05_RELIABLE_RUNTIME（10分钟）→06_EVALUATION/INTERVIEW_QA（10分钟）。每阶段报告保留问题、备选、理由、源码锚点、实际验证、失败和代价。

本地范围交付后冻结工程；真实模型/生产依赖/OCR环境修复如需继续，另行授权并按已有基线验证。后续重点转为源码理解与AI Agent实习面试准备，不自动新增功能。
