# PHASE-02 · 导入、字段解析与 React 编辑工作台（M2 补录）

- 实现/补录日期：2026-10-20；功能完成后补录，历史过程以既存日志为依据。
- 状态：本地导入/核对/版本闭环已验证；模型接口已接，真实模型验收未完成。
- Git 起点：原阶段完整 branch/status 未留存，**未核实**；功能基线为 M1 源码快照。
- Git 终点：无本阶段独立提交；补录核验 `main` / `067bfc7d63408e1e6b0ab6c227e863bd08a5857a`，工作区未提交。
- 历史源码包：`job-agent-upgrade-m2-source.zip`，SHA-256 `e0a9019dd0d5c7033bf4fdb7952f2b71ca7581deb26c93dea7f3683238c72caf`。
- 环境：Python 3.12.14、FastAPI 0.115.14、pypdf 6.10.0、python-docx 1.2.0；Node 24.19.0、React 19.3.1、Vite 8.3.4。
- 证据：[M2 verification](../audit/upgrade-m2/verification.json)、[截图与逐步说明](../upgrade/02_IMPORT_PARSE_EDITOR.md)。

## 1. 业务目标与验收标准

用户可以上传或粘贴简历，核对结构化草稿，补齐信息后保存/确认；修改可形成新版，历史可恢复。
原文件、抽取文本与人工补充分别留痕；缺失字段不能用虚构值填齐。
验证至少覆盖导入限制、原文引用、模型调用边界、草稿接受幂等、版本编辑、真实浏览器操作。

目标不包含本轮接通 JD 匹配、RAG、四角色工作流、PDF 或长期投递，它们仍是后续计划。

## 2. 原有问题和基线

M1 只有结构化合同、版本库和 API，普通用户需要手写 JSON。
已有 `knowledge/source_loader.py::load_source` 能抽取文本 PDF/DOCX，但没有接入新产品上传入口。
已有模型传输和 LLMHarness 可复用；无须另造一个模型 SDK。

M2 修改前相关聚焦测试 **40 passed**（M1 34 + 既有 ingestion 6），不是性能/质量对照。
M1 的 110 项集合与其不同，不可把 40 和 110 的大小解释成退步。

## 3. 技术方案及取舍

- 同源 React + FastAPI：界面发送带身份的请求，FastAPI 提供构建产物。
- 文件导入先做格式/大小限制，复用 loader；规范化文本与原文件字节分别保存并计算 hash。
- `DraftDocument` 允许缺失，完整 `ResumeDocument` 沿用严格要求；缺失时给用户明确问题。
- 模型只提出字段 path、exact_quote 和可选位置；Python 验证白名单与引用并生成结构 ID。
- 本地保守规则明确标记，在线模型需服务端配置及本次同意；最多两次总调用，无静默规则替代。
- 人工修改保存为新的 user_statement；接受草稿及相关来源/版本在同一事务提交，重复接受幂等。

备选一：让 LLM 直接生成整份“优化简历”。难以区分抽取与新增事实，也无法稳定局部编辑，因此未选。
备选二：先建 OCR/ES/新队列再做页面。不能解决 M1 无法直接使用的问题，服务集成留到对应阶段。
备选三：沿用 Streamlit 统一承载新产品。旧 UI 有独立证据流程，本轮用独立 React 产品入口逐步适配，保留对照路径。
代价：暂有两个界面，SQLite 与旧 PG 状态尚未统一，不能称全系统重构完成。

## 4. 实际调用链与代码地图

```text
App.parse → import_file / add_source → extract_upload → load_source → save_upload
→ parse_source（身份/发送同意） → ResumeParser.parse
  ├ local_candidates（规则，无模型）
  └ LLMHarness.invoke_structured（已接接口，真实模型未验收）
→ materialize → save_draft → 原文/字段表单
→ accept_draft → _apply_edits → _append → 确认/编辑/恢复
```

