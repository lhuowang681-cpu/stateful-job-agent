# PHASE-03 · JD 匹配与受限排序（M3 首个闭环）

- 日期：2026-10-20。状态：本地产品闭环已验证；可选模型适配经替身验证，真实质量未验收；自由改写尚未实现。
- Git 起点：main / 067bfc7d63408e1e6b0ab6c227e863bd08a5857a；[起点快照](evidence/m3-start.json)。既存未提交变更保留。
- Git 终点：工作区增量，无提交/推送；差异、源码 hashes 和环境见 [verification](evidence/m3-verification.json)。
- 范围：不引入新框架、RAG、队列或数据库；保护旧 Evidence v2 与冻结评测。

## 1. 业务目标与验收标准

选已保存简历版本→输入 JD→逐项查看对应原文/线索/限制/缺口→保存分析快照→逐条接受/拒绝已有条目排序建议→生成未确认新版。
验收要求：JD 不能进个人证据；自述不升级；只使用所选版本、忽略已删字段；变动不覆盖旧分析；接受原子化、幂等、防旧版本覆盖。
这是新工作台的首个 JD 闭环，不代表自由文本优化、补充 C2/C3 材料、岗位投递/PDF/完整 Agent 工作流已全部接通。

## 2. 原有问题和基线

此前 React 已能 PDF/DOCX 导入、自动填字段、编辑版本，但没有 JD 入口；旧证据链独立运行。
直接把原始简历全文传给旧 pipeline 会重新引入用户已删除的内容，也不能准确指向当前版本。
阶段前相关回归实跑 **174/0/0**。旧模型指标 93.07%/97.30% 不是本轮结果，不沿用成新产品成绩。
新需求没有可比的真实模型实验，因此不报告“匹配质量提升率”。

## 3. 技术方案及取舍

- 本地模式：按 JD 条目和已知术语定位事实，明确为预检查，不是语义拆解或证据支持；缺口不代表没有能力。
- 可选模型：复用 RequirementAnalyzer/EvidenceMappingService、等级政策、FitAssessmentPolicy 和 EvidenceProjectionService；不改旧语义。
- 版本适配：排除 personal 栏目，将其余当前版本事实作为独立 C1 来源；JD 单独保存。source_id、hash、quote、offset 均验证。
- 来源视图：VersionSourceStore 从 SQLite 版本/JD 重建只读目录，复用既有 SourceQuoteResolver/validate_span；snapshot_path 为虚拟定位符，未写临时文件或交给旧文件仓库。
- 修改建议：只将相关项目/实习/技能条目置顶，服务器生成并保存 proposal；接受时校验事实清单完全一致，再调用已有追加版本逻辑。
- 总预算：两步合计最多 4 次 provider 调用；传输异常立即停止，不依赖旧节点自动重试行为；只发送经历字段，正文中的个人信息仍需用户检查。
- 请求持久化：owner+request_key 唯一预留，完成/失败/running 状态落 SQLite；相同请求键不会重复执行模型。

备选一：强行直接复用文件型 EvidenceV2Pipeline，会需要持久化文件与 SQLite 双份管理并解决删除/一致性；本轮复用其内核组件，不伪装调用了原 pipeline。
备选二：放宽 C1 让新简历自述直接进入生成投影；这会降低原保证，不采用。
备选三：立即让模型自由改写；引用只证明来源，不自动证明新句子语义，本轮选择事实不变的排序闭环。自由改写需要独立设计、校验和真实质量验收。
代价：暂无跨进程 Worker 恢复；异常退出可能遗留 running，需要人工检查，系统不自动再调用模型。

## 4. 实际调用链与代码地图

`MatchingPanel.analyze → POST /resumes/{id}/matches → MatchRepository.begin → get_version/来源校验 → WorkbenchMatcher.analyze → 本地预检查或既有要求/映射内核 → validate_bundle → MatchRepository.complete → MatchView → React`。
`MatchingPanel.decide → /matches/{id}/proposals/{id}/decision → MatchRepository.decide → 检查父版本/已决策 → 重排/事实清单比较 → SqliteResumeRepository._append → 未确认新版`。

