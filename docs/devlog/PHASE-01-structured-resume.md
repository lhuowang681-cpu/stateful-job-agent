# PHASE-01 · 结构化简历、来源与不可变版本（M1 补录）

- 实现/补录日期：2026-10-20；本报告为完成后的补录，不伪装成开发时同步记录。
- 状态：本地确定性 API 增量已验证；完整产品与真实模型不在本阶段范围。
- Git 起点：原阶段开始时的 branch/status 未完整留存，**未核实**；功能基线为审计冻结源码包。
- Git 终点：无本阶段独立提交；补录时核验为 `main` / `067bfc7d63408e1e6b0ab6c227e863bd08a5857a`，含未提交工作区变更。
- 历史源码快照：`job-agent-upgrade-m1-source.zip`，SHA-256 `2ce96565216e6a2938ff2a9b974d921bb431f95c10d6042b9512c77dffcd9eee`。
- 运行环境：Windows 11、Python 3.12.14、pytest 9.1.1、FastAPI 0.115.14、Pydantic 2.14.0；没有模型调用。
- 证据入口：[M1 verification](../audit/upgrade-m1/verification.json)、[阶段源码快照差异](evidence/phase-snapshots.json)。

## 1. 业务目标与验收标准

让后续简历编辑、投递版本绑定和 PDF 渲染共享结构化数据，而不是各自修改不确定的大段文本。
本阶段验收：来源保存 → 字段引用 → 保存简历 → 带父版本编辑 → 指定版本确认 → 恢复旧内容 → 重新打开仓库仍可读。
错误引用、JD/参考混入、越权访问和并发覆盖应明确拒绝。

不要求本阶段具备前端、LLM 抽取、自动改写或 PDF；这些能力不能用 API 存在来替代。

## 2. 原有问题和基线

旧 UI 以来源文件、规范化文本和 session artifacts 为主；`backend_service/career_snapshot.py::CareerSnapshotPayload`
冻结的是 resume_text/evidence_refs，不是含教育、工作、项目字段的可编辑简历版本。
原有 Evidence v2 来源验证真实存在；此次新增业务版本管理，不替换它的等级与投影规则。

开发增量前，相关来源/长期状态/应用评测回归 **33 passed**，不能称全仓库基线。
历史基线 `568/0/16` 来自另一次 Linux 真实 PG/Redis 环境，不能当作 M1 的新结果。
开始时完整 Git status 缺失；精确前后内容以保留源码包及 manifest 为依据。

## 3. 技术方案及取舍

- `ResumeDocument` 统一结构；每个 `ResumeFact` 带 `SourceSpan`（source_id、hash、字符范围）。
- 原始文本保存为规范化 Unicode；字段必须逐字等于该范围，来源必须属于当前用户且为原简历/用户自述。
- 历史版本只追加；内容 hash 标识内容，随机 version_id 标识一次历史位置，允许 A → B → A。
- 保存使用期望父版本和数据库写事务；确认在独立记录中绑定版本/hash；新版本不继承确认。
- SQLite 为单机先行实现；不与现有 PostgreSQL 任务状态双写，不宣称完成产品 PG 迁移。

备选一：仅保存最终 Markdown。实现快，但字段引用、局部编辑和投递版本难以稳定关联。
备选二：直接扩展现有后端 snapshot/迁移 PG 并统一所有入口。将同时改变旧队列、证据和 UI 合同，
回归范围大，当前先分离业务合同，再在后续阶段适配。
代价：数据结构更细，原始事实暂只允许抽取文字，任意改写必须另走建议/语义核验流程。

## 4. 实际调用链与代码地图

```text
HTTP bearer → create_resume_app.owner
→ add_source → canonical_text → SqliteResumeRepository.add_source
→ create_resume → ResumeDocument → _validate_document → _append
→ save_version（期望父版本） / confirm_version（期望内容 hash）
→ restore_version（新版本） → SQLite → VersionRecord
```

M1 的 `_validate_document` 原本直接检查来源；M2 在保持合同的前提下抽出 `_validate_draft_facts` 共享。
当前源码包含后续增量，阅读历史实现时同时看快照 diff。

