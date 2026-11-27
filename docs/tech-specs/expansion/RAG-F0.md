# F0：真实产品入口与状态合同

版本1.0，2026-10-23，实施前，基线240d1b0。复用原InterviewPanel→InterviewStart API→RetrievalInterviewEngine→InterviewTools/BoundedEvidenceRetriever，不新增问答入口。

已读代码：UI默认track=job，用户显式project与固定snapshot；jd_text在project轨道是练习主题。prepare根据实际检索symbol构造有来源题目，模型Evaluator评价回答，Interviewer只选择follow_up/next/资料目标，不生成任意问答。默认Embedding/LLM关闭；增强模式显式加载现有本地Qwen/CrossEncoder。默认job进入公共题库符合产品合同，不按自动路由错误修复。

五层合同：①候选/排序只表示相关线索；②原文引用的owner/project/snapshot/hash/行段有效才是定位；③证据是否足够回答当前题需另判，limited_source_only当前只允许围绕所引片段的受限练习，不证明主题事实/运行成果；needs_input必须停止以不足主题生成断言式题目，或明确改为不声称该事实的来源限定练习；④真实生成/评价必须逐项完整且使用同来源边界，不能凭引用变成correct；⑤人工支持/教学效果始终未核。

先记录当前行为再改F3：复制固定研究索引到新输出目录，不改原DB；默认BM25用一条真实项目练习API→来源引用/pack/trace，选择可答和运行成果不足两个主题，不调用模型。增强真实配置可用性单列，不把配置存在写运行成功。基线记录HEAD、335源字节、工作树保留项、调用链和HTTP状态/题面/pack。F0自身不改产品语义或安全门禁。

验收产物docs/devlog/evidence/rag-round3-20261023/f0-*.json；实际命令/失败在RAG-F0报告续写。源码入口InterviewPanel::start、interview_api::install_interview_routes、retrieval_interview::prepare/_invoke、interview_tools::retrieve_pack、evidence_pack::retrieve。

实施后补录（包后文档，产品代码不变）：实际验收：真实默认HTTP/显式track合同verified，F0不含生成质量；结果见RAG-F0报告。