| 顺序 | 源码锚点 | 学习重点 |
|---|---|---|
| 1 | `frontend/src/MatchingPanel.jsx::MatchingPanel` | 输入、结果、历史、接受/拒绝 |
| 2 | `src/job_agent/resume_workspace/match_api.py::install_matching_routes` | 身份、逐次同意、错误与调用 |
| 3 | `src/job_agent/resume_workspace/match_repository.py::MatchRepository.begin` | 持久请求键和版本快照 |
| 4 | `src/job_agent/resume_workspace/matching.py::VersionSourceStore` | 版本事实与原始来源的对应 |
| 5 | `src/job_agent/resume_workspace/matching.py::WorkbenchMatcher.analyze` | 两种模式、复用内核、预算 |
| 6 | `src/job_agent/resume_workspace/matching.py::validate_bundle` | JD/C1/引用与投影边界 |
| 7 | `src/job_agent/resume_workspace/match_repository.py::MatchRepository.decide` | 事务、并发、幂等和只排序 |
| 8 | `tests/test_resume_matching.py::test_total_model_budget_stops_schema_repair_across_both_nodes` | 实际触发 4 次调用并阻止第 5 次 |

## 5. 功能开发轨迹

### A：固定版本的证据分析
- 场景：新产品缺少 JD 分析，原件不等于当前编辑后的版本。
- 采用：所选版本非 personal 字段→独立 C1 来源，JD 独立；复用已有证据内核。
- 备选：原件全文进旧 pipeline，会重新引入删除内容，不采用。
- 锚点：上表 VersionSourceStore、WorkbenchMatcher.analyze；输入版本/JD，输出 bundle/MatchView。
- 数据：owner/版本/hash 校验→预留请求→预检查或模型→逐字引用/等级校验→持久化快照。
- 验证：新增首轮 21 通过/1 失败（测试写错方法名 append_version），核对真实 save_version 修正，不删断言；扩充后 27 项通过。
- 边界：本地不作语义判断，模型仅替身验收；不引入向量检索或新 AgentLoop。

### B：事实不变的建议接受/拒绝
- 场景：相关经历靠后，希望调整重点，不能因此新增未经核实的经历。
- 采用：仅将既有条目置顶，接受生成新版本、拒绝只记决策；事实清单和来源必须相同。
- 备选：自由生成优化文字需要独立语义与事实验证，本轮不作为已完成能力。
- 锚点：上表 MatchRepository.decide；输入服务器 proposal ID/父版本/核对动作，输出新版和分析视图。
- 数据：事务检查当前 head→重排→对比全部 fact JSON→既有 _append→未确认新版。
- 验证：重复/并发接受只生成一个版本、拒绝不生成、人工编辑后旧建议失效，自动与浏览器/HTTP 验证通过。
- 边界：仅排序不是自由改写，用户仍需最终确认。

### C：产品界面与历史恢复
- 场景：用户需要看具体 JD 引用、个人来源、限制和历史，不能只给一个不透明分数。
- 采用：逐条显示线索，原文高亮，历史快照与接受/拒绝状态；不展示录用概率。
- 备选：只显示总匹配率无法表达 C1/缺失/冲突，不采用。
- 锚点：MatchingPanel（上表）；MatchRepository.get/list（同文件），返回只属于当前身份的数据。
- 数据：分析结果→引用源 API→高亮；接受→第二版；刷新→历史快照重载。
- 验证：合成浏览器实际输入 JD、查看原文、拒绝技能建议、接受项目建议成第二版；15 项真实 HTTP 检查全部通过。
- 边界：本机临时合成 Demo，未验收公网身份系统/真实模型/生产队列。

## 6. 可复现验证（实际执行）

安装 `[dev,workbench]`，在项目根目录执行。实际 Windows 环境将 TEMP/TMP 和 pytest basetemp 指向工作区，使用允许本机 API 通信的测试环境。

```powershell
python -m pytest -q tests/test_resume_import.py tests/test_resume_workspace.py tests/test_resume_pdf_autofill.py tests/test_resume_matching.py tests/test_source_audit_regressions.py tests/test_career_store.py tests/test_application_assistant_evaluation.py tests/test_backend_service.py tests/test_evidence_source_store.py tests/test_evidence_mapping_v2.py tests/test_evidence_projections.py tests/test_evidence_requirement_analyzer.py tests/test_knowledge_ingestion.py
cd frontend
node --test src/model.test.js
node node_modules/vite/bin/vite.js build
cd ..
python scripts/demo_resume_workbench.py --port 8014
```

