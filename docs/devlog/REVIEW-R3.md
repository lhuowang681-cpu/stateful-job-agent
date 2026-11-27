# R3 · 真实DeepSeek业务与冻结对照

2026-10-23，模型pilot与冻结比较已执行，最终源码与固定引用签出见本文末及R5。用户授权适量DeepSeek合成材料测试；密钥隐藏输入且仅进程内存。实际请求/返回模型字段deepseek-flash，服务商管理版本，thinking disabled，JSON模式，不推断精确权重。账单金额未知，实际usage保留。

首3例/6调用均照抄；提示澄清source始终为首稿改写对象，空candidate_clauses只是历史为空，版本review-r3-rewrite-1；同3例第二批仍照抄。第三批4例/8调用，在有冗余主语的两个正例取得合法非照抄改稿；两项无依据成果/生产部署仍needs_input，事实门禁未放松。学习前两批各2调用，评价/来源观察成功，再练习409 retrieval_interview_not_configured。测试错误地显式传普通InterviewEngine，改用产品默认RetrievalInterviewEngine后第三批12调用跑通五种回答与完整真实HTTP闭环：回答→评价/追问→结束→观察→用户纠正→复核/安排→同题空历史新场→再回答/结束/新观察。是API+SQLite+固定合成题目，不是PG项目RAG或人工语义核查。

独立真实改写HTTP4调用：awaiting_approval，显式合成用户审批生成新C1，原hash保持且truth未核实；同次面试active并反馈改问。见evidence/review-20261023/deepseek-final-rewrite-http-v1.json。所有失败pilot保留，不覆盖旧实验。

## 冻结比较

10新案例×3重复×3路径=90行，数据hash 4089ffc8a3f1ae84688c6a5d00f3e369987f2f77ecd944a4304ebba7c706e7f7。每案例/重复只真实生成一次首稿，三路径共享相同响应hash；单Writer预算1，自修订/双角色均含首稿最多6调用，输出1600上限相同。首稿30真实调用、自修订新增40、独立Reviewer新增30，合计100次/123092总token。路径成本归因30/70/60含首稿，不能把160当实际账单。

|路径|通过|needs_input|no_progress|通过稿仍为共同首稿|
|---|---:|---:|---:|---:|
|单Writer|6/30|24|0|6/6|
|自修订|11/30|9|10|11/11|
|Writer/Reviewer|21/30|9|0|21/21|

通过稿相对原文均有变化，但全部仍为共同首稿文本。通过率差异来自来源映射/审查，而非之后改稿更好；不声称协作产生更优文案。同一模型两角色不等于独立事实核实。人类有用性、语义准确率、账单金额null。原输出/usage/时延/门禁/shared_first_output_hash见deepseek-comparison-v2.json，汇总deepseek-comparison-summary-v2.json。

## 30分钟学习单元

5分钟冻结案例及首稿控制；10分钟review_collaboration_comparison.py::main/SharedFirstProvider→expansion_collaboration_eval.py::execute→RewriteRoles.invoke→LLMHarness；5分钟claim_audit.py::audit_claims的分句与摘录/硬门禁；5分钟review_deepseek_pilot.py::learning的HTTP与用户操作；5分钟比较实际与归因用量。

状态/数据：source+JD→共同真实首稿→单Writer映射或两类审查→同硬门禁→候选；source_hash绑定源码，prompt版本绑定行为，shared_first_output_hash绑定响应，actual_calls只计派发；unknown不自动重试。备选独立生成各首稿会混入随机性，故共享；降低门禁制造正例不可取，故保留约束；不以候选通过率填人类质量。

五个追问：①为何共享首稿？隔离生成随机性。②通过率高是否文案更好？本次通过稿文本相同，仅映射/审查不同。③双角色是否独立真值？不是，只隔离角色。④为何不放宽门禁？会制造事实扩张。⑤成本怎么算？真实网络100次，归因不可重复计费，金额未知。

## 最终源码与固定引用补测

当前335份src Python字节身份8712337b5e852877dae6cd4ec68c8cceba8e5b2508687991e859050b61fdb0ba与最终改写HTTP、main学习闭环及固定题库引用补测一致，见r5-source-model-alignment-v2.json。当前生产DeepSeek Provider只在显式LLM启用时接受flash/v4-pro与thinking配置，旧chat/reasoner兼容保留；31项配置/原runtime测试通过，未改变默认关闭LLM。

正式main+真实HTTP+真实题库question-checkpoint补测v2共12次调用，5类输入均有完整3项评价。正确3/3 correct；部分仅p0覆盖；错误全incorrect；不会/证据不足全uncertain，后者claim_needs_evidence=true。正确输入跑通结束→来源观察→明确纠正/复核/安排→相同题面与来源的新ID空历史练习→回答/结束/新观察。仍是AI语义未独立核查。v1的合成答案误为幂等回执而题目是线程状态/跨会话记忆，模型判错符合题面；保留v1，不把它称正确回答覆盖。v2只纠正测试输入并锁来源，不放松评价。

冻结对照归因延迟p50/p95毫秒：Writer1344.71/1829.77，自修订3182.68/4556.77，双角色2859.425/3510.58；共享首稿实际网络只计一次，归因应包含共同首稿时间，不能直接把缓存路径row.elapsed_ms作最终延迟。单Writer在csv-preview与typescript-form各3/3合法非照抄，为稳定窄正例。负例0/3不能当改写成功。所有本轮不重叠API请求共180次、输入216617、输出23860 token，见usage-ledger-v2；账单金额null，不估造费用。密钥已从远端进程环境清除。
