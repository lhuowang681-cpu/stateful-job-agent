# FINAL-F1 — 版本化PDF与有证据的局部编辑

- 日期：2026-10-20；main / 067bfc7d63408e1e6b0ab6c227e863bd08a5857a，沿用dirty基线，不创建提交。
- 状态：DONE（本地合成产品闭环）；规则LOCAL_REAL，LLM LIVE_PENDING。

## 1. 问题与基线

原产品只能摘录摘要，不能生成PDF，也不能把语义改写诚实地保留来源。F0相关291/0/0、前端13/0/0。全量诊断含新PDF8例为735/2/50，失败缺Redis，跳过34项PG与16项模型条件；不是V3全通过。

## 2. 方案和备选

保留已有原文slice/hash内核。局部改写使用独立提案，批准后复用人工编辑事务生成新自述来源，保存原文到新表述的血缘，而非把改写当原文。独立Reviewer+Python硬门禁+人工确认三道不同判断，最多三稿/六次角色调用；未决模型不重放。
ReportLab生成两模板，Noto Sans SC开放字体子集嵌入。备选HTML/Playwright需要额外浏览器服务，目前确定性文档渲染足够。首次CID字体依赖阅读器，虽中文抽取/Poppler可用，仍改为嵌入字体改善可移植性。
浏览器实测iframe无PDF插件导致空白，故采用本地PDF.js Worker渲染真正PDF字节；不是用HTML伪装PDF预览。代价：新增按需载入430KB前端模块与1.26MB Worker、17.8MB可再分发字体。

## 3. 核心源码地图与调用链

1. `frontend/src/MatchingPanel.jsx::MatchingPanel` → `/jd/extract` → `resume_workspace/api.py::extract_jd` → `ingestion.py::extract_upload`：岗位文件只抽文字，不变成个人事实。
2. `frontend/src/RewritePanel.jsx::RewritePanel` → `rewrite.py::RewriteService.start` → LangGraph writer/reviewer → `hard_constraints` → 持久提案/反馈。
3. `RewriteService.decide` → `SqliteResumeRepository._apply_edits/_append`：同事务验证head/提案hash/审批，生成C1新版及独立user_statement；原版完整保留。
4. `frontend/src/PDFPanel.jsx::PDFPanel` → `pdf_export.py::PDFRepository.export` → `render_pdf` → rw_pdf_exports → download → `PDFPreview.jsx::PDFPreview`：确认版哈希绑定、文件哈希、两模板、本机Worker画布。
5. `evidence_reference.py::EvidenceReference`：统一引用边界；不能根据source存在直接supported。

以上Python默认前缀src/job_agent/resume_workspace。旧Evidence内核/摘录协作接口不改。

## 4. 实际实验与证据

- `python -m pytest -q tests/test_v3_pdf.py tests/test_v3_rewrite.py ...`相关155/0/0，work/v3-f1-related.xml/log。首次新增PDF8/0/0。
- 嵌入Noto后 `python -m pytest -q tests/test_v3_pdf.py tests/test_v3_rewrite.py`=18/0/0；work/v3-f1-font.xml/log。
- 前端`npm test`13/0/0、`npm run build`通过；work/v3-f1-frontend-test.log、v3-f1-build.log。
- 同一长文档20项目/160描述行/长链接，两模板真实文件：docs/demo/artifacts/synthetic-resume-{classic,compact}.pdf；classic6页，compact5页。pypdf中文抽取，Poppler逐页渲染，all-pages.png已逐页目视检查无溢出/缺字。
- 浏览器8017实际导入→JD→局部改写→用户审批→确认→导出成功，但iframe预览空白，已保留失败原因并修复；8018复验进行中。
- 字体官方来源/固定commit/哈希/许可：src/job_agent/resume_workspace/assets/FONT_SOURCE.json、OFL.txt。技术参考：[ReportLab字体](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/)、[Google Fonts Noto](https://github.com/google/fonts/tree/main/ofl/notosanssc)。
- 最终原291+新增19项相关回归：`work/v3-f1-final.xml/log`，310通过/0失败/0跳过，24.96秒。覆盖真实Provider接口的结构化替身、无姓名透传、调用上限、用量汇总；不是实际模型质量。
- 8018连续浏览器实操完成导入/核对→保存v1→JD预检查→Writer/Reviewer局部改写→人工审批v2→确认→classic及compact PDF.js实际画布预览，历史两文件同一确认哈希ee5e37de9af1…；截图 `docs/demo/artifacts/f1-browser-pdf.png`。未用脚本绕过审批或用假页面替代PDF。

## 5. 前后比较

此前无PDF/局部改写提案；现在有可测试的产品路径。规则改写只做少量受限转换，不是LLM质量实验。未调用真实模型，未宣称相关性、幻觉率或求职效果提升。

## 6. 安全、失败与限制

新增数字/英文技术实体、显式否定/范围丢失、职责扩大由Python拒绝；中文复杂语义不保证仅靠词表正确，在线独立Reviewer和用户核对仍必要，未独立核实。
源HTML标记转义，不加载外部图片/脚本；PDF字体随包且不发送资料。PDF/改写均owner校验，删除简历级联、缓存hash验证；同键不重复模型调用或业务新版本。未知模型状态返回unknown、不自动再执行。
真实模型和生产PG/Redis验证未运行。OCR仍未实现，此处不宣称扫描PDF可用。

## 7. 45分钟学习路线

5分钟产品面板 → 15分钟rewrite.start图与硬门禁 → 10分钟decide/_apply_edits血缘事务 → 10分钟PDFRepository/render_pdf → 5分钟边界测试。

## 8. 面试问答

1. 改写为什么不能保留原quote字段？原文相等约束会失真，批准后应是新自述，原证据另存血缘。
2. Reviewer说accept就能发布吗？不能，Python覆盖硬冲突，仍需用户逐项接受且新版重新确认。
3. 为什么不用LLM生成PDF？模型负责结构/措辞，排版是确定性渲染，更易绑定版本与回归。
4. 确认是否代表事实真实？仅用户自述确认，C1/not_verified不升级。
5. 为什么不用iframe？真实浏览器没有PDF插件，实际空白；页面内PDF.js让预览可验证且不依赖插件。
6. 模型超时能直接重试吗？可能已计费或已成功，保留unknown与调用保留位，不自动重复。
7. 来源哈希一致能证明语义正确吗？只能证明所引文字没变，语义支持是另一个评审维度。

## 9. 下一阶段

8018预览及310回归已通过，进入F2长期岗位/项目权限，不增加新消息中间件。F3解析器依赖已从公开PyPI安装，尚未宣称索引实现。