最终相关后端 **201 通过/0 失败/0 跳过**，其中新增 27；前端 **9/0/0**，构建通过。
浏览器验证真实页面；[15 项独立本机 HTTP 检查](evidence/m3-live-http.json) 不计入 pytest 数量。
完整命令/环境/源码 hashes/JUnit 见 [m3-verification](evidence/m3-verification.json)。截图：[逐项线索](evidence/m3-match.png)、[接受与拒绝](evidence/m3-decisions.png)、[新版项目顺序](evidence/m3-version.png)。
旧端口 8013 可能仍跑旧后端；本轮最新示例为 8014。正式脚本使用临时 SQLite/公开演示口令且不读取私有模型配置。
未运行：全仓库/生产 PG/Redis/Worker、真实模型质量/费用、真实私人材料、RAG/OCR/PDF/自由改写集成。

## 7. 效果与实验数据

| 范围 | 基线 | 本次 | 含义 |
|---|---:|---:|---|
| 同范围既有相关回归 | 174/0/0 | 纳入 201/0/0 | 新增 27 项保护，不是质量提升率 |
| 前端逻辑 | 6/0/0 | 9/0/0 | 标签语义边界，非完整组件自动覆盖率 |
| 合成产品操作 | 无新 UI 的 JD 入口 | 输入→快照→拒绝/接受→第二版 | 浏览器与 15 项独立 HTTP 验证 |
| 真实模型语义质量 | 未验收 | 未验收 | 不借用旧 R12 数据 |

模型替身证明的是请求合同、引用拒绝、C1 限制、预算和失败行为；不证明真实模型判断能力。
负面结果保留：首轮 1 个测试错误方法名；无删测试/降指标/改冻结标签。源评测文件 hash 对照见 verification。

## 8. 风险、技术债、下一步

- 本地有限术语/否定规则会漏同义词或误标范围限制，只作线索，不能作语义判定。
- 单事实 C1 来源保持版本准确性，也限制模型跨多事实综合理解；当前不支持补充独立 C2/C3 证明。
- 自由改写、数字/时间线/生成新句的语义校验尚未实现，不把排序称为完整 AI 简历优化。
- 请求内执行、30 秒 provider 超时与前端等待时限可能不一致；预留键防同请求重发，异常退出的 running 无自动恢复/费用清算，人工检查后显式新建。
- 排除 personal 栏目不是全正文 PII 脱敏；在线前仍需检查经历文本。真实模型费用未知保持 null。
- 后续先做真实模型与代表性合成/授权样例验收，完善受限表达建议，再按路线进入 PDF；不自动宣称生产服务已统一。

## 9. 事后学习路线（约 50 分钟）

1. 10 分钟：演示输入一个有线索/一个带否定/一个无材料的要求，接受项目排序、拒绝技能排序。
2. 10 分钟：MatchingPanel→match_api→MatchRepository.begin，理解请求键、版本快照和同意范围。
3. 10 分钟：VersionSourceStore→旧 RequirementAnalyzer/EvidenceMappingService，理解复用的是内核组件而非整条旧 pipeline。
4. 10 分钟：validate_bundle→EvidenceProjectionService，解释为什么 C1 能帮助定位但不能生成新事实。
5. 10 分钟：MatchRepository.decide 和并发/预算测试，解释 transaction/head/事实清单/幂等。

要能复述：本地词面与模型语义分开；文档来源验证与现实真实性分开；建议操作与历史版本绑定。

## 10. 面试追问（5 题）

1. Q：为什么不用原始简历全文匹配？A：编辑后删除的内容不应重入证据池；本次只用所选版本事实，并保留到原件的 offset/hash。
2. Q：用户已确认，为什么还标 C1？A：确认是自述确认，不是独立实验或生产证明。既有投影仍排除 C1，不能为改善展示而降低等级。
3. Q：本地显示线索代表支持吗？A：不代表。只按已知术语查找，未做语义核验；无命中也不代表没能力。在线复用旧语义节点，仍要核对。
4. Q：如何避免重试反复计费？A：预留 owner/request_key 和输入 hash；running/失败键不重新执行，完成键返回原结果；provider 异常停止，总上限 4。异常退出和费用未知的情况需人工检查，不承诺跨外部模型 exactly-once。
5. Q：接受排序怎么保证不编经历？A：服务器保存的 proposal 只选择已有条目，事务验证当前父版本，再比较全部 fact JSON 一致，最后追加未确认新版。重试返回同一版本，外部人工编辑会使旧建议失效。
