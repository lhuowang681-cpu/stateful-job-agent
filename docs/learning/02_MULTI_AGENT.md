# 为什么需要有界协作

问题：单次生成容易扩大事实范围，固定顺序面试不会响应刚才的薄弱点。方案：Writer与Reviewer职责和Schema独立，Reviewer可要求修订；Evaluator提出有限缺口，Interviewer据此选追问/转题及下一步资料目标。调用链见architecture/AGENT_HANDFOFF.md。

多Agent的价值不在“角色多”，而在反馈改变行动且可追溯。反例：仅把一个长Prompt分成四次顺序调用，不能据此声称有动态协作。这里不引入群聊消息总线；LangGraph共享私有状态、结构化交接和受控路由已足够。

工具权限由服务授权，不由模型文字承诺：ToolRegistry→PolicyEngine三重允许表→ToolExecutor；项目范围固定，不接受模型传owner。总工具18次，最多6个回答、每主题一次追问。有限反馈减少标准答案暴露和无意义循环，代价是表达自由度较低。

阅读：rewrite.py::RewriteService.start → interview_collaboration.py::InterviewEngine.execute → retrieval_interview.py::_invoke → interview_tools.py::run → test_v3_interview_tools.py。先跑替身测试，再看浏览器真实读取轨迹；不要把替身Provider称为真实LLM消融。

追问：双方同意就代表事实正确吗？不代表，Python硬门禁和来源校验仍独立；引用正确仍不能完全证明语义与现实经历。
