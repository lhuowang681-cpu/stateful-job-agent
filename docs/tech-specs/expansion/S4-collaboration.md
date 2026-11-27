# S4 共享执行状态、事实审查与同预算对照

版本1.1，2026-10-22；工程/模型接线/候选对照按范围verified，语义能力未验。最初1.0在代码前写；实际失败、108行239调用无可用改稿增益、小消融与435回归见[EXPAND-S4](../../devlog/EXPAND-S4.md)。依赖CURRENT_SPEC0.4/S3，沿用两条业务图及原来源/审批/面试持久化，不另造群聊框架。

## 基线与验收范围

S3相关375通过、模型/规则真实HTTP各8检查；语义质量未验。RewriteService的LangGraph只传revision/outcome，实际资料在外围闭包；InterviewEngine只传node。旧writer确实收到drafts里的review.constraint，但缺统一可审计状态/事件合同。hard_constraints能检查数字/英文实体/范围，中文新增“显著提升求职成功率”缺口仍在。InterviewEngine和API会在异常时清除model_inflight，运输超时的未知结果应保守保留。

验收：两图实际传递并消费同一SharedRunState；原事实身份/最新反馈/证据ID/预算/事件序号/审批血缘有持久依据。合法同义改写不一律退回原文；新增成果即使Reviewer接受也被程序门禁拦截。修订反馈进入下一稿；非法动作、重复无进展、失效父版、并发/失效执行与未知调用均不自动重复写入或派发。活动面试不泄rubric，只有同题/同评价条件允许作参考比较。

## 合同与任务

1. 新execution_state.py：SharedRunState含schema/run/owner/task、可信源版本/hash与JD hash、model身份、当前node/revision/status/next_action、最新RoleFeedback、artifact/evidence ID、预算与已知/未知用量、attempt/lease、单调event_seq与有界事件。身份只由仓储/协调器设置，角色摘要排除owner/租约和原始长文，输出hash不冒充语义证明。状态随既有payload事务/checkpoint保存，不开第二权威库。
2. 两图State携带execution并在节点读取最新反馈；保留现有业务状态和原公开DTO。改写仍最多3稿/6次角色调用/120秒；面试每主题最多一追问/最多6答/18工具。每个派发前记录started，结果/门禁/路由后记录完成和产物hash。模型异常未知不默默恢复成可安全重试。
3. 新claim_audit.py：按完整分句生成断言及原文位置，分类职责/技术/数量/时间/成果/因果/范围。明确区分确定性相等/受限同义变换、模型语义判断与缺证；每条新增/变化断言映射源事实或来源不足。Reviewer可返回逐断言来源摘录和状态，程序核对摘录确实来自选定C1原文/上下文，不能用JD或源码证明本人经历。无依据中文成果、量化/否定/主体/范围变化硬拦截；模型同意不能豁免。普通语义不能靠字符串相似度宣称100%支持。
4. Writer保留原事实和上下文，历史只保留最新一稿/反馈，完整有界历史留仓储；Reviewer给具体问题，下一Writer使用同一反馈身份。相同错误稿重复立即停止，accept时重查身份/父版/草稿hash/最新审查及程序门禁，接受仍创建C1。改写执行存CAS hash及有限lease，失效执行不能覆盖新的未知/终止决定。
5. Evaluation增逐要点correct/incorrect/uncertain与回答原句依据；模型审查和local_lexical显式区分，不能只见关键词就宣称解释正确。错误/不确定要点不能留在covered。Interviewer收到安全结构化反馈，不得到完整参考答案。上下文保留当前题/回答/必要rubric/原事实和否定；只裁剪历史/完整事实条目，丢失材料明确context_incomplete，不自动补全。
6. 输入长度/真实本地token限、调用数、deadline和未知用量有合同；拒绝超限不隐藏截断关键材料。旧provider接口兼容，原LocalTransformersProvider不偷改其历史适配默认行为；新增离线文本provider可接既有Qwen2.5-7B目录，所有加载local_files_only/trust_remote_code=False，报告权重/配置hash与运行依赖。无付费API/无私人外发。

## 实验先估算再执行

本地已有/root/autodl-tmp/models/Qwen2.5-7B-Instruct，两张4090可用性需运行时核对。先2例pilot，三路径：单Writer一次；同总上限的自我审查/修订；Writer/Reviewer。后两路径均最多6调用，单Writer是1调用成本基线；同模型/材料/初稿prompt/生成参数/输出上限，原始输出与实际调用/token/时间都保存。每调用输入≤8192 token/输出≤512，pilot最坏36调用（实际有效路径上界26）、总输出≤18432 token；API费用0，GPU计算成本未知，先测速度/格式可用性，不自动分配新资源。

pilot通过后，以有界已授权本地资源跑12例×3路径×3重复的正式候选对照；上界648调用/331776输出token，实际早停及花费单独统计，最长60分钟，达限保留已完成行和不足。样本含新增中文成果、正常同义、数字/否定/范围、JD诱导、证据边界、重复失败。确定性标签只用于已明确硬约束，改写语义/可读性用模型参考和待人工盲审列，不能拿互评当唯一真值。小消融仅离线生成合成材料，比较证据约束提示开关，产品硬门禁永不关闭。若无协作收益或误拒增加如实记录。

## 验证、交付与恢复

### 首个实现与pilot的实际调整

定向100通过、扩大431通过；最初测试命令误写不存在文件，未运行测试，原命令错误保留。首次真实模型pilot（2例/三路径）6行8调用、总49.85秒，其中normal-api三路径共同首稿出现claims额外revision而StrictModel拒绝；不是运输未知，未放宽schema/删字段，下一版提示明确允许的键并递增prompt版本。另3行保留原文/needs_input，尚无协作质量提升结论。三路径同一案例首稿prompt hash/seed相同。原始s4-collaboration-pilot-v1.json保留；12例候选在pilot前已冻结，不能因结果改标签。Reviewer实际投影视图只看当前稿和原事实，不看Writer自我认可/理由；自审路径保留作者视图，两者均同模型/原材料/调用上限，实际token分别报告。

新增test_v3_claim_audit/test_v3_execution_state，复跑原rewrite/interview/source/retrieval与运行时相关合同。真实本地模型pilot与真实HTTP的模式/调用数/反馈前后稿分别留证；不能把schema替身叫真实模型。未知派发、并发、失效lease、重复无进展、非法评价/焦点、正常同义误拒与C1血缘列入用例。

收尾更新CURRENT_SPEC/CHANGELOG/INDEX/FEATURE_MATRIX/架构/决策及EXPAND-S4。报告含真实失败、对照限制、调用图、3—5源码入口、5问及参考要点、30分钟学习单元。人工未评/新浏览器未跑保持待验。回滚用本轮diff；新字段默认兼容旧checkpoint，不迁移个人事实。
