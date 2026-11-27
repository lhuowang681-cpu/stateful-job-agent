# Job Agent V3 当前实现与复核结果

更新于2026-10-23。本页只陈述R0—R5当前结果；旧过程和数字见[历史页](CURRENT_SPEC_HISTORY_2026-10-23.md)，本轮证据见[复核总报告](../devlog/REVIEW-R5.md)。人工8题由用户明确延期，human_reviewed=0。

|能力|当前实现与实际核验|限制|
|---|---|---|
|来源、简历版本、局部改写|保留C1原文/hash和审批谱系；真实DeepSeek改写HTTP取得合法非照抄候选，经显式审批写入新版本|候选通过不证明个人贡献、真人有用性或语义真值|
|逐项评价与面试协作|LLM预期ID必须唯一、完整，quote绑定回答，正确/缺失分区一致；规则/历史读取兼容。正式先红后绿与真实socket基线重放验证缺失/空/部分不推进，unknown不重派|完整结构仍为model_semantic_unverified|
|来源学习|旧不完整LLM源不能新增观察，已有观察只读失效/排除；当前生产Provider+正式main+真实HTTP固定题库引用完成评价、观察、用户纠正/安排、同题空历史新场练习闭环|不把确认当掌握；人工教学效果未验|
|检索与引用|默认BM25；显式本地Embedding/Hybrid/RRF、可选重排和有界关系。真实40代码主集+10设计补充题，来源/家族隔离，先dev冻结再新test，固定索引重放|主集冻结E完整gold开发14/16→新test6/16；设计补充分表。人工支持关系未核|
|自然入口与无答案|真实HTTP默认入口40/40公共题库，手选项目39/40项目引用、1项409；无答案项目8题仅1项needs_input|当前UI按显式track分流，没有自动项目意图路由；未测生成拒答准确率|
|持久化与任务|默认SQLite；显式PG项目域、polling或Redis Outbox/Publisher/Worker/ACK原实现保留；本轮独立Redis真实两项通过|本轮未改发布/服务实现，旧PG/故障矩阵为历史证据；不声明生产SLA|
|安装与CI|httpx统一>=0.27,<0.29，wheel包括根评分包与提示资源；Windows3.12.14/Linux3.11.15独立空环境安装、-I隔离导入及真实HTTP；最终新包Linux稳定609通过/35跳过与BM25门禁通过|Actions配置采用实测Linux锁，Windows3.12锁单列；云端Actions未执行，确定性Dense/RRF/重排合同不是质量分数|
|全仓与交付|最终Windows全仓1051通过/16失败/84跳过；FAISS中文路径原生流回调修复，10个公开历史工件按原构建器重建；前端13测试/构建通过，含PDF worker全部5静态资源HTTP通过|16失败全为未取得原始历史资料，测试保留；84条件跳过不能当执行。新三包hash/解压/安装旁证见交付目录verification.json|

真实模型当前335份src Python字节身份为`8712337b5e852877dae6cd4ec68c8cceba8e5b2508687991e859050b61fdb0ba`。冻结10案例×3重复×3路径90行共有100实际调用；通过稿全部仍为共同首稿，不能声称双角色改出了更好的文案。本轮全部有界DeepSeek网络调用180次，输入216617、输出23860 token，账单金额null。仅使用授权合成材料/项目原创CC0题库引用；真实项目源码检索在本地GPU，不外发私人材料。

正式检索入口：main.create_app → RetrievalRuntime.from_env → create_resume_app → CodeRAGService/PublicKnowledgeService → RetrievalInterviewEngine。默认Embedding/重排/LLM关闭；显式无效配置启动失败。索引绑定范围、源码/切块、模型/维度/归一化/模板/版本；缺当前向量须显式重建或Hybrid降级，不能隐藏在线全量文档编码。

API鉴权、owner/project/snapshot范围、来源权限与隐私边界保持。DeepSeek只在显式启用和用户授权下调用，密钥不入文件/包/Git；不扩大到其他付费服务。旧包、旧实验、远端原目录不覆盖；本轮真实Git从9dc50ef开始增量提交，不推送。并行学习教材与AGENTS修改保留，交付AGENTS采用已提交版本。

工程验证、真实业务窄正例、候选检索结果、人工质量分别签出。16项历史资料条件、路由差距、检索负结果和人工0均是当前结果，不能用“全部测试通过”概括。

新三包已完成实际验证：[交付后旁证说明](../devlog/REVIEW-R5-VERIFICATION.md)。源码包固定3443a4f；包后提交只增验证证据/文档，335份src与模型身份不变。
