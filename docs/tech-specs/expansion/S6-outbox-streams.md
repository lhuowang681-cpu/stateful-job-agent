# S6 · Outbox、Redis Streams与独立索引Worker

版本1.1，2026-10-22。1.0在实施前写入，以下合同保留；现在原业务Outbox/Streams/独立worker已接，工程/真实服务/模型验收已跑。基线S5为455通过/4限定跳过；新增后487/0/4，原矩阵v2的13场景/42真实子进程通过，最终authority往返fencing补强后同源码v3矩阵13/13通过。实际ER、数据字典、失败与30分钟导读见[EXPAND-S6](../../devlog/EXPAND-S6.md)。默认仍SQLite；不将服务就绪或旧Run存在冒充新业务。

## 范围与复用

只将可从不可变源重新构建的代码索引任务接入Streams；Writer/面试生成继续S4未知派发保护，不按索引重建策略自动重放。简历/面试SQLite域不迁移。

复用旧RedisStreamDispatchQueue的连接、group、ACK、lag/pending/retained等原语和OutboxPublisher的事务后发送模式；适配当前任务定位/代次合同、坏消息处理、游标/保留策略与原生PG事务，不继承不兼容旧Run模型。尽量复用IndexTaskWorker的实际构建/心跳路径，不能另造仅演示Redis调用的索引器。

## 权威状态与schema迁移

S5版本DDL/hash不改；以v3_schema_migrations新增明确版本2，扩展Outbox和调度控制/归档表。项目/任务/索引仍原权威PG域；任务创建与Outbox事件在同一事务。消息只传event_id、task_id、请求generation及必要authority标识，不传私有正文或凭据。消费者重新核数据库事件、任务与真实scope；Redis输入不授权owner。

部署显式polling或redis模式，同一schema持久绑定一个调度模式/authority；不允许嵌入轮询worker与Redis worker同时抢此域。缺参数/冲突配置启动拒绝。模式切换要求无QUEUED/RUNNING，轮换authority作epoch；旧进程即使遇到A→B→A仍失效，需重开，不靠进程临时变量掩盖。

Outbox保留event_id/任务FK/请求代次、创建/可用/发布时间、发送次数/安全错误码、重投与人工处理状态。发布成功后记账；若Redis成功而记账前退出，允许同事件再次投递，业务不重复有效发布。重试有上限/退避；永久错误、上限和未知任务进入持久可查终态/归档，不能无限pending。

## 实际时序

```text
原HTTP鉴权与固定快照
→ PG事务：请求幂等/代次 + task + Outbox
→ 独立Publisher：读取待发事件 → XADD → PG记发布
→ Consumer Group读取或XAUTOCLAIM重领
→ PG条件领取：event/请求generation、任务status、token、DB时间lease
→ 原CodeRAG事务外解析/编码 + 心跳
→ 原PG事务：代次/config/token/lease核验 + 不可变索引/指针 + task成功
→ Redis ACK
```

终态或重复唤醒查PG后ACK，不再次构建。有效其他worker租约暂不可领取时保持pending，不能因为重复消息把真实任务丢掉。接手依旧受3次执行上限/代次/config/DB时间fencing；旧attempt不能覆写新结果。坏消息只归档安全码/定位或digest，不把任意正文持久进日志；归档提交后才ACK，ACK故障可幂等重试。

XAUTOCLAIM仅转消费所有权，不替代业务领取/租约（[官方命令](https://redis.io/docs/latest/commands/xautoclaim/)；要求Redis6.2+）。维护扫描游标，不能每次从0导致大量pending尾部饥饿。ACK与删除分别统计；有限Stream保留可能裁掉pending消息，须依靠PG未完成任务/Outbox的明确对账重投，而不是宣称队列零丢失。lag、pending、retained、归档/任务失败分开查看。

## 资源

本机Redis6.0 apt缓存不满足XAUTOCLAIM。选择固定Redis7.2.16源码，使用[官方tarball](https://download.redis.io/releases/redis-7.2.16.tar.gz)与[官方hash清单](https://raw.githubusercontent.com/redis/redis-hashes/master/README)核SHA256：960a8ec15e34ff40e57ff16837b26b33bd81f2da6d24497bb63de532a323a18e。项目output内提取/编译，gcc/make已实测存在，不make install、不改系统/旧Redis。优先只开本轮Unix socket或loopback独立端口，持久目录/精确PID可追溯。此版本选择服务于受控本地实验，不作生产版本推荐。

## 必测矩阵和验收

资源历史：镜像同SHA编译7.2.16、仅UDS/port0及真实XAUTOCLAIM/ACK预检通过；原GitHub TLS超时/官方tar403保留。随后已实现业务链并运行下列矩阵，详见[实际报告](../../devlog/EXPAND-S6.md)。原矩阵v1最后一次启动就绪观察竞态保留，未以反复启动掩盖。

真实PG/Redis/独立进程与替身合同分别留证，至少：

1. 同键同内容并发去重；同键不同内容409且不覆盖。
2. PG已提交、Redis不可用，Outbox可见；恢复后真实发布与执行。
3. XADD成功但Publisher记账前退出，重发仅一次有效索引提交。
4. Worker领取后退出，超时后另进程有界接手；双worker竞争只有一个有效执行。
5. A过期、B完成、A迟到，旧者不能发布/改变B。
6. 业务完成、ACK前退出；重领只ACK，不重复publication。
7. 构建时删除快照/项目，发布拒绝且不复活数据。
8. 失败/租约恢复至上限成为终态，不无限pending。
9. 坏消息、未知任务、永久失败有归档/处理入口和安全错误码。
10. Redis重启及队列信息丢失，对账恢复仍未完成的PG任务，已完成不重做；明确保留策略限制。
11. 同时启用两种调度模式拒绝；消息无原文；实际任务/检索结果通过原HTTP读取。

先新合同与S5相关回归，再真实故障脚本；中途失败保留，不改断言凑通过。最终补实际schema数据字典、Outbox/Stream/lease/ACK时序、故障矩阵、20—40分钟导读/3—5源码入口/5问参考答案，更新当前Spec/INDEX/架构/决策/EXPAND-S6。尚未运行项保持待验。
