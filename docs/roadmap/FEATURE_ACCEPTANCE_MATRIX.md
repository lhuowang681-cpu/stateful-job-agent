# V3 功能验收矩阵（由 Codex 在实际工作区持续更新）

当前动态权威矩阵已建于仓库根目录[FEATURE_MATRIX.md](../../FEATURE_MATRIX.md)。本页下表保留用户原始最低验收模板，不能据其NOT_STARTED反推已通过阶段不存在；最终逐项证据持续更新根目录矩阵。

状态：NOT_STARTED / IN_PROGRESS / CODE_PRESENT / WIRED_TO_UI / MOCK_TESTED / LIVE_TESTED / E2E_VERIFIED / BLOCKED / NOT_APPLICABLE。每项写 Git HEAD、测试证据与可复现命令；不允许凭代码文件存在标记 E2E。

| 编号 | 功能 | 用户可见场景 | 最低验证 | 当前状态 | 证据路径 |
|---|---|---|---|---|---|
| F1-01 | PDF/DOCX 解析与人工核对 | 上传简历生成结构化内容 | 合成多格式+人工纠错 | NOT_STARTED | |
| F1-02 | JD 原子要求抽取 | 输入JD拆解要求 | 原文span准确性用例 | NOT_STARTED | |
| F1-03 | Writer/Reviewer 改写审批 | 拒绝无证据经历 | 退回修订+批准/拒绝 | NOT_STARTED | |
| F1-04 | 模板 PDF | 预览/下载中文PDF | 文件版本一致+可复制文字 | NOT_STARTED | |
| F2-01 | 岗位与历史 | 保存多次面试/简历版本 | 刷新/重启/多租户测试 | NOT_STARTED | |
| F2-02 | 项目仓库导入 | ZIP/GitHub/文档 | 限制与安全输入测试 | NOT_STARTED | |
| F3-01 | 公共知识检索 | 题库/官方文档来源引用 | 召回标注与可查来源 | NOT_STARTED | |
| F3-02 | 私有代码索引 | 语法分块/文件符号关系 | 准确行号/commit测试 | NOT_STARTED | |
| F3-03 | Code-aware 检索 | 回答跨文件代码问题 | gold符号与证据完整率 | NOT_STARTED | |
| F4-01 | Agent Handoff/Tool Calling | 面试动态检索并追问 | 脱敏轨迹+预算+终止 | NOT_STARTED | |
| F4-02 | 项目深挖面试 | 代码依据提问/评价 | 错误事实/引用边界测试 | NOT_STARTED | |
| F4-03 | 薄弱项复习 | 训练复盘后生成专项练习 | 可引用来源+历史关联 | NOT_STARTED | |
| F5-01 | 异步任务/状态恢复 | 重启后可继续 | 故障注入、幂等 | NOT_STARTED | |
| F5-02 | 隐私/安全 | 源码不泄漏/仓库不执行 | owner/ZIP/SSRF/注入测试 | NOT_STARTED | |
| F6-01 | RAG 实验 | Flat vs Code-aware 等 | 冻结集、Recall@K、成本 | NOT_STARTED | |
| F6-02 | Agent 实验 | Single vs Sequential vs Collaborative | 同口径质量/时延/费用 | NOT_STARTED | |
| F7-01 | 完整浏览器 Demo | 连续完成所有 P0 操作 | 合成样本 E2E 录屏/截图 | NOT_STARTED | |
| F7-02 | 部署与学习交付 | 新环境启动、面试学习 | 启动命令、核心路径可核 | NOT_STARTED | |
