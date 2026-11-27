# F3：项目题目、评价与来源观察的证据边界

版本1.0，2026-10-23，实施前。依据F0录用率主题实际被静默改成risk_flags练习，F1仅有引用不证明主题充分；不新增问答产品。F2排名配置已锁，不用正式新test调参。本阶段不改检索候选/融合/向量格式。

方案：EvidencePack新增默认legacy_unclassified的evidence_status，当前生成区分not_located/topic_only/partial/located_unjudged/conflict。conflict只表示明确混入当前/历史资料的适用性未决，不声称逻辑矛盾已被证明；跨owner/snapshot/hash引用仍硬拒绝，不能软化为conflict。

新增ProjectEvidenceBoundary（独立小模型）绑定pack/trace、固定快照、引用IDs、原主题状态/理由、限定题目状态(source_sufficient或partial)和quoted_source_only。Topic/Question/PublicQuestion可选边界默认None，老会话不改历史。source_sufficient只指完整已引用符号足够进行当前限定源码讲解，不指请求的业务事实/用户贡献已获支持；局部块仅能问可见片段。

原主题缺运行/录用效果、个人贡献或当前版本依据但有安全源码时：题面明确说未找到原事实依据，转为仅解释该引用的练习；原主题状态保持topic_only/needs_input，不把转题算原问题正确回答。无可定位符号仍沿用冲突停止，无观察。完整可答题正常推进，不能一概拒绝。扩大运行效果请求识别（录用率/用户规模/部署测量等），但解释边界/否定/假设、明确“文档声称”不当成用户断言真实运行事实。

评价输入带同一边界。R1完整逐项/quote/covered分区检查先执行，之后才施加窄的确定性反例守卫：明确无依据数值成果/已部署/旧计划推出当前实绩等，降级p2为uncertain并请求材料，保留实际回答摘录和原因；不以默认评价填补缺失模型项、不自动补correct。其他语义仍model_semantic_unverified，规则结果单列。守卫不能制造全覆盖或否定用户实际经历，只能说来源无法证实。

边界跟随题目/安全活跃投影/结束复盘/trace与来源观察。condition_hash仅当边界非None才加入，旧条件hash保持；同来源再练保留边界/题面/引用、新ID空历史。引用ID/快照绑定在读取时核对；学习derived fixed-source允许原pack身份作为来源谱系，不伪装一次新检索。比较需相同边界/方法，人工/掌握仍未建立。无存储DDL/新记忆/额外模型调用。

代码：project_evidence.py、evidence_pack.py、interview_contracts.py、retrieval_interview.py、interview_collaboration.py的评价后守卫钩子、interview_repository.py安全投影/引用绑定、learning.py条件与payload、InterviewPanel仅展示清楚的来源范围提示。

验证：实际Repository/HTTP可答完整符号、局部符号、多证据不足、无答案/错前提、当前/历史适用性；恶意完整模型输出被守卫限制、缺项仍先被R1拒绝；否定/假设/报告陈述不误拒；观察与固定源练习保持边界、旧无边界条件可读。先合同再真实本地模型F4，不将替身/规则当联合生成通过。

实施前Trace/投影补充：复用trace现有status和output_hash绑定pack状态/策略/理由，公开题目边界提供对应reason_codes，不新增不兼容Trace格式。现有题面会显示scope_note，无需重复添加界面文案。固定源练习的Topic边界必须取已回答Question的边界，不能误取后续追问更新过的Topic边界。

联合场景实施前补充：跨文件主题将pack中至多两个不同文件的候选引用随主符号传给限定题目/评价，不能让模型只见单段却冒称联合多证据。不同文件同现不确认调用链，题目状态记partial并说明。当前/历史适用性检测也接受所选快照中的代码与显式HISTORY资料共同出现，含义是适用性未决，不声称该快照就是线上最新版本。

实施后补录（包后文档，产品代码不变）：实际验收：来源边界贯穿合同109通过，提示身份初补33通过/1条件跳过；最终项目提示2的相关50通过/1条件跳过和稳定650/34，真实联合见F4报告，不以合同代替模型质量。
