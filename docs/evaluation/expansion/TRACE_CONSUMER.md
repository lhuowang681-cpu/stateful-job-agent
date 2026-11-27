# 统一追踪的只读消费合同

版本job-agent-trace-1 / job-agent-trace-export-1。第二项目只接收本合同、schema与合成样例，本轮没有修改或替它开发归因器。调用原服务的认证GET接口：`/api/v2/rewrites/{run_id}/trace`、`/interviews/{session_id}/trace`、`/tasks/{task_id}/trace`（均以前缀`/api/v2`开头）。默认JSON，`?format=jsonl`下载逐事件记录；Cache-Control no-store。跨owner为404，未认证401，非法format422。

导出从原SharedRunState、Harness调用结果、InterviewTools、EvidencePack轮次和所选TaskRepository读取。没有新运行器、后台订阅、重放工具、模型或审批动作。改写导出显式关闭原get中的过期恢复写入；面试走原_load来源/owner/hash校验，源已删除不借导出绕过。旧无execution的改写报409 `trace_legacy_execution_unavailable`，旧SQLite任务只给当前快照并标缺历史。

|字段|合同与边界|
|---|---|
|trace_id/run_id/span_id/parent_span_id|稳定派生不透明ID；根span无parent，其余指向根。started/completed可共享span。不是凭ID重新运行原任务|
|seq/source_stream/source_seq|seq为导出顺序；role/tool/round/task保留原序号。不同流没有可靠全局墙钟顺序，pack以correlation_id区分|
|kind/phase/status/attempt/revision|原运行、角色、工具、检索轮次与PG事件的结构化投影。旧记录缺attempt/time保持null；不是补造历史|
|role_id/tool_id/model_identity_hash|角色/工具名与实际模型/skill/prompt版本的hash，支持同一身份聚合。默认不公开任意模型路径或自由字符串|
|material_hash/input_hash/output_hash/evidence_ids|材料身份及实际输入输出摘要、引用ID；不包含原文、回答、完整rubric、提示、身份令牌、lease token|
|recorded/started/ended_at_utc/time_quality|只有确实记录的时间可用；工具和检索常只有duration_only，旧事件unknown。旧checkpoint反序列化不赋当前时间|
|input_tokens/output_tokens/cost/usage_scope|call为真实Harness完成记录；run_aggregate为原业务汇总，不能再加子span。Provider未返回、错误调用未留用量为null，费用无账单为null|
|provider_calls/usage_missing_reason|0仅用于原账本明确没有Provider调用的规则执行；未知用量不是0。工具/检索不冒充文本生成|
|error_code_id/fallback_used/approval_hash|错误与反馈用不透明关联ID；fallback仅有原记录时填bool；审批只给有无与hash，不复制决定正文|

JSON外壳usage只取run_aggregate；child_*_observed是独立观察小计，不能与总量相加。若根unknown但有部分已知子记录，总量仍unknown，child_usage_complete与provider_calls帮助判断缺口。单次512事件/8MiB读取预算，超预算不静默截断。原执行状态128事件上限仍保留。

下载文件后运行：

```text
python scripts/inspect_unified_trace.py path/to/export.jsonl
```

该命令只做schema、父子、序号和单run身份检查，输出executed_actions=0，不恢复审批/调用/Worker。不从Trace里的ID、状态或错误数推断语义支持、个人能力或生产SLA。哈希用于完整性和关联，不是匿名性证明或恶意生产者签名；有访问权限的业务原文仍由原接口管理。
