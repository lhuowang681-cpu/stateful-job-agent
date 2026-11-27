# S2 真实向量进入产品主链

版本1.3，2026-10-22；verified（工程合同/真实后端/受控开发诊断）。人工语义gold/独立测试泛化质量仍未验，不以本阶段成绩替代S1/S8要求。

## 问题、目标与取舍

api.create_resume_app直接构造两检索service，main亦无embedding选择入口。已有Qwen适配可复用。远端发现4090和本地Qwen3-Embedding-0.6B；先加载pilot，不下载巨型模型、不调用付费API。

显式本地目录配置→真实加载→同后端注入CodeRAG和PublicKnowledge→manifest身份→检索候选trace。默认BM25；显式错误配置启动失败，不能假报dense可用。备选引入向量库暂不选，现有余弦/RRF足够核验主链。真实重排、预热和公平A—D对照随后分别补子合同，不将接口完成当S2完成。

## 数据及接口合同

新增retrieval_runtime.py::RetrievalRuntime，封装backend、EmbeddingIdentity及安全能力视图。from_env只接受本地模型目录，不隐式下载；设备cpu/cuda，默认关闭。revision来自必要配置/权重hash，不只路径；身份声明与真实加载分别记录。

create_resume_app(...,retrieval_runtime=None)默认disabled；同实例注入两检索service及面试；能力接口鉴权后返回配置/加载状态，不输出密钥。main.create_app加载环境；合成demo仅显式传参，不自动读取私有模型/密钥。provider_calls仍指LLM，embedding独立；来源/C1/审批不改。

## 文件任务与验收

|任务|文件/符号|验收|状态|
|---|---|---|---|
|配置与身份|retrieval_runtime.py、qwen_embedding.py|本地离线加载；维度/模板/权重身份稳定|verified（真实Qwen pilot范围）|
|产品接线|api.create_resume_app、main.create_app|两路径同实例；默认降级；能力不虚报|verified（接线合同及HTTP/工具）|
|真实pilot|scripts/expansion_baseline.py（合并基线/pilot，避免重复脚本）|固定合成项目/公共摘要→真实Dense/Hybrid→引用复核，留两路ID/耗时|verified；s2-qwen-interview.json|
|预热/重排/对照|本页子增量2/3|同块同题A—D及E/F/G；显式失败；独立测试保留|verified（受控dev诊断）；人工/独立质量未验|

测试替身只验证接线/错误；真实模型脚本单独留原始结果。pilot控制十余段和少量查询，无API账单，记录加载/首查询/热查询延迟；合成题命中不等于语义质量提升。配置关闭即可回退BM25，不迁移引用或版本。预热与任务发布必须沿用fencing，不能跨库各查一次声称原子。

## 收尾

同步CURRENT_SPEC数据流/默认和可选能力、FEATURE_MATRIX、CHANGELOG、EXPAND-S2及20—40分钟学习导读、3—5入口、失败和5追问。重排/人工质量未运行保持待验。

## 子增量2：预热与产品默认路由（实施前合同）

第一子增量已实际通过47合同测试与真实GPU/HTTP pilot；具体原始结果收尾同步。当前仍首次查询建文档向量，且面试公共工具默认BM25。继续以下合同，不将首pilot当作S2完成：

1. CodeRAGService.build在写事务外解析/编码AST块，排序与_load一致；校验维度/值后把vectors与chunks/index在同一publish_guard事务发布。编码失败不能删除旧索引；旧attempt不能发布向量。report保存vector_index_identity。不会把构建向量推迟到首次查询。
2. 真实runtime后端require_prebuilt=true；历史索引没有当前manifest向量时，dense明确409 needs_rebuild，hybrid/code_aware降级BM25并留错误码。兼容旧测试适配器可保留显式lazy路径，不能用它证明生产预热。
3. PublicKnowledgeService在应用组装时预热doc/question两类，不编码rubric；新语料或tags过滤导致未预热时显式降级/要求重热，不在在线请求偷偷全量编码。新增prewarm()仅为服务端管理操作，不暴露普通用户写接口。当前20条小语料可接受启动耗时，后续必要时独立索引任务。
4. 公共service默认method=None，配置dense时选hybrid，未配置选bm25；HTTP/面试工具共享service默认。显式method=bm25保持对照能力。能力接口同步真实默认/构建位置。
5. 测试验证：查询不重复embed_documents；编码失败保留旧发布；fencing拒旧发布；没预热显式降级；默认工具路由；同一真实pilot重新执行并保留第一份结果。重排另开子增量，尚未实施。

子增量2当时结果：预热后相关264通过；真实GPU/HTTP7检查/7检索/2面试工具入口通过（s2-qwen-interview.json）。扩大全仓发现旧Qwen adapter默认签名兼容回归，改为新runtime显式传离线/预算参数，恢复旧适配默认；未改旧测试，定向77通过（s2-compatibility-fix.xml）。当时重排/A—D/预算待做，后续实测见子增量3收尾。

## 子增量3：重排/统一预算与冻结开发集实验（实施前）

