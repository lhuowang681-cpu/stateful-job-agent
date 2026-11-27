# S5 项目→快照→索引→任务 PostgreSQL垂直切片

版本1.1，2026-10-22；工程/隔离PG/合成迁移/真实Embedding verified。1.0在实施前写入，以下合同保留。基线S4最后435相关通过；现在默认SQLite，显式PG项目/快照/索引/任务同一权威域；旧PostgresRunRepository未被冒充复用。简历/面试/岗位域保持既有仓储，不全面迁移。实际ER、时序、失败与30分钟导读见[EXPAND-S5](../../devlog/EXPAND-S5.md)。

最后相关455通过/4限定跳过32.34秒；真实PG14.24、原HTTP、Qwen1024维两个进程检索/项目面试、PG实例重启、独立worker、无SQLite影子写、离线CLI迁移/hash/备份回滚及单业务dump恢复均已验。4跳过为PG专属用例在SQLite参数分支；真实PG参数已跑。CLI迁移样例向量0，另有fixture向量迁移合同与真实PG向量重启，不能混称真实向量迁移。生产/容量/Redis与完整研究索引未验。

## 事务域与接口

抽ProjectRepository（项目/不可变快照/文件/引用读取）、CodeIndexRepository（发布/报告/完整载荷/向量）、IndexTaskRepository（请求幂等/领取/lease/完成/历史）协议。CodeRAG只做解析、编码、校验和排序，不直接持有SQLite SQL。默认SQLite实现保持原表/引用与旧测试；配置PG时原API绑定同一PG项目/索引/任务集合，不能通过影子SQLite写入凑成功。复用旧PG实现的psycopg dict_row、显式事务和条件fencing思路，不继承不兼容的旧Run模型。

原API路径/DTO尽量兼容；API factory显式注入集合，独立worker同配置启动。面试仓储的代码引用校验必须用被选中的CodeRAG，不再另建SQLite代码service。仅同事务域可复用引用db连接；简历SQLite与项目PG之间无分布式事务，跨域引用在每次读取重新验证，来源删除后不能继续有效。

## PG实体/键/生命周期

- project：全局project_id，可信owner_id索引、原元数据、current_snapshot、index_status；owner下配额在事务锁中检查。
- snapshot：全局snapshot_id，project_id级联外键、内容/来源/commit/metadata，UNIQUE(project_id,content_hash)，desired_generation与active_publication；文件(path,hash,text)按(snapshot,path)主键。当前指针必须属于该项目。
- publication：不可变publication_id，snapshot外键、parser/index版本、完整report及payload hash；symbol/chunk/edge/vector均绑定publication_id，避免读取指针后混到另一版。active指针在事务最后一起发布；旧发布随快照生命周期保存，不在线原地改载荷。
- task：全局task_id、owner/project/snapshot、request_key/hash、index_version/config_identity、generation、status/stage/result/error、lease_token/lease_until/attempts、创建更新时间；UNIQUE(owner,request_key)，队列索引(status,lease_until,created_at)。task事件记录顺序与安全码，不放私有原文。Outbox留S6同事务扩展。
- project删除级联快照/文件/发布/派生/任务/事件；单个数据域没有跨SQLite FK。完整ER/数据字典/时序按最终DDL在报告补齐。

## 发布和并发不变量

1. 编码/解析在事务外；事务按project→snapshot→task锁顺序，核对owner、快照存在、任务RUNNING/有效token/lease、generation/config，再写不可变派生发布。
2. task完成、active_publication、index_status在同一PG事务提交。中间故障全部回滚，保留旧发布；不是先写PG任务再写SQLite索引。
3. 每次新请求的期望generation在事务里递增；同请求键去重不递增。旧任务即使自己的lease尚有效也不能覆盖较新的期望代次。worker模型/解析配置与请求不一致不得发布。
4. 原3次恢复/心跳/队列配额保留；领取可用FOR UPDATE SKIP LOCKED（[PG14官方说明](https://www.postgresql.org/docs/14/sql-select.html)），只用于队列竞争，不当作通用一致性读取。到期校验用数据库时间，完成前再次核对，不靠模型结论。
5. 引用仍按固定owner/project/snapshot/文件hash/行原文；PG不升级个人贡献或C1，不执行导入代码，不让模型写SQL。

## 资源与迁移

现有psycopg3.3.4实际导入成功（binary/libpq18客户端，不是PG18服务），apt缓存PG14.23；没有可用postgres命令。先在项目output目录下载/核SHA、提取官方发行包，不apt install、不改系统/旧项目；必要时将独立运行时放本轮/tmp/job-agent-v3-*目录，由nobody运行PG，私有Unix socket，无公网端口。启动/停止只针对本轮精确PID/路径。Redis6.0不满足XAUTOCLAIM，S6另补6.2+；本阶段不假报Redis可用。

迁移只在本轮合成SQLite夹具演示：源备份、只读一致快照、dry-run数量/hash/稳定ID核对，目标空域/冲突拒绝，拒绝迁移活动lease，写入后复核并切换配置；不删除源库，不复制旧项目可能私有的历史评测。回滚配置到原备份。schema版本明确，DDL迁移可重复且不破坏既存用户资料。

## 验收与教学

共享合同测试覆盖SQLite/真实PG：owner、不可变版本、请求幂等/冲突、配额/删除、发布/回滚、过期与跨代次fencing、配置不符、并发领取。真实HTTP至少一项目ZIP→快照→持久任务→索引→检索→新进程重启读取；确认SQLite无该项目/索引/任务影子数据，面试/引用使用PG且跨用户404。另演示合成迁移dry-run/写入/核对/回滚。可配时跑真实向量重启，不把fixture向量叫真实模型。

先新合同与旧project/code/tasks回归，再扩大相关检查；原缺资源失败不删。更新CURRENT_SPEC/CHANGELOG/INDEX/矩阵/架构/决策/EXPAND-S5，附ER、数据字典、提交时序、3—5源码入口、5问与参考要点和30分钟导读。服务/模型/人工质量分别报告。
