# S0—S8启动、四演示与面试表达

2026-10-23。默认产品SQLite、Embedding关闭；真实PG/Redis/模型须显式配置。下面只用合成材料。新输出目录保留，不覆盖历史结果。当前全仓诊断有41项缺历史评测资源、2项旧Redis端口未启动、1项无Git仓库的失败；稳定工程检查按公开的业务范围单列，不能称全仓全绿。

## 启动和检查

明确依赖：Python3.12，源码内pyproject的workbench/dev功能；实际已验证的Linux依赖版本见docs/evaluation/expansion/requirements-ci-observed.txt。首次安装可用该清单创建虚拟环境；本次交付解包检查复用已声明的隔离Python运行库，并不冒充一台空机器上的全新依赖安装。前端发布构建随源码包提供，重新构建用frontend/package-lock.json和Node22+，依次npm ci --ignore-scripts、npm test、npm run build。

```text
python -m venv .venv
# 激活虚拟环境后安装固定版本清单，或使用已有明确版本的隔离环境
python -m pip install -r docs/evaluation/expansion/requirements-ci-observed.txt
python scripts/expansion_ci.py --output output/new-offline-ci
python scripts/demo_resume_workbench.py --port 8012
```

合成演示只监听127.0.0.1；访问码由脚本输出，是公开演示码，不能上传私人材料。默认临时数据库，退出后丢弃。持久化演示要明确指定--persistent；当前旧合成服务/业务库不需要为重放而复制。健康路径/health/live，首页能打开前端构建。离线CI会检查固定开发集和稳定工程合同；专用PG/Redis/真实模型/人工有独立记录，CI的相应跳过是依赖范围说明。GitHub workflow仅提供未来仓库配置，本次无Git/未推送/未声称云CI已执行。

## 四条已实现演示

```text
python scripts/expansion_demos.py rewrite --output output/demo-rewrite-new.json
python scripts/expansion_demos.py project-interview --output output/demo-interview-new.json
python scripts/expansion_demos.py insufficiency --output output/demo-insufficiency-new.json
python scripts/expansion_demos.py recovery --output output/demo-recovery-new.json
```

前三条自己起真实loopback HTTP服务、创建合成来源/版本/项目，结束自动关自己的临时服务。rewrite展示正常同义改写→原事实门禁→显式审批→新C1版本；同时拒绝无依据中文成果。project-interview在无Embedding默认配置下用明确save_receipt源词定位、固定本场引用，再展示关键词齐但ACK机制错误→实际追问→已答复盘→一次来源观察。insufficiency即使项目有xack源码，也不写成用户主导Redis/成果。

recovery必须先准备**本项目专用测试PG与Redis**并显式设置JOB_AGENT_TEST_PROJECT_DSN和JOB_AGENT_TEST_INDEX_REDIS_URL；不应指向生产。运行原12场景故障矩阵，不额外重启Redis。它保留每场schema、子进程/退出码、PG事件/唯一有效发布、Redis Pending/ACK和统一Trace。删除源的场景连任务一起删除，trace正确404；其他场景导出原PG事件。S6另有真实专用Redis重启AOF矩阵13场景证据。所有模型unknown仍禁止自动重放。

没有这些专用依赖时不运行第四条，阅读S6/S8已有原始证据；不要为演示临时打开或清空其他Redis。当前实际服务边界见S5/S6报告，不承诺生产SLA/HA或任意外部副作用exactly-once。

## 五案例到证据

|验收案例|可复现入口|结论边界|
|---|---|---|
|代码有Redis，个人经历未声明|insufficiency演示；test_v3_evidence_pack.py的personal/runtime边界|允许读源码与提学习建议，不升级个人事实或C1|
|自然语言要租约校验+发布两组证据|固定72题的multi_evidence类别、A—G逐query及E/F分组充分率|关系扩展改善候选覆盖但降低部分MRR，语义充分仍待人工|
|新增“显著提升求职成功率”与正常改写|rewrite演示；test_v3_execution_state.py反馈回下一writer|硬合同/断言审查有限，不宣称所有中文幻觉已解决|
|A过期/B发布/A迟到；提交后ACK前退出|recovery的old_worker_late_after_takeover和commit_before_ack_exit|真实进程/PG/Redis，唯一有效发布；不是任意副作用恰好一次|
|事务/幂等/Redis都说了却说ACK保证一次|project-interview演示；test_v3_ack_feedback.py|有限ACK确定性反例、有否定对照/纠正/再练习；不是通用语义Judge|

## 3分钟项目介绍（按实际参与范围使用）

这个项目围绕求职材料、岗位和面试练习保留了原工作台，新增重点是让回答能回到来源，让任务失败后能解释和恢复。公共技术说明、项目源码和个人自述分开；检索命中不会自动变成用户做过某项工作的证明。

检索复用了原AST、BM25和向量/RRF路径，补了真实可配置Embedding、可选重排、Markdown切块及完整身份。固定26份合成/公共摘要原文、72候选题做同口径对照，并把原文、项目/快照、向量和配置装入研究包。真实开发和测试各630次检索无错误；复杂策略没有全面胜出，重排在测试集反而漏题。人工支持核对由用户延期，这些数字仅是候选标注下的机械结果。

业务运行沿用原角色图和工具，增加共享执行状态、逐断言门禁和预算。项目索引切片把项目、快照、任务、Outbox与发布放进同一PG事务域，Redis只负责唤醒；Worker必须持有效租约和attempt才能发布，完成后再ACK。文本模型结果未知时不会照搬索引的重放策略。

学习记录来自已答完成的具体题目，有回答/评价/引用版本与时间，可纠正、撤回、暂停或删除。再练习复用同题和来源；条件不同不硬算提升。统一Trace把既有事件导出为ID/hash，保留unknown用量并避免根子重复计算。这里能证明的是列明范围内的工程行为，不能据此声称生产SLA、模型普遍理解正确或用户已掌握。个人贡献应再按自己实际读过、改过、复现过的内容说明。

## 10分钟深挖路线

前2分钟沿API→所选Repository→原图/工具→事务发布走一遍；第3—4分钟展示同源不同query模板为何索引失效、引用有效为何不等于支持；第5—6分钟看一次坏草稿反馈和unknown调用保护；第7—8分钟按PG提交→Outbox→Redis→租约→发布→ACK逐个指出崩溃点；最后2分钟看重排负结果、固定重放和人工待验。

常见追问：为什么不全部迁PG？本轮只迁能同域提交的项目索引切片，简历/面试仍SQLite并声明跨域边界。为什么不接监控平台？现有事件的只读结构化导出足以复核本范围，未出现平台运维收益证据。为什么保存公共向量？否则新进程会隐式重编码，不能证明恢复固定工件。为什么hash不等于可信？它只绑定字节，支持关系和个人经历仍需独立审核。为什么没有Git提交？当前来源目录没有.git，本轮保留基线、真实diff/hash，不伪造历史；没有推送。
