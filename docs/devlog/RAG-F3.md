# RAG-F3 · 来源边界贯穿

2026-10-23，工程合同verified，真实联合待F4。实施前Spec RAG-F3.md已写；排名配置不再调，新增边界不会把定位变成语义支持。

## 实际进展与失败原件

ProjectEvidenceBoundary绑定固定snapshot/refIDs及pack/trace，区分原主题状态与限定题面来源几何充分性。当前题面明确源码/片段边界，词面配置直说词面检索；活跃API只加安全边界，不泄rubric。完整符号、局部片段、跨文件不足、录用率错前提、当前/历史适用性、R1拒绝、观察及同来源新ID空历史均有合同。Trace沿用schema，在status和output_hash绑定状态/策略/理由，公开题目保留对应reason_codes。旧无边界条件不新增hash字段，学习fixed-source取已回答Question的边界，避免后续Topic引用变化污染来源。

首次15通过/1失败及单项诊断失败来自新合成Provider助手漏latency参数（误成unknown），不是本产品漏洞；修正助手并加强必须interview_incomplete_semantic_review后，第二集合91通过/1失败仅因测试把旧practice端点200误期望201。按原API修正，最终92通过/0失败，29.24秒，f3-boundary-related-v3.xml。首件/诊断/错误期望均保留，不计作产品缺陷红测或真实模型结果。原R1真实正式红绿证据不改。窄守卫只在R1完整性校验后降级明确无依据成果/当前状态断言，未补默认correct；语义仍未独立核查。

后续补充真实多文件引用进入评价reference_data、P95未来字段与明确已部署断言、当前事务不误当历史适用性。最终相关集合109通过/0失败，49.93秒（f3-final-related-v8.xml）；边界提示身份改为rag-project-source-1后，33通过/1跳过，4.741秒（f3-prompt-identity-v9.xml），跳过项需要本机未安装的torch。各集合重叠，不相加。v6误指不存在测试文件，无测试执行，原件保留。实际HTTP after-v1三入口检查完成，但未调用生成模型，不能作为真实联合结论。

## 功能地图与权衡

API项目范围→`retrieval_interview.py::RetrievalInterviewEngine.prepare`→`evidence_pack.py`固定引用→`project_evidence.py::make_question_boundary`→公开限定题面。答案经`interview_collaboration.py`原R1完整性校验后才可由`guard_project_evaluation`降级明确无依据断言；观察在`learning.py::condition`绑定已回答Question边界，同题再练保留来源而重新生成场次ID。`unified_trace.py`沿用现有事件合同绑定状态与理由，不引入第二套存储。

选择显式可选边界字段及旧字段缺省兼容，未采用重写旧观察哈希/全库迁移；实际旧正式来源观察哈希仍可读取。source_sufficient只表示窄题完整符号引用，不表示原主题或当前部署为真。跨文件候选保留partial，不声称完整调用链。窄断言规则不能代替语义评委；正确答复也可能因小模型格式不完整被拒绝，F4将实际测量。

## 25分钟学习增量与五问

先用5分钟对照Spec与题面，8分钟走`ProjectEvidenceBoundary`/`make_question_boundary`，5分钟读`guard_project_evaluation`与R1先后顺序，7分钟追`learning.py::condition`到同题再练并看新测试。问：定位为何不是支持？答：行段只证明确有来源，语义未审。问：完整符号为何只足够窄题？答：不能推出运行成果。问：缺项为何不能守卫补齐？答：会伪造模型评价。问：为何绑定已回答Question？答：后续检索可能改Topic。问：旧观察为何不新增None字段？答：保持已有来源哈希与读取兼容。

复现：`.venv-review/Scripts/python.exe -m pytest tests/test_rag_f3_project_boundary.py tests/test_v3_execution_state.py -q`，设置TEMP/TMP为可写output临时目录；JUnit见同目录evidence/rag-round3-20261023。无前端或数据库结构改动；真实模型/真人效果与学习掌握均未在F3宣称通过。
