# R0—R5 交付后验证与阅读入口

2026-10-23。工程验证、真实业务窄正例、候选检索实验分别签出；人工8题按用户决定继续延期，人工0。完整测试仍有16项缺原始历史资料，未删除测试、改skip或发明gold，不称全仓全绿。

|层次|实际结果|证据|
|---|---|---|
|评价漏洞|先3红/11绿再修复；真实socket基线重放证明缺失/空评价不推进、不造观察，完整正例与unknown不重派保留|REVIEW-R1及r1-real-http-before/after-v1.json|
|真实模型业务|当前335份src身份一致，真实DeepSeek合法非照抄改写/显式审批；正式main固定题库来源完成5类输入及纠正/复习/同题新场完整HTTP闭环|r5-source-model-alignment-v2.json|
|公平对照|10新例×3×3路径，100实际调用；通过稿仍为共同首稿，没有后续文案改善结论|REVIEW-R3；延迟/usage原件|
|真实RAG|40代码主题+一次10设计补充，真实Qwen/CrossEncoder、来源家族隔离与冻结新test；主集E完整gold14/16→6/16；默认项目范围0/40、手选39/40|REVIEW-R4；原查询与路由失败保留|
|Windows全仓|1051通过/16失败/84跳过；16项全为原始历史资料缺失|r5-full-v1.xml及remaining-legacy-conditions|
|新包Linux空安装|全新Python3.11.15环境、不继承系统包；wheel安装/pip check/-I正式main认证与业务HTTP/5静态资源/CLI通过|r5-package-verification-v1.json|
|新包CPU门禁|609通过/35条件跳过，BM25正阈值通过；不加载真实模型，不称生成质量|r5-package-linux-contracts-v1.xml及gate|
|新包前端|Node24.19.0/npm11.17.0，按锁新装，13测试/生产构建通过；5个dist字节与包一致|r5-package-frontend-v1.json|
|新包研究重放|主dev/test各140、设计70组合，引用/候选顺序一致，文档编码0；使用既有独立ML环境，区别于CPU空安装|verification.json及runtime-evidence/replay-*.json|
|Git与交付|三新包逐文件hash/CRC/解包通过；完整Git bundle恢复后945源码文件与包逐字节一致；不推送|delivery.json、git-history-verification.json|

新包目录为`output/review-20261023/delivery-r5-v1`：

- [源码包](../../output/review-20261023/delivery-r5-v1/job-agent-review-source.zip)
- [学习包](../../output/review-20261023/delivery-r5-v1/job-agent-review-learning.zip)
- [真实研究包](../../output/review-20261023/delivery-r5-v1/job-agent-review-real-research.zip)
- [实际运行旁证](../../output/review-20261023/delivery-r5-v1/verification.json)与[逐项验收](evidence/review-20261023/r5-requirement-audit-v1.json)

包固定源码提交`3443a4ff19d248c082c5244f23abf1408a39be75`。包后的本地提交只增验证证据和文档，不把旧包冒称后来HEAD。335份src身份始终为`8712337b5e852877dae6cd4ec68c8cceba8e5b2508687991e859050b61fdb0ba`，与最终真实模型运行及最终解包源码一致。原包不重写，最终运行结果用包外旁证解决自引用哈希循环。

第一次空安装停在配置的Aliyun源下载隔离构建依赖，主动停止的原日志和条件记录保留；换官方源并限制网络超时/重试，在另一个全新venv成功。没有将复用旧环境称从零安装。复现命令见[演示说明](../demo/REVIEW_RUNBOOK.md)。

本轮DeepSeek共180实际请求、输入216617/输出23860 token，账单金额未知；无重复首稿计费归因。只外发授权合成材料/项目原创CC0题库，真实项目代码本地检索。密钥未入文件/包/Git，验后环境为空。专用Redis先核PID140982和目录后shutdown nosave，临时转发已关闭；旧服务、旧包和远端原目录保留。

并行学习聊天的AGENTS、导航教学段落和未跟踪教材/技能/进度保留，不纳入工程提交。建议先读[本轮30分钟增量](../learning/REVIEW_30_MINUTE_ROUTE.md)，再按需要查看R1—R5各20—40分钟单元；不要求重读全仓，也不把AI开发记录当用户个人经历。
