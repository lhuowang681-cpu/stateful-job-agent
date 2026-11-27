# R1 · 在线逐点评价完整性

2026-10-23，工程合同已验证；以下为实施前计划与实际证据。实现前合同见REVIEW-R0-R5。问题：LLM省略或返回空point_assessments时绕过完整性检查，可把不会的回答记全覆盖并推进；非空部分评价反而失败。

先新增正式HTTP/真实Repository回归：缺失/空/部分/重复/未知ID/quote伪造、完整正确与保守降级正例、规则/历史兼容、未知调用不重放。先保留修前失败与状态/revision/调用/观察数量，再修门禁。不能把HTTP200看作业务成功，不用补默认正确修复。

入口：interview_contracts.py::Evaluation/PointAssessment → interview_collaboration.py::InterviewEngine.execute.evaluator → interview_repository.py::answer/claim/checkpoint → route提交 → learning.py::LearningRepository.materialize。只改在线完整性义务，不破坏历史反序列化；若其他测试的合成Provider省略逐点评价，须改成与其测试目的相符的完整合法输入，不继续依赖漏洞。

计划命令：项目自有空环境Python运行tests/test_review_r1_evaluation_integrity.py，先红再绿；随后test_v3_execution_state.py/test_workbench_interview.py/test_v3_learning*.py/test_v3_unified_trace.py及全部受影响规则/模型替身。真实文本模型后续R3单列验证，不将本阶段替身当真实模型质量。

## 2026-10-23 实际红绿与边界

修前正式在线回归3失败/11通过：省略、空数组、“逐点正确但声明missing”均错误推进revision1；修后核心28通过。历史学习来源模拟先因错误观察ID触发3个唯一约束错误，保留r1-legacy-fixture-error.xml，不能计为漏洞证据；修正ID后的r1-legacy-before-v2.xml为2失败/2通过，空/部分来源错误地返回200并新增观察。来源门禁修后最终受影响集合99通过/1跳过，29.83秒，见evidence/review-20261023/r1-affected-v2.xml。

首轮受影响集合96通过/3失败/1跳过也保留：旧FixtureProvider省略逐项评价，已明确改为完整uncertain，保留追问、双角色隔离、12调用预算断言。未删除原断言。远端实际Python3.11.15复用环境只用于R1，不能称空环境安装；99项不是全仓或模型质量成绩。

功能轨迹：Evaluation.has_complete_assessments只检查形状。在线evaluator强制LLM完整性，错误记录stopped/code并停在pending.evaluation提交前；revision/turns/观察不变，原键幂等，unknown不重派。错误/不确定仍强制降级missing，完整正确可提交。方法版本review-r1-answer-1，仍model_semantic_unverified。

LearningRepository在任何新增写入前检查所有未撤回评价来源。旧不完整LLM来源物化409；已有观察只读变invalid/excluded并隐藏payload，不删除历史。旧完整LLM和规则模式继续兼容。不把结构完整等同语义真；真实DeepSeek合成材料另记R3。

## 30分钟学习单元

1. 5分钟，tests/test_review_r1_evaluation_integrity.py::test_invalid_online_assessment_cannot_commit_or_create_learning_and_is_not_replayed：HTTP200与业务失败的差别。
2. 5分钟，interview_contracts.py::Evaluation.has_complete_assessments：兼容读取默认和在线强制义务。
3. 10分钟，interview_collaboration.py::InterviewEngine.execute/evaluator：reject_evaluation→pending→interviewer→route，检查提交边界。
4. 5分钟，learning.py::usable_evaluation_source/ LearningRepository.materialize/_payload_for：评价→fingerprint→观察→队列过滤。
5. 5分钟，三组红绿JUnit：区分代码漏洞、夹具错误和真实模型质量。

数据/状态：active/revision0→评价失败→failed/revision0；合法评价→pending→interviewer→turn/revision1→complete→来源观察。point_assessments逐点判断；covered/missing完整分区；answer_quote绑定回答；method_version绑定行为；source_fingerprint绑定来源与条件；independent_mastery始终not_established。

备选：全局必填数组破坏历史和规则读取，故在线检查；静默删除旧观察丢失审计，故只读排除；自动补correct制造证据，故拒绝；未知自动重试有重派风险，故保留不重放。

五个追问及答要：①为何保留默认[]？历史/规则可读，线上按模式强制。②为何不补correct？无语义证据。③为何200不能计成功？失败状态已正常保存，仍需核status/revision/副作用。④为何不删除旧观察？保留审计，通过来源检查排除。⑤99项证明什么？完整性、状态与兼容合同，不证明模型语义准确或用户掌握。

## 最终真实回环HTTP基线重放

新增r1-real-http-before-v1.json与after-v1.json，在真实socket/Uvicorn/SQLite上分别运行真实Git基线9dc50ef导出的新目录和当前源码。缺失/空评价修前错误推进revision1、2次角色调用并生成3条观察；修后failed/revision0/原题、0轮、仅1调用，结束/物化409且0观察。部分、完整正例及unknown不重派同时验证。此socket“修前”是在收尾时重放真实基线；最初正式3红/11绿确实在修代码前运行，二者时间不混写。
