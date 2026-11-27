# 恢复、幂等与未知结果

版本数据库保存业务事实；InterviewState保存下一节点/pending回答/预算；后台Task保存任务状态和租约。LangGraph在这里编排步骤，但应用SQLite检查点不是原生Saver部署。

`InterviewRepository.answer/claim/checkpoint`：相同request_key+相同正文返回原任务，正文变更冲突；独占租约避免并发回答；Evaluator已完成可以从Interviewer继续。模型inflight结果未知时不能自动重放，防止重复收费；规则失败不伪装成功。

`tasks.py::TaskRepository`：事务入队、唯一键、数据库claim、心跳/过期、三次恢复上限；`IndexTaskWorker`先解析，再在索引写事务publish_guard检查租约，旧Worker不能发布。索引提交后进程退出，任务仍RUNNING，新Worker租约到期安全重建；只替换派生索引，不生成重复源码快照，不执行外部副作用。

真实验证：scripts/verify_v3_local_recovery.py，独立HTTP服务+两个子Worker、公开Starlette104文件，注入退出70→再次执行成功，attempts=2，同键相同任务，异主404。第一版独立入口漏ROOT导入路径失败，已修复并保留记录。

本地队列表自身同时是持久事实与可领取集合，所以不需要跨Redis双写Outbox。旧backend_service/中有PG/Redis Outbox/ReliableWorker，但其v1合同与新产品不同，当前没有接到这条主链，也未在本机完成生产服务验证。不要写“分布式Exactly Once”。

学习顺序：tasks.submit→claim→guard→worker.process_once→test_v3_tasks；再看旧reliable_worker/outbox比较两种部署约束。代价：SQLite单机写竞争，不适合多个服务节点共享网络盘；本地轮询存在延迟。