| 阅读顺序 | 代码锚点 | 输入 → 输出 | 为什么读 |
|---|---|---|---|
| 1 | `src/job_agent/resume_workspace/contracts.py::ResumeFact` | 文字/来源 → 字段合同 | 区分事实与来源关系 |
| 2 | `src/job_agent/resume_workspace/contracts.py::ResumeDocument` | 结构字段 → 受校验文档 | 统一业务结构与 ID |
| 3 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository._validate_document` | 文档/身份 → 校验或拒绝 | 来源边界 |
| 4 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.save_version` | 父版本/修改 → 新版或冲突 | 防丢失更新 |
| 5 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.confirm_version` | 版本/hash → 确认记录 | 确认不漂移 |
| 6 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.restore_version` | 历史版/当前父版 → 新版 | 恢复保留历史 |
| 7 | `src/job_agent/resume_workspace/api.py::create_resume_app` | 服务端身份解析器 → API | 客户端不能指定 owner |
| 8 | `scripts/demo_resume_versions.py::run_demo` | 合成材料 → 检查报告 | 最短可运行数据流 |
| 9 | `tests/test_resume_workspace.py::test_simultaneous_edits_have_one_winner` | 两个并发写 → 一个成功 | 理解并发保证 |

## 5. 功能开发轨迹

以下按可独立工作的功能补录，不声称保存了当时的每个操作时刻。

### 功能 A：可核验字段

- 问题：生成或编辑后的文字难以说明来自哪份用户材料。
- 方案：规范化来源 + hash + 字符范围；只接受逐字片段。备选仅 source_id 不足以定位版本和原句。
- 数据流：`contracts.py::SourceCreate.canonical_text` → `repository.py::SqliteResumeRepository.add_source` → `_validate_document`。
- 改动：个人信息/教育/经历/项目/技能均用来源字段；JD/reference 来源禁止作为个人事实。
- 验证：`python -m pytest -q tests/test_resume_workspace.py` 的对应历史运行共 34 passed；见 M1 JUnit。
- 限制：证明来源关系，不能证明现实经历真实，也不能证明任意后续改写语义成立。

### 功能 B：保存、确认和恢复

- 问题：覆盖最终文本会丢历史；恢复相同内容也可能错误继承旧确认。
- 方案：版本追加 + 独立确认记录；备选 content hash 直接当主键无法表示 A-B-A 的不同历史位置。
- 数据流：`repository.py::SqliteResumeRepository.save_version` → `_append` → `confirm_version` / `restore_version`。
- 改动：expected parent、sequence、content_hash、restored_from、confirmed_at；新版本重新待确认。
- 验证：并发唯一赢家、旧版本不变、确认幂等、A-B-A、重开仓库等包含在 34 项中；合成脚本 6 项检查为 true。
- 限制：本地事务保证，不是多进程工作流恢复或付费模型幂等协议。

### 功能 C：身份与清理边界

- 问题：客户端传 user_id 会使身份可伪造；来源直接删除会破坏历史引用。
- 方案：可信服务端 token 映射身份、跨用户与不存在均返回 404；引用约束保护来源。
- 数据流：`api.py::create_resume_app` → owner → `repository.py::SqliteResumeRepository.delete_resume` / `delete_source`。
- 改动：错误响应不回显私人值；私有启动器要求外部配置口令；删除简历与版本记录级联。
- 验证：实际本机 Uvicorn 8 项 HTTP 检查全 true，包含无凭证拒绝和创建/确认/删除；M1 临时服务已停止。
- 限制：单用户开发身份适配；不是账号登录平台，也不承诺磁盘/备份安全擦除。

## 6. 可复现验证（历史实际执行，非本次重跑）

仓库根目录、已装开发依赖，等价 pytest 命令：

