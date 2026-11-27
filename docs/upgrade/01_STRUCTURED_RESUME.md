# 第 1 步：把简历变成能追溯、能修改、能确认的业务数据

日期：2026-10-20。范围：M1 本地后端增量，**尚不是完整产品 Demo**。

后续 M2 已接通前端和导入/解析/编辑，见 [第 2 步](02_IMPORT_PARSE_EDITOR.md)；本文保留 M1 的实现与测试范围。

## 遇到了什么问题

现有 UI 的主要材料仍是文本和文件；后端的 `CareerSnapshotPayload` 保存原始简历文本与
evidence refs，可以冻结一次任务的输入，但没有个人信息、教育、工作、项目和技能的字段合同。
它也不是支持用户局部编辑、版本确认、恢复的简历管理接口。

如果直接在这上面增加“AI 改写并导出”，不同功能可能各自处理不同文本；
投递记录无法准确说明当时使用了哪份简历；两个编辑页面也可能覆盖彼此的更改。

## 本次具体做了什么

| 能力 | 源码与函数 | 为什么这样做 |
|---|---|---|
| 统一个人信息、教育、经历、项目、技能模型 | `resume_workspace/contracts.py:ResumeDocument` | 编辑器、解析角色、后续校验与渲染有同一数据合同 |
| 每个事实带来源 ID/hash/字符范围 | `ResumeFact`、`SourceSpan`；`repository.py:_validate_document` | 把“这句话来自哪里”变成程序可验证的关系 |
| JD、公共参考资料不能作为个人事实来源 | `_validate_document` | 检索到某技术，不代表用户掌握该技术 |
| 每次保存新增版本，不修改历史内容 | `save_version`、`_append` | 投递记录后续可绑定稳定版本 |
| 带当前父版本保存 | `save_version` 的 expected parent 检查 + SQLite 写事务 | 两个页面同时编辑时一个成功，另一个明确收到 409，而非静默丢数据 |
| 确认绑定版本与内容 hash | `confirm_version`、独立 `rw_confirmations` | 查看并确认的内容与保存内容保持一致；重复确认可幂等返回 |
| 恢复也是一个新版本 | `restore_version` | A → B → A 保留 B 的历史，不继承旧版确认 |
| 来源删除约束、简历删除级联 | `delete_source`、`delete_resume` | 保留历史时引用有效；用户能主动移除业务数据 |
| 服务端身份、跨用户 404、错误不回显私密值 | `api.py:create_resume_app` | 不能让客户端用 user_id 冒充别人，也不能把隐私值拼进验证错误 |

这里只允许**抽取式事实**：`fact.text == canonical_source[start:end]`。
这样能确定性阻止“引用原文却偷偷改成掌握 Kubernetes / 提升 80%”。这不等于已有语义改写功能。
下一步优化会使用单独的“建议”合同，保留原始事实；语义校验和用户接受之前不能直接覆盖事实。

用户若确实补充新经历，应先新增 `user_statement` 来源，再引用新事实。
来源类型仍由提交者声明，系统不能检测所有人为造假，来源校验也不能证明现实经历真实。
用户确认只标记 `user_attested_only`，不会自动赋 C2/C3。现有 Evidence v2 等级逻辑未修改。

## 一次完整数据流

```text
服务端把 bearer token 映射为 owner
→ POST /api/v2/sources
→ SourceCreate 规范化 NFC / 换行
→ SqliteResumeRepository.add_source 保存不可变文本和 SHA-256
→ 客户端/后续解析角色引用返回的规范化文本字符范围
→ POST /api/v2/resumes
→ ResumeDocument 检查结构与唯一 ID
→ _validate_document 检查 owner / kind / hash / range / exact text
→ _append 在同一事务中保存简历、版本和来源引用
→ POST .../versions/{id}/confirm，绑定 content_hash
→ POST .../versions，带 expected_parent_version_id，新版重新等待确认
→ POST .../versions/{old_id}/restore，新增恢复版本
```

这条链全部是 Python 逻辑，没有 LLM、embedding、OCR 或检索调用。
业务内容 hash 和版本 ID 含义不同：相同内容可以出现在不同历史位置，所以恢复允许相同 hash，
却产生新的版本 ID。历史确认继续存在；新版本不会自动确认。

## 怎么运行

在项目根目录、已有 Python 3.11+ 开发环境中：

```bash
python -m pip install -e ".[dev]"
python scripts/demo_resume_versions.py --output-dir output/demo-resume-m1
python -m pytest -q tests/test_resume_workspace.py
```

脚本使用合成姓名和技能，演示保存、确认、重排、恢复、重新打开仓库。
每次新建演示简历，不重置或删除已有数据库。报告 `checks` 应全部为 true。
这是数据/API 增量的 Demo，没有前端，也没有真实模型成绩。

