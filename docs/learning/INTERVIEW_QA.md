# 基于真实源码的面试问答

回答结构建议：问题→方案→为什么→代价→真实验证。不要背不存在的生产规模或模型提升率。每组按给出的文件继续追问。

## 简历解析与版本（contracts/parsing/repository.py）
1. 为什么模型不直接返回Markdown简历？结构化Schema便于编辑、字段验证与模板复用；来源另存，方便定位幻觉。格式正确仍需业务校验。
2. PDF提取和简历解析有什么区别？ingestion先提文本，ResumeParser再识别字段；文字PDF可直接提，OCR当前因原生库环境阻塞，不声称图片都能识别。
3. 用户修改的文字仍算原文引用吗？不算。edit_version建新C1补充来源、追加版本，原始材料不改。确认只是用户确认，不能升级第三方证据等级。
4. 并发编辑如何避免覆盖？写事务与expected parent/head检查，只允许从当前基线追加。恢复旧版同样创建新版本，不复用旧确认。

## JD/Evidence（matching.py/evidence目录）
1. JD能进入用户经历证据池吗？不能，输入来源类型/允许材料分开，映射后重新校验source/hash/quote/offset/等级；JD只能表达要求。
2. supported是否等于现实已证实？语义支持与来源等级不同；C1自述未独立核实。partial、gap、conflict分别展示，检索lead不能直接supported。
3. 为什么短简历直接上下文而不强上RAG？小材料直读避免漏召回和索引维护；个人源码与公共知识按需检索。不同入口边界合理，不强行统一旧UI/CLI/RAG。
4. 本地预检查准确率多少？未测语义准确率；只按条目/已知术语找线索并明确标注。真实LLM与人工质量尚待授权，不引用历史R12冒充新结果。

## Writer/Reviewer（rewrite.py）
1. 为什么生成和核验独立？Writer负责表达，Reviewer独立检查事实扩大并给约束；反馈可改变下一稿，Python硬门禁不能由两模型共识覆盖。
2. 如何处理“提升80%”“3年生产经验”？新数字/技术/职责/否定范围变化会被hard_constraints拦截；中文所有语义无法规则穷尽，仍需独立审查和用户接受。
3. 怎样控制循环和成本？最多三稿六角色调用，输入/输出/时间上限，无自动schema修复或无限重试；模型结果未知不重复计费执行。真实收益消融未跑。
4. 审批为什么还要再次确认版本？接受提案只产生新用户自述版本；PDF只接受具体确认版hash，避免接受与正式导出混为一谈。

## 公共RAG（public_knowledge.py/public_seed.py）
1. 语料来自哪里？10份本项目原创CC0技术整理和10题，记录官方参考URL/版本/许可；不是抓取付费面经，也不称官方原文。
2. 如何避免答案泄漏？公开DTO排除rubric/aliases/followups；活动review409，结束仅复盘已答题。Interviewer只拿有限反馈，不拿Evaluator标准答案。
3. BM25和混合怎么选？准确术语优先关键词/标签；可注入真实向量再RRF。当前向量未配置，hybrid明确降级，不能把同分说成向量提升。
4. 最大真实失败是什么？BM25漏公开tags导致40标签诊断只召回一半；修索引后同标签重跑，保留v1/v2。但gold按标签派生，不是语义泛化成绩。

## Code-aware RAG（code_parser/code_rag.py）
1. 如何跨文件？AST/Tree-sitter提取符号、导入与可消歧静态引用，SQL存关系；精确符号→BM25→最多两跳展开，不需要图数据库。
2. 为什么不执行仓库获取调用图？代码不可信，而且运行依赖复杂。静态索引更安全可重复，代价是不完整；动态对象和反射不能猜。
3. 引用怎样证明准确？owner/project/snapshot/commit/path/hash/行原文逐项核对；旧引用不能转到新head，删项目后不可读。只证明定位，不证明本人贡献或运行成功。
4. 找到测试文件有什么用？能针对覆盖边界追问，界面写未执行测试；只有实际运行才可以说通过。引用与执行回执是两类证据。

## 有界面试协作（retrieval_interview/interview_tools.py）
1. 比顺序Prompt多什么？Evaluator建议使Interviewer选追问/转题与symbol/references/tests目标，真实读取返回新来源改变下一题，公开trace可查。
2. 工具权限靠Prompt吗？服务绑定租户和快照，Schema拒绝owner参数；复用PolicyEngine三层工具交集，ToolExecutor校验action digest与返回合同；18次总预算和重复指纹。
3. 哪些是模型、哪些是规则？在线分Evaluator/Interviewer两个Schema调用，显式同意；本地规则仅词面评价与确定性路由。替身RoutingProvider证明接口/派发，不证明真实LLM能力。
4. 薄弱项是能力判定吗？只是本轮未识别/未表达要点与专项建议，不等于用户不会。源码问题的规则评价不判断解释全部正确性。

## 后台与恢复（tasks.py/interview_repository.py）
1. 数据库、Checkpoint、队列的区别？数据库是事实/版本，Checkpoint是待执行步骤，队列安排领取；不能只靠消息保存长期状态。
2. Worker崩溃后怎样避免重复副作用？派生索引可重建；租约token/fencing在索引事务内检查。模型/外部未知副作用不在自动重放范围，不宣称exactly-once。
3. 为什么不用现成PG/Redis Worker直接跑？旧v1任务请求/执行器不同，当前环境也无服务；保留旧实现，本地SQLite最小适配实际跑通。生产迁移与Compose实测明确未验收。
4. 真实故障怎么测？独立HTTP+两个子Worker：索引提交后退出70，租约到期第二次成功，attempts2，同键同任务，异主404。不是mock队列；同样不是PG/Redis部署证明。

## PDF、隐私与评测（pdf_export.py/evaluation目录）
1. 为什么不用LLM生成PDF排版？模型输出结构化内容，确定性ReportLab两模板渲染；嵌入OFL中文字体，PDF.js显示真实PDF。长内容/分页/链接与版本hash均测试。
2. 为何不用iframe？真实IAB中空白，改同源PDF.js，不依赖插件；代价是字体与worker包体。输出文字可选中，不是截图PDF。
3. 哪些数据不得外发？私人经历/源码默认本地；在线模式每次同意具体范围。原始模型输入/密钥不写公开trace，源码不执行，ZIP/SSRF有边界。
4. 哪个数字能放心讲？40合成冻结题下指定检索指标及分母、855/2/50工程结果与未跑原因；不能说模型准确率或生产SLA。93.07%/97.30%只属于旧R12。