```powershell
python -m pytest -vv --tb=short -o faulthandler_timeout=30 tests/test_resume_workspace.py
python -m pytest -vv --tb=short -o faulthandler_timeout=30 tests/test_resume_workspace.py tests/test_source_audit_regressions.py tests/test_career_store.py tests/test_application_assistant_evaluation.py tests/test_backend_service.py tests/test_evidence_source_store.py tests/test_evidence_mapping_v2.py tests/test_evidence_projections.py tests/test_evidence_requirement_analyzer.py
$env:PYTHONPATH='.;src'
python scripts/demo_resume_versions.py --output-dir ../../work/upgrade-m1-demo
```

实际使用了工作区 `work/run_audit_tests.ps1` 包装器设置临时目录/环境；准确命令和版本见 verification.json。
M1 快照运行新增 **34/0/0**、合并 **110/0/0**，后者包含前者，不能相加。
合成脚本 6 检查、真实本机 HTTP 8 检查不是模型任务样本数。
首次沙箱在 Windows asyncio socketpair 阻塞，中断后在允许 loopback 环境原样通过；保留旧依赖弃用警告。

| 验证类别 | 状态与证据 |
|---|---|
| SQLite/确定性合同/FastAPI 请求 | 已运行；`docs/audit/upgrade-m1/upgrade-m1-tests-network.xml`、`upgrade-m1-regression.xml` |
| 实际本地 HTTP | 已运行；`docs/audit/upgrade-m1/http-smoke.json` |
| 合成数据流 | 已运行；`docs/audit/upgrade-m1/synthetic-demo.json` |
| 真实 LLM / embedding / PG/Redis 全量 | M1 未运行，不能继承历史成绩 |

在当前 M2 源码重跑并不是重放原 M1 快照；需要精确历史条件时用 M1 源码包及记录环境。

## 7. 效果与实验数据

| 指标/样本 | 旧基线 | M1 | 同口径？ | 证据 |
|---|---|---|---|---|
| 既有聚焦回归 | 33 pass | 纳入后续合并 | 测试集扩展，不能当提升率 | verification.json |
| 新增合同/边界测试 | 无此模块 | 34 pass | 新功能验收，无模型对照 | M1 JUnit |
| 合并相关模块 | 未跑相同集合前后对照 | 110 pass | 无有效质量对照 | M1 regression.xml |
| 版本演示 | 无统一版本 API | 6 项检查 true | 功能演示，不是 benchmark | synthetic-demo.json |
| 模型准确率/成本 | 未测 | 未测 | 无结论 | 无新模型结果 |

## 8. 风险、技术债、下一步

M1 适合本地结构化事实与历史；生产认证、PG 迁移、任务恢复、模型解析和 UI 当时未接入。
下一步 M2 已完成导入/编辑增量，见 PHASE-02；未来 JD 适配仍不能自动把用户确认升级为 C2/C3。
没有为了方便生成而修改现有 Evidence v2 的证据约束。

## 9. 事后学习路线（约 45 分钟）

1. 8 分钟读 `contracts.py`：区分 SourceRecord、ResumeFact、VersionRecord。
2. 12 分钟读 `_validate_document`、`save_version`：画出校验和事务范围。
3. 8 分钟读 `confirm_version`、`restore_version`：解释版本 ID 与内容 hash 的差别。
4. 10 分钟运行合成脚本和上述测试，看重排/恢复后的 hash、sequence、confirmed_at。
5. 7 分钟读并发测试；可在临时示例里调整技能顺序观察新版本，勿修改真实材料或冻结标注。

要能复述：来源不等于现实真相；父版本防覆盖；恢复不继承确认。

## 10. 面试追问（5 题）

1. **为什么文本和结构化字段都保留？** 文本提供可核验原始依据；字段服务编辑/校验/渲染，互不替代。
2. **引用真实是否代表新增业绩成立？** 否；本步只允许抽取文字，新增改写需独立语义校验和人工决定。
3. **同时编辑怎么保证不覆盖？** 同一写事务内检查 expected parent；先成功的推进 head，另一个收到冲突。
4. **为什么相同 hash 可以有不同 version_id？** hash 是内容身份，版本是历史动作；恢复旧内容也要保留中间历史。
5. **确认是不是 C2？** 不是。它只代表用户认可确切版本，不提供第三方证据，不改变 Evidence v2 来源等级。
