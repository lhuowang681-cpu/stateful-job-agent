# FINAL-F3 — 公共知识与Code-aware RAG

- 日期：2026-10-20，main/067bfc7，沿用dirty基线。
- 状态：LOCALLY_VERIFIED，真实模型/向量LIVE_PENDING。F3检索UI、公开/合成源码与面试复盘已接；F4进一步接动态项目工具。F2相关333/0/0为历史阶段基线，不转作当前全量。

## 1. 用户问题

固定题库不能围绕用户项目提出可引用追问；整仓库塞入上下文浪费且难定位实现。应将公共概念参考与私人项目实现区分，检索来源不推断用户作者/运行成绩。

## 2. 方案与取舍

先精确符号/路径，再复用BM25与可配置Embedding，复杂问题有界展开静态关系。Python AST、已安装Tree-sitter JS/TS；不能解析时明确文本降级，不假造调用图。SQL储存符号/边，保留不可变snapshot，暂不引入图数据库。Dense缺真实模型时返回不可用，不拿随机/哈希向量假装语义检索。

## 3. 功能轨迹与调用链

### 安全导入与固定版本
- 场景：GitHub源码只能读取，不能安装或执行；ZIP不能逃逸路径或读入密钥。
- `resume_workspace/github_import.py::PublicGitHubImporter.import_project`（均位于src/job_agent）只请求固定官方域名、验证公网DNS、不跟随重定向、不带凭据。分支先解析commit；完整SHA要求ZIP git archive comment严格相等。
- 真实失败：分支API403/remaining=0，不绕过权限；固定公开Starlette 0.46.2 commit `4a811767bcba6e933bf7a8b48edef5993ce8948e` 的匿名codeload下载成功。许可BSD-3-Clause，源和hash见docs/demo/assets/starlette-public-manifest.json，非用户本人贡献。
- 发现大PNG被文件读取上限误拒，`project_import.py`改为先检查总量/路径/类型，再跳过非文本资产，不解压无用图片；文本/总量炸弹仍拒绝。有对应回归，保留首次失败日志work/v3-f3-public-import.log。
- 备选直接git clone会多出进程/凭据/执行面，故不用；限制是8MB压缩/24MB展开，只面向小项目。

### 解析、检索与可校验引用
- `code_parser.py::parse_file/resolve_edges` 用Python AST和实际Tree-sitter JS/TS，提取符号与可消歧静态边；动态对象无法确定时不猜。
- `code_rag.py::CodeRAGService.build/search/get_symbol/find_references/read_code_range` 保存不可变快照派生索引，精确符号→BM25→最多2跳/8关联；真实向量未配置，dense拒绝、hybrid明确降级。
- `validate_reference` 校验owner/project/snapshot/path/hash/commit/行原文；调用关联不等于实际运行，源码有tests不等于已跑测试，支持标签强制needs_judgment。
- UI `frontend/src/ProjectsPanel.jsx` → `/api/v2/projects/{id}/search` → CodeRAGService → SQLite符号/分块/边 → 原文引用。实际浏览器Starlette run_in_threadpool返回定义与其他文件调用，截图docs/demo/artifacts/f3-code-search.png。
- 上游104文件、1693符号、2118分块、3733静态边、1948未解析引用，只是索引规模，不是准确率；不运行上游代码。

### 公共知识和复盘真实接通
- `public_seed.py::seed_entries` 提供10份原创技术整理+10题，CC0，保留官方参考URL/整理版本/许可。不是逐字镜像，不宣称官方审定。
- `public_knowledge.py::PublicKnowledgeRepository/Service` 不可变版本、去重、引用校验；题目公开DTO排除答案/别名/追问模板，私人rubric仅服务内部读取。POST检索避免把查询放访问日志URL。
- `KnowledgePanel.jsx` → POST `/api/v2/knowledge/search` → BM25/标签/可选向量；`interview_api.py::review`先完成与owner门禁，再对已答问题检索公共摘要；不改变旧面试评价标准。114项测试包含活动409、结束有资源、跨用户404。
- 备选每轮塞全部公共资料会扩大上下文和答案泄漏面，故按需取用；当前小语料BM25可能召回泛相关项，未做人工语义相关性标注，不能称教学效果已验证。浏览器截图f3-public-knowledge.png。

## 4. 验证计划

F0代码冻结集40题（20跨文件）哈希不改。先开发独立合成样例，测试引用owner/snapshot/hash/原文行号、调用边可解析性、删除/重建、GitHub URL/SSRF/超限/不执行。公开开源项目需固定commit与许可并记录实际导入，不虚构真人标注。

## 5. 前后比较

已运行 `python scripts/eval_v3_code.py`，40题×5方法，固定hash未改。原始每题引用、命中、耗时和汇总在docs/evaluation/results/v3-code-frozen-v1.json。

| 方法 | 文件Recall@5（macro） | MRR | 20跨文件题完整 |
|---|---:|---:|---:|
| flat | 1.00 | .75 | 20 |
| keyword AST块 | 1.00 | .75 | 20 |
| symbol | .75 | 1.00 | 0 |
| code_aware | 1.00 | 1.00 | 20 |

README方法无候选（冻结源文件无README）得0，不能包装成胜过有内容README；flat无符号metadata，其symbol recall=0不代表文件没命中。复杂方案没有提高本集文件召回率，仅改善定位排名。每方法实际返回引用均通过原文校验（flat/keyword/code_aware各200，symbol40）；无返回的README引用准确率为null。合成精确标识题不外推真实仓库/自然语言质量，Dense/Reranker/LLM NOT_RUN。

实际命令：`python -m pytest tests/test_workbench_interview.py tests/test_v3_public_knowledge.py tests/test_v3_code_parser.py tests/test_v3_code_rag.py tests/test_v3_github_import.py tests/test_v3_long_term.py -q --junitxml=../../work/v3-f3-integrated.xml`，114 passed/0 failed/0 skipped，11.05秒。前端node --test 13通过，Vite构建通过，证据work/v3-f3-ui-build.log。这里不是全量回归或真实模型质量测试。

## 6. 安全与限制

公共知识是术语参考，项目源码是实现存在的证据，贡献仍需用户自述；两阶段支持判定。检索文本为不可信数据，无授权不外发私有源码。

## 7. 学习顺序

实现后按导入→解析→符号/关系→召回→引用校验→面试工具阅读。

## 8. 面试问题

1. 为什么不用git clone？只需固定源码，不需要执行/认证；官方HTTPS下载更易限额与隔离，代价是大仓库不支持。
2. AST边是调用图吗？仅静态可解析引用，未解析明确计数；反射/动态绑定不能推断，也不能证明实际执行。
3. 检索分数能作证据支持率吗？不能，校验引用只证明片段来自固定源，语义支持/用户贡献另判。
4. 用了向量就更好吗？本轮真实向量未配置；精确函数题BM25已完整召回，不应编造语义收益。
5. 如何防参考答案泄漏？公开题目投影排除rubric，活动review409；完成后只复盘已答题，再提供公共学习摘要。
6. 如何保证历史引用？固定快照+commit+源hash+行原文；重建不改源，删源后失效，不用相似新源替换。

## 9. 后续

F4把工具与检索接到真实面试决策；先建立可校验的数据链，不先画假Agent轨迹。
