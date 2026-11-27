# Job Agent 完整源码与全过程学习资料总包

汇总日期：2026-10-22。请先解压压缩包，再用 Markdown 阅读器打开本文件。

本包以当前工作区最新公开源码为准，汇总早期源码审计、M1–M3C 产品升级、V3 F0–F7 实施、技术选型、测试、实验、运行截图和面试资料。历史报告保留当时的范围与失败，当前状态以 [最终交付](FINAL_HANDOVER.md) 和 [功能验收矩阵](FEATURE_MATRIX.md) 为准。

## 包内内容

| 位置 | 内容与用途 |
|---|---|
| `src/`、`fit_verdict_engine/` | 当前 Python 源码，包括新 React 产品后端与保留的独立旧模块 |
| `frontend/src/`、`frontend/dist/` | React 源码与已构建静态文件 |
| `tests/`、`scripts/`、`pyproject.toml` | 测试、冻结/诊断样本、演示及评测脚本、依赖配置 |
| [全过程学习报告](docs/learning/OPTIMIZATION_JOURNEY.md) | 按阶段解释遇到的问题、方案、收益、代价和证据 |
| [阶段报告导航](docs/devlog/INDEX.md) | M1、M2、M2A、M3、M3B、M3C 和 F0–F7 的原始报告 |
| `docs/architecture/`、`docs/evaluation/` | API、数据模型、协作交接、代码索引、实验协议及原始结果 |
| `docs/demo/` | 部署步骤、连续演示脚本、公开/合成资料、截图及导出 PDF |
| [源码面试指南](docs/INTERVIEW_SOURCE_GUIDE.md)、[简历表述](docs/resume_notes.md) | 真实调用链、源码定位、可用能力与指标边界 |
| `historical_reports/` | 两份此前交付的学习包原件，保留阶段快照，勿用它们覆盖最新源码 |
| `delivery_evidence/` | 最终回归原始日志/JUnit、前端构建记录、汇总来源索引 |
| `DELIVERY_MANIFEST.json` | 本包每个文件的 SHA-256 和来源 |

此前公开学习包中、最新源码白名单未包含的历史日志、截图、差异和性能表，也按原相对路径补入本包；若路径已有当前文件，优先保留当前版本。历史原件仍可在 `historical_reports/` 查阅。

## 建议阅读顺序

1. 先读 [全过程学习报告](docs/learning/OPTIMIZATION_JOURNEY.md)，建立整个升级过程的地图。
2. 按 [部署说明](docs/demo/DEPLOYMENT.md) 和 [演示脚本](docs/demo/DEMO_SCRIPT.md) 操作产品；服务需要自行启动，旧端口链接不代表当前仍在运行。
3. 阅读 [端到端调用链](docs/learning/01_END_TO_END.md)，对照代码理解一个请求。
4. 分别学习 [多 Agent](docs/learning/02_MULTI_AGENT.md)、[公共 RAG](docs/learning/03_PUBLIC_RAG.md)、[Code-aware RAG](docs/learning/04_CODE_AWARE_RAG.md)、[运行时](docs/learning/05_RELIABLE_RUNTIME.md) 和 [评测](docs/learning/06_EVALUATION.md)。
5. 回看相应阶段报告中的备选方案、失败案例与真实验证，最后用 [32 个面试问答](docs/learning/INTERVIEW_QA.md) 自测。

## 验证边界与隐私

最近一次工程全量回归为 **855 通过 / 2 失败 / 50 跳过**，前端 **13 通过**、构建通过；这是此前 F7 的实际结果，本次汇总没有重跑或改写该成绩。两个失败依赖 Redis；50 跳过中 34 个受 PostgreSQL 环境限制，16 个受模型、Embedding 路径或显式启用条件限制。

当前 Demo 已验证本地规则/替身机制和公开/合成资料流程，真实模型质量、真实向量/Reranker、扫描 OCR、产品 PG/Redis 集成、Docker/公网生产部署仍有未验证或阻塞项。旧 R12 指标不转用于 V3。详情见 FINAL_HANDOVER 和 evaluation/RESULTS。

本次仅整理交付和文档，没有新增业务功能。源码、前端及字体与此前验证包逐文件一致；总包核验 CRC、清单哈希、关键文件与冻结样本。排除真实 Key、私人简历/JD、运行数据库/附件、Git 历史、虚拟环境、node_modules 和模型权重；这些应按部署说明在本地重建。包内公开演示口令仅用于合成资料。

中断后从 [继续开发手册](docs/CONTINUE_DEVELOPMENT.md) 恢复，不从旧 ZIP 覆盖工作区。
