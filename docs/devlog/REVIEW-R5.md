# R5 · 最终源码验证与新交付

2026-10-23，本轮工程、真实业务窄正例和候选检索实验分别签出；人工8题继续延期/0，语义支持/真人有用性/教学效果未独立核查。旧实验、旧包、远端原项目目录保留，不推送。16项原始历史资料缺失条件明确保留，不能称全仓全绿。

## 实际验证与来源身份

- R1正式修前3红/11绿→修后核心28绿、受影响99通过/1跳过；收尾再从真实Git基线9dc50ef导出新目录，在真实socket上重放before/after。缺失/空逐项评价修后failed/revision0/0轮/0观察，unknown不重派；完整正例/规则/历史兼容保留。
- Windows最终全仓1051通过、16失败、84跳过，276.21秒。16项逐路径为FileNotFoundError，见r5-remaining-legacy-conditions-v1.json。未删测试/改skip/发明历史gold。10个v4/v5公开工件按原构建器原样恢复；FAISS中文路径先红后绿，原生流格式和跨进程持久化通过。
- Linux/Python3.11.15真正新环境[dev,workbench]安装、pip check、-I安装模块/真实HTTP；稳定604通过/34跳过与正阈值BM25门禁。Windows/Python3.12.14独立环境正式main启动/匿名401/来源解析采纳列表及全部5前端资源（含PDF worker）通过。前端Node24.19.0/npm11.17.0，13测试/构建通过。配置中的Actions Node22没有云端执行证明。
- 独立本轮Redis7.2.16/PID140982两项真实测试通过，Windows全仓经回环转发连接同一实例；原S6实例和PG目录未动。本轮未修改PG/Outbox发布实现，不把旧矩阵称新执行。
- 当前335份src Python字节身份8712337b5e852877dae6cd4ec68c8cceba8e5b2508687991e859050b61fdb0ba，与最终生产Provider的非照抄改写HTTP、正式main学习和固定引用学习补测一致。固定题库question-checkpoint的正确/部分/错误/不会/证据不足均完整评价，正确输入完成同来源同题面新ID空历史练习及新观察。v1题面错配保留，v2只改测试输入，不改产品判分。
- DeepSeek冻结10案例×3重复×3路径90行，实际100调用；三路径共享首稿，合法稿全部仍为首稿，不能声称后续文案更好。全轮180实际请求、输入216617/输出23860 token，金额null；仅授权合成/原创CC0题库输入，真实项目代码仅本地检索。
- R4真实40代码主集与唯一10设计补充，共50中文独立候选；主集先dev选E再新test，完整gold14/16→6/16。主dev/test各420、设计新test210真实检索，0运行错误/0无效定位不等于支持正确。主集新目录各140组合重放文档编码0，引用/排序一致。自然默认入口项目范围0/40、显式项目39/40；无答案8题仅1个needs_input，其余limited_source_only。负结果保留，无生成拒答准确率结论。

证据均在docs/devlog/evidence/review-20261023。CURRENT_SPEC、FEATURE_MATRIX、SPEC_CHANGELOG、CONTINUE、开发导航、架构/决策与演示/学习增量同步；旧数值按日期历史解释。

## 新三包与复现旁证

新目录output/review-20261023/delivery-r5-v1：job-agent-review-source.zip、job-agent-review-learning.zip、job-agent-review-real-research.zip。包内manifest逐文件SHA256，delivery.json列ZIP哈希；review_package.py从真实Git已提交快照取源码，不扫入未审计文件。研究包只包含inspect_bundle严格核对的固定研究索引/向量/来源与模型身份、冻结数据和原始结果，source_kind=owner_project_source，不冒称合成CC0；真实源码为内部评测授权。

**实际解包、全文件hash/CRC、从解包源码新建空环境安装、正式main认证/静态资源HTTP、CPU离线门禁和研究包重放结果以同目录verification.json及其原件为准。** 它作为包外旁证避免“包内记录自身最终hash”的循环，不从压缩成功推断运行成功。源码335份身份再与模型证据核对；真实Git历史另附bundle，提交按实际时间、不倒填。* -text只保留已测试文件字节，323项初始行尾差异审计保留，不虚构323项功能改动。

并行学习聊天对AGENTS、导航教学段落及未跟踪教材/技能/进度的修改留在工作树；本轮索引只加入自己的导航段落，包使用已提交AGENTS。旧S8包不覆盖，不夹带环境、密钥、私有用户库、权重、运行时或node_modules。

## 30分钟学习单元

5分钟看Git基线/真实时间提交与源码身份；10分钟review_package.py::source_files/package→研究inspect_bundle→manifest/新目录解压；5分钟review_installed_http_smoke.py正式main/隔离导入/认证/资源；5分钟expansion_ci.py公开SQL重建→BM25门禁/稳定合同；5分钟比较本报告与verification.json的工程、业务、候选、人工四层边界。新路线docs/learning/REVIEW_30_MINUTE_ROUTE.md，不改并行教材或掌握记录。

五个追问：①ZIP CRC足够吗？还需逐文件hash、安装和真实HTTP。②Git行尾为何重要？实际模型/算法身份按字节绑定。③为何留16失败？没有原始资料就不能编造历史gold。④研究包为何不是用户数据库？只允许固定研究scope/源码与特定表，其他业务表非空拒绝。⑤人工延期是否要停止工程？用户允许继续，人工0和语义未核单独保留，不能代签。

## 新交付实际完成旁证

三包固定源码提交3443a4f，未重写或覆盖。Windows解包前端按锁重新安装，13测试/构建通过且5个dist资源字节与包一致；945源码文件在真实Git bundle恢复的clone中逐字节一致。Linux第一次隔离构建依赖下载停滞已保留并取消；官方软件源/有限重试/另一全新venv安装成功，-I正式main匿名401、来源解析采纳列表、全部5静态资源和CLI通过；最终解包稳定609通过/35跳过，BM25正阈值未降。三份包内真实研究重放140+140+70组合全部相同候选/引用，文档编码0。

原件见同目录delivery-r5-v1/verification.json及runtime-evidence，本仓库镜像r5-package-verification-v1.json、r5-package-linux-contracts-v1.xml、r5-requirement-audit-v1.json。包后提交只新增证据/文档，335份src身份保持不变。专用Redis核PID/目录后shutdown nosave，临时SSH转发已停，密钥环境为空；旧服务/目录未改。工程、真实业务窄正例、候选评测已签出；16历史资料条件及人工0延期明确保留。简明交接见REVIEW-R5-VERIFICATION.md。
