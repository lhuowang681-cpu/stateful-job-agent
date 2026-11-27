# 项目代码如何成为可追问材料

问题：README常常写得比真实实现完整，不能只读README就替用户断言生产经验。索引源码能定位定义、引用和测试，但仍不能证明作者或运行情况。

读project_import.scan_zip → long_term.publish_files → code_parser.parse_file/resolve_edges → code_rag.build/search → validate_reference → retrieval_interview.prepare。Python AST与Tree-sitter只解析，不执行；动态方法保守不连边。精确符号优先，关系展开有深度/数量限制。

一次save_receipt场景：code_search返回app/storage.py定义与app/api.py调用；不完整回答提出测试需求；Interviewer选择tests，get_symbol固定定义、find_references(tests_only=True)返回tests/test_storage.py，下一题据此问覆盖边界。界面写明未执行测试，源码引用按owner/快照/commit/hash/行原文验证。

代价：静态分析不完整；大仓库/超长行有上限；解析器升级要重建派生索引。相比GraphDB/自由代码执行，SQL静态边更简单且降低不可信仓库执行风险，尚无证据需要Neo4j。

冻结40题平面检索已经全文件召回，代码感知提高首个相关定位排名而非召回率；本集是机械构造精确标识，不足以证明自然语言复杂问答泛化。详情architecture/CODE_RAG_INDEXING.md和evaluation/RESULTS.md。
