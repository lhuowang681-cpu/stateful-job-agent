# Agent交接、反馈和权限

## 简历闭环
`rewrite.py::RewriteService.start` → LangGraph Writer → Reviewer → 有界修订/拒绝 → 用户审批。`RewriteRoles.invoke`是独立Schema角色调用；`hard_constraints`检查数字/技术/否定/责任范围，不能证明所有中文语义。最多三稿六次角色调用，人工接受后产生新C1补充来源；不把新措辞继续冒充原简历逐字引用。模型未授权时明确使用conservative_rewrite本地演示，不伪造LLM轨迹。

## 面试闭环
`InterviewRepository.start` → `RetrievalInterviewEngine.prepare` → 真实question_search/code_search → 固定计划与来源 → 用户回答 → 旧`InterviewEngine.execute` LangGraph：evaluator → interviewer → route。
Evaluator看到rubric/回答/允许经历/选定来源，用完整不相交covered/missing ID分区输出。Interviewer仅收到允许focus、建议行动、剩余轮数与引用位置，不拿参考答案；它可选择不同retrieval_target，Python执行实际get_symbol/find_references/knowledge_search，然后生成带来源的追问。每主题最多一次，最多6个回答；最后一轮不再做无用的后续检索。

模式：job检索公共题；project检索用户指定快照；weakness从已完成review选待补充主题，源码场次补救先回到AST/引用边界。规则判断是词面线索，不是回答正确性的权威评价。Coach在结束后用已答评价和带来源摘要做确定性复盘/学习引导，未新增无必要的LLM调用。

## 工具与消息
`interview_tools.py::InterviewTools`实际复用原运行时的ToolRegistry、PolicyEngine和ToolExecutor；不是另一套自由工具执行器。参数Schema不接受owner/project/snapshot，范围在服务绑定。interviewer可读题/资料/代码，evaluator仅资料/精读，coach仅公共资料；禁止未知工具。18次工具总预算，重复指纹不重读，12秒合作式期限；不能抢占任意堵塞Python处理器。

结构化消息包含from/to/type/turn/action或retrieval_target和固定交接说明；公开trace包含工具名、角色、耗时、状态，不含原始参数、rubric、模型私有推理。完整执行状态私有保存，有owner与hash校验。活动review409，结束仅已答复盘；暂停保留题目，不透露下一题；恢复未知模型调用禁止自动重放。

## 验证边界
tests/test_v3_interview_tools.py的RoutingProvider是结构化替身，确实派发到真实代码工具，可验证不同目标得到不同来源；不能据此说真实模型自主协作效果改善。真实浏览器规则路径截图f4-project-followup/f4-tool-trace，付费模型质量与三组消融LIVE_PENDING。
