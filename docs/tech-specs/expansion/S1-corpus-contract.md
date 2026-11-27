# S1 语料、索引身份与评测合同

版本1.0，2026-10-22；in_progress。基于CURRENT_SPEC 0.1和S0。

## 子增量3实施前合同（S8收尾依赖）

旧18文/32题及所有结果冻结不动。另建72候选版本，补充原创合成设计文档与不同机制的代码；gold使用问题所需的精确行范围，不一概给完整文件。family/source跨split隔离，规范重复拒绝、语义近重复另出人工待核列表。每题显式检索域，不再由gold选择算法域；这仍是已知领域受控评测，不宣称产品自动路由质量。新增EvalRun与持久研究scope/索引包，配置冻结后评分测试部分，机械指标/人工支持/安全测试分层。只对实际收到的人类逐题审核保存human_reviewed状态，先准备小批原文核对包；无人确认保持AI候选。详见[S8实施合同](S8-observability-replay-delivery.md)。

## 问题、目标与备选

当前代码向量缓存键仅snapshot/model字符串，公共缓存仅chunk IDs。同名模型的模板/维度/分块变化可能误用旧向量。先补身份合同，再冻结实际语料和开发/独立测试题。复用KnowledgeChunk、原文引用、AST，不将代码等同个人经历。备选每次重编码简单但昂贵且不可追溯，采用完整manifest身份。

## 首个增量合同

`knowledge/index_manifest.py`新增EmbeddingIdentity（provider/model/revision/dimension/normalization/query_template）和IndexManifest（corpus_kind/scope/input_hash/parser_version/splitter_version/embedding）。规范JSON→SHA256；任何一项变化都失效。scope来自可信服务owner/project/snapshot或public，先鉴权再编码。input_hash包含实际embedding文本及顺序，不只chunk_id。

CodeRAG复用现有vectors表model_id字段保存manifest键，无破坏性DDL；旧键不静默复用，重建沿用级联。Public缓存同身份，引用仍用title/body，不能引用tags或私有rubric。维度/有限值/非零验证保留。测试替身身份明确test，不算真实模型。

## 评测合同（后续子增量）

三类语料为代码、项目Markdown、公共技术摘要。EvalCase包含case_id/family/source_snapshot/query/category/gold/all_or_any/answerable/split/annotation_status。无答案须给理由，dev/test家族与近重复隔离；gold定位回固定原文。先20开发候选、再30—40首批、最终60—80。AI候选和人工gold状态分开，未经人工确认不称可信语义金标。

EvalRun固定数据/配置/模型/代码身份。命中、全gold召回、MRR、引用有效、断言支持、最终业务质量分别统计；没有实际生成/人工检查的项为null。安全权限单列，测试集不用于反复调参。

## 任务、验证与回滚

1. index_manifest.py实现纯身份合同，验证模型/维度/模板/语料/parser/splitter/scope变化失效。
2. code_rag.py::_dense用manifest键存取，保持完整性及owner检查；跨重启复用。
3. public_knowledge.py::search缓存绑定同身份；空语料返回空不编码，坏向量不留缓存。
4. tests/test_v3_retrieval_identity.py覆盖同ID异配置、跨重启、污染、跨owner；实跑前不填通过。
5. 后续冻结语料/题集，补原始结果及EXPAND-S1、CURRENT_SPEC/CHANGELOG。

关闭dense可回退BM25，原表保留，新增键隔离不删用户数据。报告交付3—5入口/状态图/失败反例/5追问/20—40分钟导读，首个身份增量完成不等于S1人工语义验收。

## 子增量2：可执行评测数据合同（开发前）

knowledge/evaluation_contract.py新增CorpusDocument/CorpusSnapshot/EvalCase/GoldSpan，固定内容hash、原文行范围/quote、来源/许可、问题family、dev/test、all/any、answerable、标注状态。所有初始题为AI候选，人工状态不冒充完成。validate_dataset拒绝同family跨split、题目近重复（先用规范化完全重复检查，语义近重复仍人工待核）、gold不属于固定快照/所在split、quote/hash/行不符。测试集仅做静态合同检查，不先看检索分数调参。

首批冻结32候选：20 dev、12 heldout；代码/项目Markdown/公共摘要三种语料，dev与test源分组隔离。代码是CC0合成，公共摘要复用现有seed正文/来源版本，不把链接网页当已抓取原文。生成脚本仅冻结候选，不默认运行测试集。

evaluate_case返回any-gold Hit、gold覆盖率、all/any充分证据、首gold MRR、原文引用有效率；无答案只报告retrieved_context_on_unanswerable，不能把“检索到了上下文”直接称幻觉。断言支持/最终业务质量未人工评判时为null。检索结果须包含可信doc/version/hash/范围/quote并回原文核对；不能拿命中替代支持。

任务：新增合同模块、固定JSON与生成器、test_v3_eval_contract.py，验证跨split泄漏、篡改gold、引用伪造、多gold的all/any分母和无答案指标。后续S2对照使用冻结dev，heldout只在方案冻结后跑一次，修改合同/语料必须版本化。

实施结果：18原文/32候选（20dev/12test）已冻结，9项静态合同通过0.16s，见EXPAND-S1和s1-eval-contract.xml。语义gold/近重复人工确认仍待做；测试集未评分。实现文件为evaluation_contract.py、freeze_expansion_eval.py、docs/evaluation/expansion/candidates-v1.json、test_v3_eval_contract.py。


## 2026-10-23最终候选与Markdown补录

保留旧32题/18源与v2；最终v3为26源/72 AI候选（36/36、显式project/public scope、每组2无答案），dev28与test36的近似在任何评分前发现并改v3。8题原文核对包和1296跨split机械相似审计均已落盘；用户明确稍后人工核对、继续工程，因此human0，不升级gold。Markdown标题/段落切分、围栏内伪标题、超长表格/围栏显式片段及旧索引重建已实现。真实A—G固定研究索引/两个split评分、全新进程/目录恢复与离线正阈值合同详见EXPAND-S8；仅机械指标，原语义支持/近重复人工验收仍待用户。
