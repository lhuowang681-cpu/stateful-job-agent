# Job Agent V3 实际验收矩阵

## 2026-10-23 R0—R5 当前复核

当前以docs/tech-specs/CURRENT_SPEC.md和docs/devlog/REVIEW-R5.md为准。修复LLM缺失/空逐点评价错误推进与虚假来源观察，保留历史/规则兼容及unknown不重派；统一安装依赖、wheel资源与中文FAISS路径，补齐PDF worker。最终Windows全仓1051通过/16原始历史资料缺失失败/84条件跳过，最终解包Linux空环境609通过/35跳过与门禁通过，前端13测试/构建通过。

真实DeepSeek当前源码非照抄改写/审批和固定引用完整学习HTTP闭环已验，180实际调用usage台账保留；冻结10新例×3×3路径没有首稿后的文案提升结论。真实项目40+10中文候选、真实检索与新进程重放完成；主留出E完整gold6/16、默认入口项目范围0/40、手选39/40，负结果与无答案政策不足保留。人工8题继续延期/0。新三包及复现旁证在output/review-20261023/delivery-r5-v1，学习增量见docs/learning/REVIEW_30_MINUTE_ROUTE.md。

以下为旧轮次历史记录，不能用旧待办、旧HEAD或旧分数替代本轮结果。


## 2026-10-22 新扩展实际状态（下方F7为历史）

|阶段|当前变化|本轮证据|尚未完成|
|---|---|---|---|
|S0|独立远端新版、hash、合成HTTP、失败分类|基线246/前端13通过；全仓839/45/50，原失败逐项保留|41缺历史资源/2 Redis/1 Git；另1本次Qwen回归已修复且77定向通过；未新跑浏览器|
|S1|完整索引身份、Markdown结构块、26原文/72 AI候选v3|保留旧32；真实最终dev/test各630检索0错；精确原文合同/研究重放已验|人工核对由用户延期仍0，语义近重复/支持关系待人核|
|S2|真实Qwen/CrossEncoder双知识/面试；任务同事务向量发布、公共预热、统一预算|最新相关306通过；GPU重排HTTP7检查/7检索/2面试；双进程索引复用；A—G dev339调用0错|人工gold/独立test泛化质量未验；负结果保留，S8可重放索引待补|
|S3|有界EvidencePack/不足分层、双角色共享摘要、真实工具/复盘预算；事务内引用校验|375相关通过；真实模型/规则均8检查6 pack；保留373通过后HTTP锁失败及修复|语义充分性待人工；未新跑浏览器/全仓|
|S4|共享执行状态/逐断言门禁/反馈/未知派发/并发恢复；离线Qwen7B|435相关通过；108行239次生成/6次小消融/真实HTTP角色反馈改问|未测可用改稿收益，保留默认简单路径；人工语义质量未验|
|S5|可配置同PG项目/快照/不可变索引/任务、原API和独立worker、合成迁移|455通过/4限定跳过；真实PG/HTTP/Qwen双进程、PG重启、迁移dry-run/回滚与dump恢复|生产迁移/容量/运维未验，最终研究索引待S8|
|S6|task+Outbox/单调度authority/独立Publisher/原索引consumer、对账/归档|487/0/4、13场景42进程矩阵、真实Qwen独立链、前端13/构建；最终epoch往返fencing/v3矩阵13/13通过|生产SLA/HA/完整研究重放未验；文本生成不重放|
|S7|来源观察/明确纠正撤回/偏好/有限复习/原图固定来源再练习|517/0/4、规则HTTP5/PG HTTP7、合成浏览器2场6观察、前端13/构建|Qwen首评价缺部分要点被拒绝；人工教学效果/完整模型学习闭环未验|
|S8|固定研究索引/EvalRun/只读统一Trace/正阈值离线门禁|相关612/0/4、离线583/0/33和门禁通过；dev/test各630真实调用0错/各210重放；四演示含12故障场景通过|v2解包启动/离线门禁/7 Trace通过，最终包同目录旁证；全仓1024/44/54历史边界与人工0保留|

默认SQLite/Embedding关闭；PG/Redis须显式配置，S6隔离真实异步索引链与S7来源学习已接。详见docs/tech-specs/CURRENT_SPEC.md与EXPAND-S0至S7，模型失败及人工/生产限制保留，不以旧组件存在宣称完成。

HEAD基线067bfc7，dirty工作树作为当前交付源码；实际结果优先于文件存在。最后更新：2026-10-21，F7本地连续验收完成，外部模型/生产条件逐项保留。
本地规则/合成数据不等于真实模型质量；LIVE_PENDING需单独授权与实测。测试原始文件在工作区work，归纳见docs/devlog/evidence/v3。

