# 既有实现学习规格与独立聊天交接

- 日期：2026-10-22。
- 状态：文档补建，静态核验结果见下方机器记录；业务运行结果未重测。
- Git起点/终点：本目录为ZIP解压源，无`.git`；未创建提交或推送，不把来源SHA当本地HEAD。
- 范围：学习文档、导航、交接与静态核验工具；业务源码未改。

## 1 业务目标和验收

用户要按详细Spec理解既有项目，掌握流程、设计理由、取舍、故障和验证，随后两个项目分开聊天。依据用户补充，参考两份GitHub项目的详细组织方式，不能只有大纲。

验收为：现状说明可定位源码；6章18任务每项有场景、文件、步骤、失败、产物及追问；区分当前/历史/教学/未来；可独立交接；新文档链接和源码锚点可核对。

## 2 原问题与基线

源码包已经有M/F阶段历史报告，但用户难以把它们组织为逐步学习链条。原学习偏向通读源码，不符合当前优先级。功能也存在多条历史入口，易把旧PG/Redis和新SQLite工作台混为一体。

参考模式：`https://github.com/jerry-ai-dev/MODULAR-RAG-MCP-SERVER`的Dev_SPEC按阶段和任务注明目标、文件/函数、验收与测试；`https://github.com/jerry-ai-dev/smart-appointment-ai-agent`提供场景/架构和项目理解准备的参考。本轮吸收粒度与任务结构，结论按本项目源码编写。

## 3 方案与取舍

采用“当前实现总Spec＋详细任务章节＋演进概览＋聊天交接”。替代方案是只有一个长README，缺少逐任务完成标准；或伪造从零开发史，会混淆真实贡献。

任务顺序是教学重建。设计理由引用既有决策，补充解释与假设案例明确标注。未来新增功能先写开发Spec，记录真实实现、实验和失败，不倒造旧提交。

## 4 代码地图

| 主线 | 已核对入口 | 责任 |
|---|---|---|
| 上传与版本 | `src/job_agent/resume_workspace/api.py::create_resume_app` | 入口组装与业务路由 |
| 状态与版本 | `src/job_agent/resume_workspace/repository.py::SqliteResumeRepository` | 来源、不可变版本、确认与编辑 |
| 协作 | `src/job_agent/resume_workspace/rewrite.py::RewriteService` | 有界Writer/Reviewer及采纳 |
| 检索 | `src/job_agent/resume_workspace/code_rag.py::CodeRAGService` | 快照索引、查询与引用 |
| 面试 | `src/job_agent/resume_workspace/interview_collaboration.py::InterviewEngine` | 评价反馈、动作与检查点 |
| 后台 | `src/job_agent/resume_workspace/tasks.py::TaskRepository` | 领取、租约、发布校验 |

真实业务链：入口→来源/版本→匹配/改写→人工采纳；项目快照→索引任务→检索/读取工具→面试评价反馈。旧后端另有PG/Outbox/Redis路径。

## 5 实际文档轨迹

建立总Spec，按流程解释合同、局限与历史证据；建立18任务，重点放RAG、协作、版本与异步可靠性；外围PDF只要求边界。添加独立聊天交接，避免两个聊天同时修改同目录。

另为第二项目建立独立参考目录、来源manifest和学习Spec，但本仓库职责仍只覆盖Job Agent。参考源码保持原字节，不执行企业数据入口。

## 6 可复现静态核验

运行目录为父工作区`C:/Users/1/Desktop/就业agent`，使用Python标准库，不导入项目模块、不读取模型配置。

```powershell
& 'C:\Users\1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 资料阅读记录/verify_learning_specs.py
```

实际结果与计数见[学习Spec核验](../../../资料阅读记录/学习Spec核验_2026-10-22.json)。核对新文档链接、Python路径与符号、第二项目96参考文件hash和60Python语法树，并比较Job源码文件与输入ZIP的字节。

仅静态检查不证明业务测试、真实模型或PG/Redis生产环境通过。先前单独函数探针只证明hard_constraints对特定中文新增成果的漏检；不是端到端通过/失败率。

## 7 前后变化与效果

前：存在源码/阶段记录，但缺少统一现状教学主线。后：总Spec、6章18任务及交接可导航。没有用掌握率、面试成功率或模型质量数字衡量本轮文档效果，尚无此类有效对照。

## 8 风险与下一步

用户随后明确边优化边学，并要求每次优化同步更迭续写Spec。已补[当前总Spec](../tech-specs/CURRENT_SPEC.md)、[变更记录](../tech-specs/SPEC_CHANGELOG.md)和[增量模板](../tech-specs/INCREMENT_SPEC_TEMPLATE.md)，将Spec与验证证据同步列入阶段完成条件。旧内容穿插回看，不作为开发前置等待；本次仍无业务代码变化。

任务仅是待学习清单，没有替用户声明已掌握。现有Dense/RRF接口与真实Embedding接入验证不同；多角色存在与协作收益不同；SQLite恢复与PG/Redis生产接入不同。

后续先按任务学习，并为RAG接入/重排/引用支持度和协作对照等写真实增量Spec。Git仓库应从真实基线建立，不倒签或伪造开发历史。

## 9 30～60分钟首次学习

先看总Spec第2—4节，再做J01：画上传到来源/草稿的调用图，标出读文件、模型、写库三类边界。用合成材料讲正常与缺字段场景；无需先运行服务或照抄全部源码。

## 10 面试追问与回答要点

1. 为什么不直接让LLM生成终版简历？来源、提议、确认与版本责任不同，避免错误覆盖和事实扩大。
2. 有引用就可信吗？结构合法和语义支持分开，C1自述不自动升级为独立事实。
3. 多Agent有什么收益？先讲反馈和约束，再用公平质量/成本对照证明，不按角色数量判断。
4. 项目有没有数据库和RAG？已有SQLite及BM25/符号/可配置Dense/RRF，重点是准确说明当前默认接入与未验部分。
5. 这些是当时的开发过程吗？当前Spec是基于源码的教学重建，原历史按真实报告引用，自己的后续增量单独记录。
