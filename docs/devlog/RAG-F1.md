# RAG-F1 · 失败归因与新评分

2026-10-23，in_progress。基线main/240d1b0，实施前Spec见docs/tech-specs/expansion/RAG-F1.md；尚未产生本轮运行结果，不以静态代码存在代替通过。旧资料/实验/包、并行学习与人工0保留。实际功能轨迹、失败、命令和20—40分钟导读随进展追加。

## 实际诊断与实现

独立support_evaluation.py新增support-eval-1.1，原evaluation_contract/40+10/旧queries/gold完全不改。分层定位、最小片段单条/同行并集、原gold并集与旧严格单条并列；跨scope snapshot/source_version/hash/quote失效，预算与topk照计。15项新增风险合同+9项旧合同共24通过；初14通过与23通过原件保留。不是用新分数证明检索提升。

8个代表的逐题原文/原gold/新标签/top5/全trace与理由见f1-diagnostic-v2.json，标签先冻结在rag-round3-diagnostic-labels-v1.json，人工0。真实长函数额外诊断仅查询已见dev源码，7变体/5次真实查询编码，文档编码0；不算新test。

|代表|核对事实|归因/后续|
|---|---|---|
|中文PG事务终态|Dense最小支持完整；Hybrid只定位文件、未中函数。两者dense候选完全一致，未发生字符裁剪|融合排序/top5损失，不是Dense召回缺失|
|capabilities精确符号|Dense/E完整覆盖当前题所需45—51行；旧gold还要求无关local_model_revision|标注义务过宽与融合问题并存，旧gold保留，新标签单列|
|旧观察失效跨文件|E完整；关系F只保留第一个直接证据，丢掉_load与完整性检查|关系插队挤占top5，不是context字符预算|
|answer/claim跨域|E完整；F把直接的三个目标换成邻接_load等，最小支持归零|直接证据保留应优先关系扩展|
|行范围/引用字段|E完整，F最小行覆盖.5，关系补充替换了read_code_range|同上，图边存在不保证本题相关|
|设计ACK/权威发布|BM25/Hybrid两来源完整；Dense缺PG发布文档|文档与代码分层，不能强推Dense全局默认|
|录用率前提|各方法都有上下文，但没有实际录用效果证据，未运行生成|产品应明确主题不足/限定，不由检索有引用当事实|
|122行retrieve|旧单条严格全失败；C/E原gold行并集和最小支持均完整；F又丢掉尾部|切块与评分差异不能冒充排序改进；关系仍有真实损失|

功能/数据流：原始语料身份→独立最小标签→已验证引用→topk/预算→同身份区间合并→分层指标。真实读取路径优先原文和固定索引；没有仅看均值或单靠LLM自动改gold。没有发现本样本字符预算溢出，因此不把它写作真实根因；长函数前后上下文是实际切块限制。

30分钟导读：5分钟旧evaluate_case单条条件；10分钟SupportLabel/LocatedSpan/evaluate_support→merged_intervals；5分钟diagnose.freeze/analyze的独立标签与固定snapshot适配；5分钟对照capabilities标注问题与PG排序问题；5分钟关系F原top5。入口共5个，脚本与测试可直接复跑。

五追问：①新分数高是改进吗？同结果新定义，只能说明校准。②为何跨快照不能拼？同名行可能不是同版本事实。③找到文件等于找到支持吗？PG例子反证。④为什么保留过宽gold？防改口径粉饰旧成绩。⑤为何无答案有上下文不算幻觉？尚无生成，需要联合业务验证。

F1评分合同/8例AI诊断verified，语义人工未核。F2只据上述真实损失另立有限Spec。
