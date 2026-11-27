# 代码感知索引的真实实现

实现：`src/job_agent/resume_workspace/{project_import,github_import,long_term,code_parser,code_rag}.py`。阅读时从类/函数定位，行号随开发会变化。

## 导入与版本
`ProjectsPanel` → long_term安装的ZIP/GitHub API → `scan_zip` / `PublicGitHubImporter.import_project` → `LongTermRepository.publish_files`。只解析文本，不解包到用户文件系统、不安装/导入/执行项目。限制8MB ZIP、24MB展开、1200项、256KB可读单文件及配额，拒绝路径穿越/symlink/凭据文件。忽略图片也先计入总量。

GitHub仅固定官方域名、公网DNS、验证TLS、不跟重定向、不用凭据。分支API先解析40位commit；完整SHA下载要求git archive comment相等。公开Starlette固定版本成功，分支API403保留在失败记录。私库未接入。

快照身份含文件manifest/导入来源/commit；源文本哈希明确按解码文本UTF-8计算。文件列表与单文件读取校验内容；旧引用不会跟随head。贡献字段是用户自述，导入公开仓库不获得作者身份。

## 符号与关系
`parse_file`：Python `ast.parse`，JS/TS/TSX使用Tree-sitter；提取定义/签名/文档/行位置。语法错或插件不可用明确文本降级。`resolve_edges`只收录可唯一消歧的静态引用，动态绑定不按方法名猜。没有运行时call graph、类型检查或上游测试执行结果。

`CodeRAGService.build`：产生flat和语法块、符号/边；数量上限12000块/15000符号/30000边。SQL事务整体替换派生索引；source快照不变。payload/源manifest/符号集合/边集合均有完整性校验。版本过期显示needs_rebuild，拒绝用旧索引检索。后台任务的publish_guard在同一写事务检查租约，旧Worker不能发布。

## 查询路由
`search`：精确符号优先，复用BM25；可注入真实Embedding后使用向量/RRF。目前演示未配置语义模型，dense拒绝、hybrid明确降级。关系展开最多2跳、8关联，返回最多20片段；默认top5。不引入ES/图数据库，因为合成精确题平面BM25已全召回，尚无额外部署成本的收益证据。

`get_symbol`歧义拒绝；`find_references(tests_only=True)`只找测试源码；`read_code_range`最多120行/12000字符。引用绑定owner/project/snapshot/source/hash/path/commit/行原文，`validate_reference`重新读取验证并把支持标记归为needs_judgment。引用可解析与语义支持是两件事。

## 产品接入与证据
项目检索UI/API和`RetrievalInterviewEngine`使用同一CodeRAGService；Agent工具通过原ToolRegistry/PolicyEngine/ToolExecutor，绑定范围由服务控制。见FINAL-F3/F4/F5、test_v3_code_parser.py、test_v3_code_rag.py、test_v3_interview_tools.py、test_v3_tasks.py。
40题冻结实验见`docs/evaluation/results/v3-code-frozen-v1.json`。AST关系没有提高本集文件召回率，改善首个相关排名；语义、跨仓泛化和边误报率人工标注仍不足，不能推广成通用质量成绩。
