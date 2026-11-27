# 固定研究包使用说明

数据全部为作者合成CC0源码/项目说明及项目自写公共技术摘要，公共链接未当作抓取原文。72题均为AI候选，8题人工支持/定位核对由用户明确延期，human_reviewed_count=0。三包共同以当前SOURCE_MANIFEST为来源；先解压源码包，再将研究包解压到同一目录，研究工件位于research/。

manifest固定模型/设置、算法源码hash、dev/test各自owner/project/snapshot/index/chunk/edge/public-version、原文数据和两个SQLite/公共向量快照hash。实际生成后的预热/编码次数与冷启动另存。SQLite仅含本次合成研究项目，检查拒绝其他非空业务表和源原文漂移。hash可发现意外损坏，不能取代可信生产者签名。

普通离线门禁：安装源码包说明中的Python 3.12依赖后，运行以下命令；不需要GPU/模型/PG/Redis/网络。输出目录必须未存在。

```text
python scripts/expansion_research.py gate --bundle research/index-v1 --gate-file research/retrieval-gate-v1.json --output output/research-gate-new
python scripts/expansion_ci.py --gate-only --output output/fixture-gate-new
```

前者使用研究包，后者使用源码内同字节的tests/fixtures/expansion_research/index-v1。四个阈值来自实际dev BM25基线减一题，不从test调整；多证据开发基线0只观察，claim_support/最终业务质量不设假门槛。prepare保存的模型元信息在CPU离线检查中不表示模型已加载，只检查真实冻结工件和BM25回归。

严格模型重放需原同版本的本地Qwen3-Embedding-0.6B与CrossEncoder权重、sentence-transformers/transformers/torch及可用设备。权重和运行库不随包附送，实际身份在manifest，版本不符拒绝。复制整个research/index-v1到新目录，在新进程运行：

```text
python scripts/expansion_research.py replay --bundle copied-index-v1 --reference research/evaluations/dev-v1 --output output/replay-dev-new.json --model-path LOCAL_QWEN_DIRECTORY --rerank-path LOCAL_CROSS_ENCODER_DIRECTORY
python scripts/expansion_research.py replay --bundle copied-index-v1 --reference research/evaluations/test-v1 --split test --output output/replay-test-new.json --model-path LOCAL_QWEN_DIRECTORY --rerank-path LOCAL_CROSS_ENCODER_DIRECTORY
```

这只重做检索并比较全部固定引用/候选顺序，不重新构建文档、不调用文本模型、不执行导入源码。已实测每split210 case×variant组合、0文档编码。浮点得分和耗时不要求逐位相等。已评分heldout保留reservation；普通evaluate不会静默再评分，replay也不作为重新调参入口。

原始queries.jsonl包含真实trace/引用/时间/错误；run.json包含raw SHA/代码/配置/模型/scope及结果口径。第0次用于质量，全部3重复用于延迟。E/F/G只有项目22题，不能拿其分母与A—D全部36题直接比。每split34可回答，剩余2无答案只记是否检索上下文；没有生成答案，不能据此算“幻觉率”。检索失败在可回答指标中算0，不丢弃失败改善均值。

trace-examples是已实际运行合成流程的脱敏只读事件，schema和TRACE_CONSUMER解释根子账本/unknown时间。用源码包的inspect_unified_trace检查，不执行原业务。详细正负结果、故障测试、人工待验边界见EXPAND-S8和四条演示runbook。
