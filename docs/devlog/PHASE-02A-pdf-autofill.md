# PHASE-02A · 普通 PDF 简历自动填表

- 日期：2026-10-20。状态：本地增量已验证，真实简历质量尚无结论。
- Git 起点：main / 067bfc7d63408e1e6b0ab6c227e863bd08a5857a；既存未提交状态见 [开始快照](evidence/m2a-start.json)。
- Git 终点：工作区增量，未提交/推送；见 [验证记录](evidence/m2a-verification.json) 的 diff_stat/source hashes。
- 环境：Windows、Python 3.12、本地 pypdf、SQLite、React；模型调用为 0。

## 1. 业务目标与验收标准

上传文字版 PDF 后，自动填写姓名、联系方式、教育、工作/实习、项目和技能；主要任务是核对，不要求重打已有内容。
使用合成数据验证：真实 PDF 字节上传 → 文本 → 结构草稿 → 原文核对 → 无 edits 保存版本。
字段仍须逐字引用规范化抽取文本，经过 owner/kind/hash/offset 校验；保存与最终确认分离。
这是 M2 导入体验的补强，M3 JD 匹配尚未开始。

## 2. 原有问题和基线

M2 已有文字 PDF/DOCX 抽取和可选 LLM 接口；缺口是本地结构解析依赖标签/管道。
无标签姓名、邮箱/电话容易漏识别，空格分栏不拆字段，普通正文可能一行变成一个项目。
原版 M2 压缩包在独立工作副本运行原有工作台测试：72 通过，0 失败，0 跳过。
同输入对照见 [合成样例记录](evidence/m2a-synthetic-comparison.json)：25 个预先指定字段旧规则匹配 3 个、新规则匹配 25 个。
这仅是一份合成回归样例，不是代表性准确率实验。

## 3. 技术方案及取舍

复用 PDF 抽取器、DraftDocument/FieldCandidate、来源校验和人工核对；不迁移库、不变 API 模式名。
本地解析保留 Line 起点；分段、时间、学校、学位、角色只是定位规则，不先改写原文。
身份和联系方式限定在个人信息区域，多候选不猜；技能否定整句保留，项目技术栈不转成个人技能。

| 方案 | 好处 | 成本/为何本轮不选 |
|---|---|---|
| 本地保守结构解析（采用） | 无外发/费用，可直接复用现有来源校验 | 模板覆盖有限，仍需核对 |
| 强制在线模型 | 更灵活地适配自由表述 | 隐私发送、配置、费用、真实质量待验；保留已有可选接口 |
| OCR/版面模型统一解析 | 可处理扫描和复杂栏 | 依赖、推理、图片和独立数据验收；本次不宣称接入 |
| 继续要求固定标签 | 成本最低 | 不能满足导入后自动建档的目标 |

## 4. 实际调用链与代码地图

React 选择 PDF → App.parse 上传 `/api/v2/imports` → extract_upload → load_source/pypdf → save_upload（原件与规范化来源）。
随后 `/sources/{id}/parse` → ResumeParser.parse → extract_local/LocalExtractor → materialize → save_draft → 自动填表。
用户核对 → `/drafts/{id}/accept` → accept_draft → 来源校验/事务/追加版本 → 未最终确认的新版本。
offset 指抽取文本的 Unicode 字符位置，不是 PDF 字节或视觉坐标。