### 场景、备选与依赖

当前两路候选存在但候选数随limit动态变化、无重排。使用小型多语言本地CrossEncoder试验，不预设胜过RRF。候选为cross-encoder/mmarco-mMiniLMv2-L12-H384-v1，官方模型卡含中文、Apache-2.0；官方提交1427fd652930e4ba29e8149678df786c240d8825。只取safetensors和必要tokenizer/config，不执行仓库脚本，不用推理API。模型新下载在本项目output/models内（约500MB），无付费调用，优先本地GPU。官方来源：https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 。备选BGE更大，当前先以较小模型核验接口、收益和延迟，未宣称该候选最优。

### 合同及文件任务

1. knowledge/retrieval_policy.py新增RetrievalSettings：每路候选20、融合30、重排30、最终最多20（请求默认5）、关系最多8、总quote字符预算24000（工具默认更小后续S3统一）。RRF k=60。版本化、合法范围与hash进入trace；各路/融合/重排保持同一输入块，不能扩大输出limit换收益。
2. 新增knowledge/reranker.py：RerankerIdentity记录本地文件hash/模型/软件/512-token pair上限/原始logit语义；协议score(query,texts)返回与输入一一对应有限分数。通用apply_rerank验证数量/数值、排序按分数与chunk_id稳定破平，失败显式保留原序与错误码，不生成假分数。不得把logit当概率。默认关闭；配置后由服务策略决定对hybrid/code_aware启用，可逐请求rerank=false做公平对照。HTTP不能选择任意模型路径。
3. RetrievalRuntime扩展settings/reranker，main从显式本地配置加载，capabilities分别说明dense/rerank；不隐式下载。create_resume_app把同一settings/reranker注入两知识service。Qwen/重排均有batch、输入/候选上限；同步GPU没有硬抢占超时承诺。
4. CodeRAG先两路→融合→可选重排，再保留符号优先和有限关系扩展；统一预算覆盖最后去重/quote输出。纯hybrid用于A—D隔离比较，code_aware另测符号/关系E/F。trace保存两路/融合/重排前后ID、reranker身份/耗时/错误、输入预算截断、最终ID和config hash。Public同合同，rubric仍不编码/输出。
5. scripts/expansion_retrieval_eval.py：默认只跑candidates-v1的20dev；heldout需显式一次性开关且策略冻结记录（本轮不评分）。控制已知语料域，不把gold辅助的评测范围当产品路由能力。用同一原文块/同K/同候选预算比较A BM25、B Dense、C Hybrid、D C+真实重排，另E/F code_aware开关关系。记录dataset/config/source/model身份、每题完整排名/引用核验/分层指标/时延/失败、AI候选标签限制，支持/业务质量null。金标全文件在AST结果里需用quote包含关系定位，严格匹配不足作为失败保留，不换gold迁就实现。
6. tests/test_v3_retrieval_policy.py覆盖预算越界、重排改变顺序、失败/缺分数/非有限值回退、默认关闭、原文与权限/审批边界不变；复跑CodeRAG/Public/面试相关回归及真实HTTP pilot。

### 验收与回滚

真实重排加载/调用和前后排名有证据；开发集A—D/E/F有同口径原始结果，无提升也保留；独立测试仍只静态验证。配置关闭即可回退已验BM25/Hybrid，不删索引/快照。源码、CURRENT_SPEC/CHANGELOG/报告/20—40分钟学习单元同步后才收尾。实施前状态planned，收尾实际状态/证据见后文；真实模型下载失败仅阻塞相应实验，不阻塞预算/错误合同和S3独立开发。

### 收尾补证任务（实施前）

已有替身验证SQLite向量重启复用，补真实模型独立进程：scripts/expansion_dense_restart.py先在合成临时库编码/发布，第二个独立Python进程重新加载同模型和库、禁止重新embed_documents，执行strict dense并核对manifest一致；实际查询仍用真实模型。核对持久向量维度、有限值及L2范数容差1e-4。只操作本项目新建临时目录，不接私人数据库；保留两子进程结果/失败/耗时，不把禁止重建的测试断言说成真实模型替身。

开发集首轮A—F已跑306次/0错误。观察到完整文件gold与AST函数块之间的import范围缺口，新增G=既有flat BM25，与A=AST BM25在同query/K/语料/预算下隔离切块影响；C→E隔离符号优先，E→F隔离关系扩展。保持原gold和第一份结果，另存s2-dev-v2.json，不用改gold迁就AST。这是基于失败定位的补实验，独立test继续封存。

收尾证据：相关306通过17.76s；真实重排HTTP7检查/7检索/2面试入口，双独立进程Qwen向量复用/维度/范数通过；A—G三次重复共339调用0错误。Dense=Hybrid，重排仅少量排序改变，关系无覆盖增益且MRR降，负结果保留。全部原始结果及限制见EXPAND-S2。完整scope/可重放索引快照由S8继续补，不将临时UUID的新建运行称bit级复现。回滚关闭RERANK_PATH/EMBEDDING即可；无来源/审批/私有数据迁移。
