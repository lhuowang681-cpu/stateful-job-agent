# FINAL-F4 — 有界检索协作与三种面试

状态：LOCALLY_VERIFIED / LIVE_PENDING，2026-10-21，main/067bfc7 dirty，保留既存修改。F3相关114/0/0、前端13/0/0/build、200次冻结检索原始结果已留存；真实模型调用未授权。

## 1. 问题与计划
旧面试只能从固定题库顺序选主题，Evaluator虽能改变追问，但不能请求项目源码。复用现有InterviewRepository的版本/JD、租约、检查点与答案隔离；复用ToolRegistry/PolicyEngine/ToolExecutor，不新造自由群聊框架。

## 2. 最小方案与验收
新增显式检索模式，旧请求默认保持旧流程。岗位/项目/薄弱项均绑定版本；公开题目不含答案，私人代码工具由服务绑定owner/project/snapshot，模型不可换租户。Evaluator有限反馈→Interviewer选择后续检索目标/行动→源码引用追问；每主题一次追问、会话至多6答、工具有总预算/重复指纹/超时和角色权限。外部模型需每次同意，不自动重试未知结果。
先用真实服务+结构化模型替身验证动态选择，不将替身轨迹宣传为真实LLM效果。计划测试tests/test_v3_interview_tools.py及旧test_workbench_interview.py，前端检查/构建和真实合成浏览器。

## 3. 功能轨迹
- `interview_tools.py::InterviewTools.run` 真实复用ToolRegistry→PolicyEngine三层允许工具交集→ToolExecutor合作式超时，绑定owner/project/snapshot不接受模型覆盖。18次总预算、指纹去重、公开trace仅工具名/角色/时长/状态，不含私有输入和rubric。
- `retrieval_interview.py::RetrievalInterviewEngine.prepare/_invoke` 扩展旧InterviewEngine，选择公共题库/项目符号/历史薄弱项；Evaluator只向Interviewer传允许focus、建议行动与位置，模型可选symbol/references/tests等，Python执行真实读取再形成有限追问。规则模式显式词面评价，不冒充模型。
- `interview_repository.py::start/_load/set_paused` 保留原租约/答案幂等/检查点；新请求稳定hash对旧记录兼容；每次读取重新校验来源，删除项目后旧引用不可读。暂停/继续/结束不重复调用模型。
- `InterviewPanel.jsx` 三目标→POST interviews→prepare真实工具→固定首题；answer→旧LangGraph evaluator/interviewer/route→反馈选检索目标→工具→带文件行号追问→结束review→学习资源/薄弱项新场次。
- 备选另造独立面试存储会丢失旧可靠性验证，不选；不让Agent自由聊天或执行源码。代价：局部词面规则不能判断代码解释是否正确，需真实模型/人工质量评审。

## 4. 验证与失败
`python -m pytest tests/test_v3_interview_tools.py tests/test_workbench_interview.py tests/test_v3_public_knowledge.py tests/test_v3_code_rag.py -q --junitxml=../../work/v3-f4-related.xml`，75 passed/0 failed/0 skipped，12.71秒（随后仅规则模型标识/薄弱项query/末轮省检索调整待重跑）。前端构建通过work/v3-f4-ui-build.log。
真实8019浏览器：合成简历解析/人工保存→项目快照→初题save_receipt→不完整回答→真实code_search/get_symbol/find_references共3调用→tests/test_storage.py引用追问→结束复盘/公共资料；另实际进入薄弱项场次并暂停，三条历史持久保存。截图docs/demo/artifacts/f4-project-followup.png、f4-tool-trace.png。
失败/修正：第一次完整回答覆盖所有词面要点，系统正确换题，未产生预期追问；改用明确不完整回答验证反馈分支，未降低评价规则。初次项目薄弱项检索误召通用Schema题，新增源码边界主题路由，后续需重验；不宣称个性化教学质量。
真实模型未调用，结构化provider替身选择不同目标验证的是协议与真实工具调度，不是LLM自主能力成绩。

## 5. 比较与代价
真实模型三组消融LIVE_PENDING；共享老持久状态避免平行再造，新字段需兼容旧序列化记录。

## 6. 安全
源码证明实现存在而非用户贡献；公共知识是概念参考。活动阶段不透出rubric/预期答案，删除来源必须使引用失效。

## 7. 源码地图与学习
待实现后按入口→绑定工具权限→检索→Evaluator→Interviewer→路由/检查点→复盘阅读。

## 8. 面试问答
1. 真工具还是画轨迹？run实际经旧Registry/Policy/Executor读取同一CodeRAGService，trace来自返回观察，替身选择不同目标也实际访问不同工具；不是虚构示例消息。
2. 为什么不套自由群聊？明确职责/有限反馈足够，成本和权限可控；代价是自由规划范围较窄。
3. 如何防越权？租户/项目/快照服务绑定，Schema不接受owner参数，角色工具白名单与总预算；删除源后重新读引用失败。
4. 为什么能恢复？复用已有private state/next_node/pending/lease；Evaluator完成后从Interviewer继续，不重跑前者，未知模型调用不自动重放。
5. 如何证明改善面试质量？当前只能证明机制和本地真读取，真实LLM/人工盲评未授权，不能给质量提升百分比。
6. 规则得分可信吗？词面定位仅提示待补充表达，未识别不等于不会；代码解释全局正确性需要语义/人工评审。

## 9. 下一阶段
F5真实异步主链及恢复/幂等，不以F4局部结束替代全项目交付。