| 顺序 | 文件::函数/类 | 输入→输出/学习重点 |
|---|---|---|
| 1 | `frontend/src/main.jsx::App.parse` | File/文字→上传/解析/表单 |
| 2 | `src/job_agent/resume_workspace/api.py::create_resume_app.import_file` | 流→UploadView，身份/大小/线程池 |
| 3 | `src/job_agent/resume_workspace/ingestion.py::extract_upload` | 原件→ExtractedSource，扫描/加密边界 |
| 4 | `src/job_agent/resume_workspace/local_extraction.py::LocalExtractor.extract` | 原文→候选和警告 |
| 5 | `src/job_agent/resume_workspace/local_extraction.py::LocalExtractor.entries` | 段落→标题/时间/描述归组 |
| 6 | `src/job_agent/resume_workspace/parsing.py::materialize` | 候选→逐字引用草稿 |
| 7 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository.accept_draft` | 核对草稿→新版本，来源/幂等/事务 |
| 8 | `tests/test_resume_pdf_autofill.py::test_real_pdf_bytes_to_draft_to_saved_version_without_manual_edits` | 合成 PDF→版本/原件 hash/跨用户隔离 |

## 5. 功能开发轨迹

### 功能 A：普通格式自动识别

- 场景：普通 PDF 无“姓名：”或固定管道，不应因模板不同重填。
- 采用：Line+offset、标题别名、联系方式唯一候选、日期/学位和描述归组；备选在线模型保留但不强制。
- 锚点：`src/job_agent/resume_workspace/local_extraction.py::LocalExtractor.personal`、`src/job_agent/resume_workspace/local_extraction.py::LocalExtractor.header`。
- 数据：抽取文本→path/exact_quote/start/end→materialize→草稿；无原文不造值。
- 失败：首轮编号规则截断日期 `2022.09`，3 项测试失败；限制编号范围后通过，未删断言。
- 验证：新增首轮 14 通过/3 失败；修复后工作台合并 89 通过；后续新增边界用例纳入最终 174。
- 限制：少数姓名、复杂栏、无标题结构可能漏识别，交给核对环节。

### 功能 B：上下文与歧义保护

- 场景：逐字抽到原文不等于放进哪个字段都正确。
- 采用：熟练度/否定整句保留；项目“技术栈”保留项目段；多个邮箱/电话留空并警告。
- 锚点：`src/job_agent/resume_workspace/local_extraction.py::LocalExtractor.extract`。
- 数据：上下文规则→候选/警告→来源校验→待核对表单，不改原件。
- 备选：一律按逗号拆技能，简洁但丢否定语义，因此不采用。
- 验证：技术栈子标题、否定、项目联系方式、缺失标题、多标签身份和歧义测试均纳入最终回归。
- 限制：保守规则不是完备语义理解，仍需核对分组和含义。

### 功能 C：自动填写反馈和真实 PDF 保存

- 场景：用户需要知道填了什么，并能直接核对保存。
- 采用：复用表单，建议简历名称，展示字段/经历数量与后端警告；模型逐次同意不变。
- 锚点：`frontend/src/model.js::extractionSummary`、`frontend/src/main.jsx::App.openDraft`。
- 数据：上传→解析→表单→原文高亮→无 edits 接受→第 1 版；保留独立最终确认。
- 备选：导入即确认，操作少但削弱核对边界，因此不采用。
- 验证：真实浏览器上传合成 PDF，显示 25 字段/1 教育/1 实习/2 项目，未补填即可保存；截图如下。
- 限制：本机合成 Demo，不是生产部署或真实模型端到端；扫描件未识别。

## 6. 可复现验证（实际执行）

安装 `[dev,workbench]`，项目根目录执行。Windows 沙箱曾无法建临时目录/阻塞本机通信；最终在允许本机通信的环境用工作区临时目录运行，失败/中断记录保留。

```powershell
python -m pytest -q tests/test_resume_import.py tests/test_resume_workspace.py tests/test_resume_pdf_autofill.py tests/test_source_audit_regressions.py tests/test_career_store.py tests/test_application_assistant_evaluation.py tests/test_backend_service.py tests/test_evidence_source_store.py tests/test_evidence_mapping_v2.py tests/test_evidence_projections.py tests/test_evidence_requirement_analyzer.py tests/test_knowledge_ingestion.py
cd frontend
node --test src/model.test.js
node node_modules/vite/bin/vite.js build
cd ..
python scripts/demo_resume_workbench.py --help
python scripts/demo_resume_workbench.py --port 0 # 预期退出 2
```

最终后端相关回归 **174 通过/0 失败/0 跳过**，其中本次新增 20；前端 **6 通过/0 失败/0 跳过**；Vite 构建成功。
完整命令和日志见 [m2a-verification.json](evidence/m2a-verification.json)。这是相关回归，未重新运行全仓库/真实 PG/Redis。
浏览器验证 PDF 上传→自动字段→原文高亮→无补填保存成功。
截图：[自动填写](evidence/m2a-autofill.png)、[项目与原文](evidence/m2a-projects.png)、[保存版本](evidence/m2a-saved.png)。
正式启动脚本另经 8 项真实本机 HTTP 检查，全部通过（不计入 174 个 pytest 用例）；见 [HTTP 记录](evidence/m2a-live-http.json) 和 [最新运行截图](evidence/m2a-live-saved.png)。首次受环境代理影响的探测在读取 capabilities 时返回非 JSON，未写入数据；直接连接 loopback 后完成检查。
复现演示：`python scripts/demo_resume_workbench.py --port 8013`，公开演示口令沿用 M2 脚本，限合成材料。
本轮浏览器验收使用同一个 build_demo_app 工厂、临时库、端口 8013；追加两项上下文用例由最终单元/接口测试验证。
真实模型/GPU/OCR/生产服务/新 JD 集成均未运行。

## 7. 效果与实验数据

| 范围 | 旧基线 | 本次 | 解释边界 |
|---|---:|---:|---|
| 同一合成样例 25 个预先指定字段逐项匹配 | 3/25 | 25/25 | 单样例回归，不代表真实准确率 |
| 既有工作台测试 | 72 通过 | 纳入最终 174 | 接口/来源/版本约束回归 |
| 前端辅助逻辑 | 历史 4 项 | 6 通过 | 辅助逻辑，不是全部 UI 自动覆盖率 |

比较输入是测试内合成文本，旧代码来自已交付 M2 包的独立副本；不改冻结数据或指标。
负面结果：编号规则曾截断年份，已修复；环境失败/中断与一次错误测试路径导致的未收集也记录保留。
复杂版式、扫描、真实模型质量没有有效实验，不能给出生产提升率。

## 8. 风险、技术债、下一步

无标签姓名为启发式；多栏、嵌入字体和图片需要独立版面/OCR 验收，不能承诺任意模板。
来源可追溯不证明现实经历真实性或字段分组正确，草稿核对保留。
新产品仍是本地 SQLite/请求内解析，未借此引入队列、ES、新 Agent。
完成后回到既定 M3 JD/证据适配路线；不把计划写成已接通。

## 9. 事后学习路线（约 45 分钟）

1. 5 分钟：导入合成 PDF，观察自动字段、缺失城市、原文依据。
2. 10 分钟：读 App.parse→import_file→extract_upload，区分“读文字”和“分结构”。
3. 10 分钟：读 LocalExtractor.personal/entries/header，理解覆盖边界。
4. 10 分钟：读 materialize/accept_draft，理解 offset/hash/owner 与人工核对。
5. 10 分钟：运行新测试，改成两个邮箱或把“技术栈”放入项目，观察为何不自动断言能力。

要能复述：抽取与结构解析是两层；可追溯不等于语义一定正确；自动填写减少录入，确认仍由用户完成。

## 10. 面试追问（5 题）

1. Q：已有 PDF 上传为何还要改？A：抽文字已存在，原本规则依赖标签/管道。本次补结构定位与自动填写反馈。
2. Q：为何不让 LLM 包办？A：已有可选通道但需逐次同意、限预算和原文验证；规则无外发、可测试，适合常见格式。未运行真实模型就不报模型成绩。
3. Q：如何保证没编经历？A：字段逐字对应 source_id/hash/start/end，保存复查 owner/kind；仍可能语义误分组，因此保留人工核对，不声称证明经历真实。
4. Q：项目有 Redis 为什么不直接写技能？A：技术上下文不必然证明个人掌握；项目技术栈留在项目，否定/熟练度句子不拆成肯定技能。
5. Q：能说准确率 100% 吗？A：不能。25/25 只是一份合成回归样例，真实模板数据、扫描/OCR 和真实模型质量尚无本轮验收。