| 顺序 | 代码锚点 | 输入 → 输出 | 重点 |
|---|---|---|---|
| 1 | `frontend/src/main.jsx::App.parse` | 文件/文字/模式 → API 草稿 | 页面入口 |
| 2 | `src/job_agent/resume_workspace/api.py::create_resume_app.import_file` | 字节流 → 上传结果 | 身份与流式大小限制 |
| 3 | `src/job_agent/resume_workspace/ingestion.py::extract_upload` | 文件名/bytes → 抽取文本/元数据 | 文件边界 |
| 4 | `src/job_agent/resume_workspace/parsing.py::ResumeParser.parse` | 来源/模式 → DraftRecord | 模型调用上限与失败 |
| 5 | `src/job_agent/resume_workspace/parsing.py::materialize` | 候选字段 → 可追溯草稿 | 引用与 ID |
| 6 | `src/job_agent/resume_workspace/fields.py::checked_path` | path → 白名单路径 | 任意属性/越界拒绝 |
| 7 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.accept_draft` | 草稿/核对改动 → 完整版本 | 事务与幂等 |
| 8 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository._apply_edits` | 显式改动 → 自述来源/文档 | 原文与补充分离 |
| 9 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.edit_version` | 当前版/改动 → 新版 | 继承 M1 并发约束 |
| 10 | `tests/test_resume_import.py::test_model_transport_timeout_does_not_retry_potentially_billable_call` | 超时替身 → 一次调用后停止 | 成本/不确定失败边界 |

## 5. 功能开发轨迹

### 功能 A：上传与原件保留

- 问题：用户已有 PDF/DOCX，不能要求手工构造字段 JSON。
- 方案：复用 loader，最大 5 MB；PDF 加密/页数检查、DOCX 展开限制；备选每份文件 OCR 会增加成本与错字。
- 调用链：`api.py::create_resume_app.import_file` → `ingestion.py::extract_upload` → `repository.py::SqliteResumeRepository.save_upload`。
- 改动：文本与原件 hash 分开；客户端文件名只做显示，不控制保存路径；原件读取受 owner 限制。
- 验证：真实文字 PDF、中文 DOCX 合成文件、坏格式/大文件/无文字 PDF/加密和展开限制测试，含最终 154 项。
- 限制：没有 OCR；5 MB 不等于 CPU/内存硬隔离，复杂版式识别率未测。

### 功能 B：字段草稿与补问

- 问题：解析可能漏姓名或经历名，不能编造必填项来通过校验。
- 方案：不完整草稿与完整版本分开；备选放宽所有 ResumeDocument 字段会削弱保存合同。
- 调用链：`parsing.py::ResumeParser.parse` → `materialize` → `missing_fields` → `repository.py::SqliteResumeRepository.save_draft`。
- 改动：唯一 quote 或有效 offsets、受限字段路径、Python 生成 IDs；模型结构/引用仅修复一次，传输失败不自动重试。
- 验证：缺姓名、模糊引用、伪造 quote、越界路径、一次修复/两次失败、超时单次调用；模型均用测试替身。
- 限制：只证明抽取引用，不证明分类语义或任意真实模型质量；费用未知不填假值。

### 功能 C：人工核对、编辑与幂等接受

- 问题：用户新补充不能伪装成原 PDF 内容；重复点击不能建立两份简历。
- 方案：只提交 changedFields，补充写独立自述；接受请求 hash 绑定草稿和事务。备选直接改原来源会破坏历史。
- 调用链：`frontend/src/model.js::changedFields` → `repository.py::SqliteResumeRepository.accept_draft` → `_apply_edits` → `_append`。
- 改动：同请求重复接受返回同一版本，不同请求冲突；局部编辑带当前版本检查；引用保护与来源清理界面。
- 验证：并发接受只有一份简历，失败回滚无孤立来源，人工补充 kind 正确；旧 M1 34 项同时回归。
- 限制：请求内模型调用仍未接 Worker；解析付费操作没有跨重启幂等协议。

### 功能 D：可实际试用的界面与隔离 Demo

- 问题：代码和 API 验证不足以展示用户如何连续使用。
- 方案：React 原文/表单/版本界面，同源提供；合成 Demo 临时库无模型。备选直接用私人库演示会混入真实资料。
- 调用链：`scripts/demo_resume_workbench.py::build_demo_app` → `api.py::create_resume_app` → `frontend/src/main.jsx::App`。
- 改动：公开演示口令仅适用临时实例，私有启动器仍需单独口令；切换材料/解析尝试清除在线发送同意。
- 验证：浏览器走通粘贴/保存/确认/编辑/恢复；无姓名 DOCX 上传拒绝后补齐；1280/390px 无水平溢出；4 个前端测试/构建成功。
- 限制：浏览器手工验收不虚报成自动 E2E 测试数；生产认证未完成，正常退出清理与强制终止遗留不同。

## 6. 可复现验证（历史实际执行，非本次重跑）

仓库根目录，后端等价命令；准确包装器命令见 verification.json：

```powershell
python -m pytest -vv --tb=short -o faulthandler_timeout=30 tests/test_resume_import.py tests/test_resume_workspace.py tests/test_source_audit_regressions.py tests/test_career_store.py tests/test_application_assistant_evaluation.py tests/test_backend_service.py tests/test_evidence_source_store.py tests/test_evidence_mapping_v2.py tests/test_evidence_projections.py tests/test_evidence_requirement_analyzer.py tests/test_knowledge_ingestion.py
```

前端目录实际执行过 `npm install --ignore-scripts --no-fund` 生成锁文件，随后：

```powershell
npm test
npm run build
npm audit --json --registry=https://registry.npmjs.org
```

项目根目录实际启动过：

```powershell
python scripts/demo_resume_workbench.py
```

历史最终结果：后端相关 **154 passed / 0 failed / 0 skipped**，包含 M2 新增 38 项与 M1/旧模块测试；
前端 **4 passed / 0 failed**，构建成功。两种测试集合不相加为“158 个后端用例”。
真实 SQLite/HTTP/浏览器已验证；真实模型、PG/Redis 新产品链、OCR/ES/PDF 未运行。

证据：`docs/audit/upgrade-m2/upgrade-m2-final-demo.xml`、`frontend-tests.log`、`frontend-build.log`、
`verification.json`、`workbench-desktop.png`、`workbench-mobile.png`。

失败记录：最初 66 个用例中 65 通过，1 个用例 setup/teardown 共产生 2 个 error 事件，
原因是 5 MB 参数自动生成超长测试 ID，超过 Windows 环境变量上限。
只设置短 ID，原大小/断言不变，重跑通过。旧 verification 简单相减曾错误写成 64，
本次依据原 JUnit 核对后修正为 65，并单列事件/用例数；不改原日志或测试。
默认 npm 镜像审计 404，官方接口同锁文件查询本次 0 已知漏洞；不等于生产安全认证。

## 7. 效果与实验数据

| 指标/样本 | M1 基线 | M2 | 同口径？ | 证据 |
|---|---|---|---|---|
| 普通用户导入和编辑界面 | 无此新产品页面 | React 表单与来源/版本连通 | 功能验收，不是质量提升率 | 浏览器记录/截图 |
| 修改前聚焦回归 | 40 pass | 最终集合扩大 | 不能直接比较数量 | before / final JUnit |
| 相关后端回归 | M1 110 pass | M2 154 pass，新增 M2 38 + ingestion 6 | 测试集扩展 | verification.json |
| 前端数据/Unicode | M1 无此前端 | 4 pass | 新功能测试 | frontend-tests.log |
| 模型解析准确率/成本 | 未测 | 未测 | 无结论 | 不沿用 R12 |

没有真实模型的同数据前后实验，不能写准确率提高、解析覆盖率提升或成本下降百分比。
冻结的 25 个公开 eval 文件逐字节未变；旧 R12 不是本步解析模型成绩。

## 8. 风险、技术债、下一步

规则只识别明确格式，未识别原文仍保留；PDF 混合扫描页/复杂布局未全面验证。
模型接口未做真实质量/费用验收；生产认证、PG/Worker 产品适配、对象存储与恢复协议待完成。
下一步 M3：新工作台接 JD 要求与已有证据边界、受限修改建议/人工审批，保留来源级别。
本次任务只补录文档，不启动该功能开发。

## 9. 事后学习路线（约 55 分钟）

1. 10 分钟运行隔离 Demo，体验一次补充、保存、确认和恢复。
2. 10 分钟读 `App.parse` 与 `create_resume_app.import_file/parse_source`，画前后端请求顺序。
3. 12 分钟读 `ResumeParser.parse` 与 `materialize`，区分模型提议和 Python 可验证事实。
4. 13 分钟读 `accept_draft` / `_apply_edits`，解释事务、重复提交和用户补充来源。
5. 10 分钟读超时/并发/缺失信息测试；用合成示例删去姓名观察拒绝与补问，不动冻结标注。

要能复述：草稿不是最终事实；人工修改不能污染原文；同意/模型调用边界与版本确认各自负责什么。

## 10. 面试追问（5 题）

1. **为何不是一个 LLM 输出完整简历？** 解析只提字段，工程逻辑先固定来源与结构；优化建议需要独立核验与接受流程。
2. **模型有真实引用是否就能认定掌握某技能？** 不一定；引用校验确认来源，本步仍需人工核对，未来语义支持不能由相似度或引用存在替代。
3. **无姓名 PDF/DOCX 怎么处理？** 保存不完整草稿并提问，用户补充后才满足完整文档合同；无文字 PDF 明确 needs_ocr。
4. **调用失败会不会无限烧钱？** 最多两次总调用，仅修复结构/引用；传输超时不自动重试，未知计费与持久幂等仍是后续问题。
5. **当前真的是多 Agent + PG/Redis 完整产品吗？** 不是；此入口接解析与本地版本库，旧运行时/队列真实存在但尚未为新产品统一适配。
