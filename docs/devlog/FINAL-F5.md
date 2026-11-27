# FINAL-F5 — 持久后台索引任务

状态LOCALLY_VERIFIED / 生产适配BLOCKED，2026-10-21，main/067bfc7 dirty。F4新增协作相关75/0/0、三模式UI构建与真实源码追问截图已保存，真实模型仍未授权。

## 问题/基线
项目索引目前同步阻塞HTTP；浏览器关闭不应丢任务，也不能靠消息当事实真相。旧ReliableWorker依赖PostgresRunRepository/RedisStreamDispatchQueue和v1 AgentExecutionAdapter，其请求是semantic_job_flow/application_assistant_flow，不能假装直接接入v2项目索引。

## 方案/备选
本环境Docker/PG/Redis未就绪。保留旧部署链，新增最小SQLite产品任务适配：复用旧RunStatus状态词汇和事务claim/租约/fencing原则，数据库同时保存任务与可领取状态，避免引入新中间件或不持久的BackgroundTasks。不是PG/Redis Outbox集成，不宣传分布式生产保证；生产接入仍BLOCKED。首条实际耗时链为代码索引，无外部副作用，崩溃后可安全重建派生索引。模型任务未知结果不纳入自动重放。

## 验收/测试计划
submit202→独立工作线程→进度查询→可用索引；同键一致/不同输入冲突；owner、并发claim、租约过期、旧worker不能提交、发布后崩溃再执行、项目删除、队列取消/失败上限。保存pytest日志与真实服务重启/worker故障记录；未跑项明确NOT_RUN。

## 功能轨迹/结果/学习
`tasks.py::TaskRepository.submit/claim/guard/heartbeat/complete`与`IndexTaskWorker.process_once`保存SQLite持久任务，复用旧RunStatus命名；不扩充v1请求、不引入新中间件。原子入队、同键去重、排队限额、租约心跳、三次恢复上限；code_rag.build的publish_guard与索引发布同事务校验，失去租约不可发布。只允许取消尚未领取任务，运行任务不假装强行撤销。

`ProjectsPanel.jsx`→POST index-tasks202→后台线程领取→静态解析/原子发布→GET tasks轮询→显示可用索引。离开页面可从项目任务历史重开，失网显示手动刷新；未把长请求绑在页面等待里。

真实`python scripts/verify_v3_local_recovery.py`：隔离HTTP服务+公开Starlette ZIP104文件+独立Worker，索引提交后注入退出70，任务仍RUNNING；等待2秒租约，第二子Worker执行成功、attempts2，同键不另建、异主404，7.899秒。不是Mock，也未用PG/Redis。证据evidence/v3/f5-live-worker-recovery.json。首次失败是独立CLI漏仓库ROOT import路径，修复后重跑，失败日志保留。

pytest相关76/0/0，最新针对性61/0/0；全量855/2/50，真实缺依赖未绕过。前端13通过/build通过。F7浏览器真实ZIP上传后202排队→完成→6文件索引可检索；刷新/任务历史保留，截图f7-async-index.png，独立只读断言f7-demo-state.json。

学习45分钟：submit唯一键→claim事务→guard写事务fencing→Worker心跳→崩溃后重建→test_v3_tasks.py；再比较旧reliable_worker/outbox的PG与消息投递约束。

面试追问：
1. 为什么本地没有Outbox？队列表和可领取状态在同一数据库，无跨消息系统双写；不能泛化到分布式部署。
2. 索引提交后任务没完成怎么办？允许重建派生索引，不新增源快照；同键仍同任务。
3. 旧Worker如何被阻止？token/未到期租约/status在索引写事务检查，过期attempt不能发布或覆盖状态。
4. 能自动重试模型吗？此Worker只处理幂等索引，不把结果未知的模型/外部副作用放入自动重放。
5. PG/Redis是否完成？旧独立实现保留，当前新产品未接且环境缺失，明确BLOCKED，不沿用旧Linux验收冒充本轮。

剩余：生产多节点、PG/Redis产品适配、容器实测、模型异步调度未验收。F6实验与F7全链交付继续，不新增其他消息中间件。