API 使用：在进程环境配置私有的 `JOB_AGENT_WORKSPACE_API_TOKEN`（ASCII，至少 32 字符；
本地随机生成，不写进仓库，不在日志中展示）。可通过 `JOB_AGENT_WORKSPACE_DB` 指定数据库路径。
然后：

```bash
python -m uvicorn job_agent.resume_workspace.main:create_app --factory --host 127.0.0.1 --port 8011
```

打开 `http://127.0.0.1:8011/docs`，用 Authorize 设置 bearer。
本地启动器只映射一个用户；测试工厂映射两名合成用户验证隔离。
这不是完整注册/登录/会话管理系统，不应直接作为公网多人服务发布。

如果环境仅通过 editable src 安装、运行脚本无法解析项目包，可在 PowerShell 设置
`$env:PYTHONPATH='.;src'`；Linux 设置 `PYTHONPATH=.:src`。不要从私有目录导入演示材料。

## 实际验证

运行记录位于 `docs/audit/upgrade-m1/`。最初受限沙箱执行到 API 测试时，Windows asyncio
在创建本机 socketpair 阻塞；中断后在允许回环网络的环境重跑。没有更改逻辑来绕开 API。

- 增量前现有来源/长期状态/应用评测聚焦回归：33 passed。
- 新增测试：34 passed / 0 failed / 0 skipped。包含两个并发修改、A-B-A 恢复、外来用户引用、
  JD/参考库混入、伪造 hash/quote/offset、持久化重开、来源删除和实际 FastAPI 请求路径。
- 初次新增测试有一个 Starlette/AnyIO 依赖弃用警告，保留原日志，不为消警告更改项目依赖。
- 合成脚本 6 项检查全为 true；不是 6 个模型任务或语义准确率。
- 合并相关模块回归：**110 passed / 0 failed / 0 skipped**（包括新增 34 项，不相加重复计数）。
- 本机实际启动 Uvicorn 后，8 项 HTTP 检查全部通过，包括无凭证拒绝、创建、确认、读取和删除；
  临时服务已关闭。没有使用真实简历或模型凭证。
- 25 个公开 `eval/` 文件与冻结基线包逐字节 hash 相同。具体命令、版本和结果见同目录
  `verification.json`；旧版 568/0/16 是历史 Linux PG/Redis 基线，不能直接当成本轮升级全量结果。
- 本轮未运行全仓库真实 PG/Redis 回归，也未运行模型、OCR、ES、PDF 或前端 E2E；M1 未修改这些执行链。

## 现在还缺什么

新模型未接入旧 UI、LLM 解析、Evidence v2、后台 Worker、React、PDF 或真实投递流程。
没有把既有后端悄悄切换到新 API，没有自动迁移已有用户文件。
SQLite 版本仓库用于本地先行验证，后续产品 PostgreSQL 迁移需要独立适配与真实集成测试。
此增量没有多进程任务恢复、对象存储、OCR、ES、登录系统或模型成本统计。

删除 API 移除逻辑记录，但不承诺 SQLite 空闲页、磁盘快照或备份的物理安全擦除；
多人部署的数据生命周期和备份清理另行验收。引用尚存时先删除相应简历，再删除来源。

## 你需要理解的 5 个问题

**1. 为什么不直接存一段大文本？**
文本适合作为原始来源；结构化模型适合作为可编辑业务数据。两者同时保留，原文帮助核验，
字段帮助局部编辑、校验和模板渲染。

**2. 引用了原文就能证明事实正确吗？**
只能证明来源关系；不能证明用户确实做过，也不能证明以后任意改写都由这段话支持。
因此 M1 只保存抽取事实，生成建议要另过语义校验与确认。

**3. 为什么要 expected_parent_version_id？**
它表达“我是在这个版本上编辑的”。如果别人已经保存新版，服务器拒绝覆盖，要求刷新/处理冲突。
数据库事务保证检查与新增不能被另一条写入插到中间。

**4. 为什么恢复旧版后还要确认？**
恢复是一项新的用户操作，可能发生在另一个岗位或时间点；相同内容不代表旧确认适用于当前工作。
新版本保留恢复来源和父版本，历史可以回看。

**5. 为什么第一步没有增加新 Agent？**
Agent 需要稳定的输入输出和可以安全调用的工具。先把个人事实、版本和确认合同确定下来，
后续四个角色才知道能读取什么、能提出什么、什么需要由用户决定。

可用于面试的一句话：

> 我先为求职助手补了结构化简历和不可变版本管理，每个原始事实关联用户来源的 hash 与字符范围；
> 保存时用当前父版本避免并发覆盖，确认绑定具体内容，恢复保留历史。这个本地增量有 API 与边界测试，
> 目前还没有把它说成完整的多 Agent 简历产品。
