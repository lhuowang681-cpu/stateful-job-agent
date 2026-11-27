# S3 有界检索计划、EvidencePack与不足分层

版本1.2，2026-10-22；工程合同/合成HTTP verified，语义充分性待人工判定。依赖S1身份/原文合同、S2双知识service；复用既有ToolRegistry/Policy/Executor和18次会话工具上限。实际调整/失败/375项回归与两条HTTP路径见[EXPAND-S3](../../devlog/EXPAND-S3.md)。

## 场景与范围

输入“旧Worker回来了会不会覆盖新索引”，不能仅凭一个guard函数就说全部发布原子。先定位定义/发布证据，不足最多补一次，仍缺就返回可确认范围和缺什么。目标是有限检索决策和证据交接，不增加必调LLM分类器，不将“找齐几个文件”当语义支持，不把测试源码说成已跑测试。

备选无界自由工具循环难以保证预算；只跑一次top-k无法解释不足，采用规则计划+至多2检索轮+有限读取。来源原文仍不可信数据，指令不得扩展权限。

## 数据与状态合同

新增resume_workspace/evidence_pack.py：

- RetrievalScope来自服务端owner/project/snapshot或public（question/doc），不能由模型filter指定。
- RetrievalPlan包含query、kind（exact_symbol/semantic/cross_file/runtime_evidence）、scope、可用工具、第一次/修正query、最多2检索轮/5工具/输入模型预算上界/quote预算/调用前deadline。改写采用固定补充词（调用/定义/测试或runtime报告），不是伪造新的事实。
- PackItem包括原始EvidenceReference、可选符号/公开entry、location_valid、relevance=candidate；引用逐个重查owner/hash/quote/range，错误引用硬拒绝，不以补检索掩盖完整性损坏。内容相关、断言支持分别保持待判。
- ClaimAssessment独立于Reference，任意语义断言默认needs_judgment；可确定的“定位到了某原文”只代表定位。个人参与/量化成果请求缺独立材料标insufficient_evidence；自述和代码不升级independent_truth。来源相矛盾需显式证据，不凭词面编conflict。
- EvidencePack含pack/plan/config/trace身份、固定范围、两轮各自结果/原文引用/预算/降级/缺失、claim assessments、answer_policy（limited_source_only/needs_input）和visible_roles。所有状态有简短可审核理由，不存模型内部思维链。

## 工具与预算实现任务

1. InterviewTools新增retrieve_pack协调方法（不注册一个绕过计数的包装工具），每次search/get_symbol/find_references/read_code_range通过原run调用并计入state.tool_calls/指纹和18上限；计划自身不调用LLM。嵌套读取不得使用未计数的服务直连代替Agent选择的工具。原文校验属于确定性校验，不伪装额外模型决策。
2. 首轮精确符号/一般语义/跨文件仍复用code_search或question_search/knowledge_search。不足（空命中/机械跨文件覆盖未满足/请求运行成果但仅有代码）最多一次补search；必要时有限读取定义或静态引用。两轮结果保留，不覆盖第一次。机械覆盖不是人工语义充分性。
3. 所有调用前检查剩余会话/本pack工具次数、deadline、模型调用/输入上界、quote字符；到限输出budget_exhausted和已有可引用内容，不再继续。同步GPU无硬抢占保证，调用后超时停止后续步骤并标明超限。
4. InterviewState增加内部evidence_packs；RetrievalInterviewEngine.prepare消费pack的安全item选题，仍通过已有private_question内部取rubric；活动HTTP视图只公开允许的题面/来源位置和安全摘要，不能泄露技术参考答案/别题rubric。Evaluator/Interviewer收到同一pack身份与分层状态，未知支持不得自动放行。后续S4再补完整共享State和事实审查。
5. followup原get_symbol/find_references仍计数；新增读取结果按同引用合同校验后更新pack，不重新执行已经完成的工具或未知模型动作。
6. 新增鉴权HTTP `/api/v2/evidence/retrieve` 供合成验收/后续写作使用：输入query/scope/项目快照/待判claims，scope私有时先查owner。独立请求使用同Registry/Policy/Executor及临时执行state，而非无限服务直调；请求体不接受owner。缺来源与非法来源分别返回不足/404/409。

### 实施前预算补充

- 工具结果在32K序列化上限之前做确定性投影：引用整段预算8000字符，公开entry不重复携带body（正文仍在reference.quote），省略整段留下位置和原因；保留候选trace。太大的代码段可用计数内的read_code_range读取有限完整行，不自行拼造引用。Public全条目引用不可随意截短。
- 父计划deadline传入ToolContext；既有ToolExecutor需取`min(父deadline, 当前+工具timeout)`，不能重设延长父时限。只保证调用前/后拒绝晚结果，不宣称硬中止GPU。新增父deadline单测并复跑原运行时合同。
- 每次搜索预留真实已配置后端的模型调用/输入上界：Embedding query≤1024 token，重排≤30×512 pair token；最多2搜索轮，总上界≤32768。记录reserved upper bound，不能冒称实测token用量。读取不预留模型预算，所有搜索/读取仍走原18次计数。
- 缺命中只说明retrieval_empty/answerability_unknown；仅范围确实没有资料才no_material_in_scope。请求个人贡献或量化运行结果，源码/测试文件不足以证明，返回needs_input；语义支持待人工/后续Reviewer，不靠命中数自动通过。
- 结束后review现有资源循环会直调knowledge最多6次，未进入会话tool_trace。改为完成/owner gate之后独立有ID的资源检索pack（最多2检索/2工具/同模型预算），显式标为post_review执行，不假装已计入场内18次；活动场内仍≤18。保留learning_resources外形，增加资源pack/usage摘要，避免无计数的嵌套资源循环。

## 验证与文件级任务

evidence_pack.py实现合同/规则规划/有界执行；interview_tools.py接原工具计数；interview_contracts.py/engine接内部pack；api.py安装新路由；test_v3_evidence_pack.py覆盖精确符号、跨文件、空/无答案、恶意文档指令、删除/过期/篡改引用、跨owner、剩余工具不足、两轮终止、前后覆盖/花费，以及活动面试不泄答案。真实HTTP合成脚本加入正常/不足案例；模型路径和规则路径分别报告。

相关旧面试回归必须通过，反馈仍改变追问；引用硬约束逐项拒绝。语义支持人工未核时明确待判，不能称100%准确。实验记录首轮与补轮的命中/引用增量、候选/延迟/模型调用；不能仅按工具次数增加宣称更好。

## 回滚与学习

### 真实HTTP暴露的事务补充（实施中）

373项相关回归通过后，带独立索引worker的真实HTTP首次在面试读取时发生SQLite database locked，失败日志保留为s3-http-model-v2-failed.log。外层状态读事务持有SHARED锁，后台worker提交进入PENDING，引用校验再开连接请求新的SHARED，形成等待环。修复要求：InterviewRepository._load内所有私有/公开引用校验复用调用方当前数据库事务；CodeRAG读取和公开知识校验提供仅内部使用的可选db参数，默认独立调用兼容原行为。不能仅延长超时、关闭worker或跳过引用完整性检查。增加真实并发提交回归，确认状态读结束后写事务确实提交，而非仅没有抛异常。

新增字段有默认值兼容旧SQLite checkpoint；不改旧来源/C1/审批，不迁移个人数据。回滚需依本轮diff恢复旧引擎接线，尚无单独运行时开关；保留已产生trace/pack。收尾同步CURRENT_SPEC/CHANGELOG/EXPAND-S3/架构图和必要决策；交付一张状态图、3—5源码入口、一个不足反例、5面试追问和20—40分钟导读。