| 编号 | 范围 | 当前状态 | 证据/限制 | 验收 |
|---|---|---|---|---|
| F0 | 审计、工程基线、冻结协议 | DONE | FINAL-F0；基线291/0/0、前端13/0/0；全量诊断735/2/50含新PDF8项 | PASS；基础设施失败另记 |
| F1-01 | PDF/DOCX简历抽取/核对 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(文字规则) | 原解析复用；test_resume_import、test_resume_pdf_autofill；F1实际浏览器文字导入 | PASS(本地)，LLM NOT_RUN |
| F1-02 | JD原子/原文span | WIRED_TO_UI / MOCK_TESTED | matching.py直读；Evidence旧内核；规则只给词面线索；新增文件抽取独立 | PASS(合同)，真实质量LIVE_PENDING |
| F1-03 | Writer/Reviewer局部改写/审批 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(规则) | rewrite.py；test_v3_rewrite；原文/新自述分离，三稿六调用、硬门禁与人工审批 | PASS(本地)，LLM LIVE_PENDING |
| F1-04 | 两模板中文PDF | WIRED_TO_UI / E2E_VERIFIED | pdf_export.py/PDFPreview.jsx；真实字体嵌入、长链接6/5页、版本/历史/owner/字节hash | PASS |
| F2-01 | 岗位/投递/版本/面试关联 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(岗位/进展) | long_term.py；test_v3_long_term；真实服务重启前后哈希一致 | PASS(本地)，公开账号服务未集成 |
| F2-02 | 项目元数据/ZIP/文档/删除 | CODE_PRESENT / WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(合成ZIP) | 安全扫描/快照/配额/删除级联；真实Starlette+合成6文件两用户；F7真实文件选择器ZIP上传/索引 | PASS公开/合成范围；私库NOT_RUN |
| F3-01 | 公共知识检索 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(规则/公共资料) | 10摘要10题，版本/许可/去重，结束review真实检索，公开题不含rubric；f3-public-knowledge.png | PASS本地，语义质量LIVE_PENDING |
| F3-02 | Python/JS/TS代码索引 | CODE_PRESENT / WIRED_TO_UI / MOCK_TESTED / LIVE_TESTED(公开数据) | Python AST/Tree-sitter实际解析，静态边；降级/不执行/重建/删除测试 | PASS本地，不是运行时调用图 |
| F3-03 | 符号/混合/跨文件引用 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(代码检索) | f3-code-search.png；40冻结题×5方法；owner/commit/hash/行原文验证；dense未配、hybrid降级 | PASS符号/BM25/关系，真向量NOT_RUN |
| F4-01 | 真实工具/动态Handoff | CODE_PRESENT / WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(规则) | 复用Registry/Policy/Executor，结构化目标选择→真实读取；替身不同目标/18预算；f4-tool-trace.png | PASS机制，真实模型LIVE_PENDING |
| F4-02 | 代码项目面试 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(规则) | save_receipt定义→回答反馈→测试引用→追问→结束复盘；暂停恢复/删除撤销引用 | PASS本地，语义评价LIVE_PENDING |
| F4-03 | 薄弱项补救 | WIRED_TO_UI / MOCK_TESTED / E2E_VERIFIED(规则) | 完成review选缺口→AST公共题→回答→结束复盘；不同题not_comparable；截图f7-weakness-review | PASS机制，教学效果NOT_RUN |
| F5-01 | 持久异步/恢复主链 | CODE_PRESENT / WIRED_TO_UI / MOCK_TESTED / LIVE_TESTED / E2E_VERIFIED(本地索引) | 真实104文件发布后故障恢复；F7浏览器上传后排队→完成→可检索；f7-async-index | PASS本地运行时；PG/Redis产品集成BLOCKED |
| F5-02 | 全链隐私/安全 | MOCK_TESTED / LIVE_TESTED(本地) | owner/ZIP/URL/工具权限/审批/引用/删除/租约测试；无外发与源码执行；未外部渗透审计 | PASS已测范围；公网账户/安全审计NOT_RUN |
| F6-01 | 检索消融 | LIVE_TESTED(本地真实算法) | results/v3-code-frozen-v1.json与public-diagnostic-v1/v2，保留负结果/样本限制 | PASS机械基线；人工语义gold不足 |
| F6-02 | 协作/模型质量实验 | CODE_PRESENT(真实模型适配) / LIVE_PENDING | 替身机制测试不等于真实质量；未授权付费模型，无独立人工盲评 | BLOCKED |
| P1-OCR | 扫描PDF/图片识别 | NOT_INTEGRATED | 已尝试公开CPU RapidOCR/ONNX，1.31和1.22.1均本机原生初始化失败；文字PDF可用，cap.ocr=false | BLOCKED，不能宣传支持 |
| F7-01 | 连续完整产品Demo | E2E_VERIFIED(本地合成/公开数据) | PDF真实上传→v1→JD→改写v2→确认/下载→ZIP/后台索引→三面试/复盘→岗位两版三关联→重启/双用户 | PASS本地，未声称真实模型/生产完成 |
| F7-02 | 最终部署/学习交付 | LOCALLY_VERIFIED / LIVE_PENDING | FINAL_HANDOVER、学习路线/32问答/源码与报告包；解压独立应用/PDF链烟测通过；Docker未运行 | PASS本地交付；容器NOT_RUN |

最后业务全量855/2/50（work/v3-f7-final-full.xml/log，169.92秒）；2 Redis缺服务，34 PG+16模型条件跳过。最后前端13通过/build通过，岗位卡片同步修复真实浏览器验证。历史Linux568/0/16不替代当前产品集成，真实模型无调用。
