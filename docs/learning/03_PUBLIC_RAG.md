# 小型公共知识库怎样落地

问题：每次面试只用固定旧题，无法按知识点找资料；把参考答案公开又会破坏练习。`public_seed.seed_entries`建立10份原创CC0技术摘要+10题，记录官方参考URL/整理日期/版本/许可。内容是本项目整理，不是官方原文或官方背书。

`PublicKnowledgeRepository`保存不可变版本、去重、删除和哈希；`PublicKnowledgeService.search`支持标签、BM25、可选向量/融合；`private_question`只对服务内部开放。前端搜索题目DTO不含答案/别名/追问模板，结束review才开放已答评价与公共学习材料。

真实失败：第一版BM25只索引标题/正文，公开标签中的术语查不到；诊断40项中只召回一半。修正仅把公开标签加入搜索文本，引用原文仍是原来标题/正文，历史quote/hash不改。前后JSON均保留，标签派生诊断不是人工语义金标，不能外推“RAG准确率100%”。

原始RAG是“检索提供上下文再生成/选题”，不是相似分数直接变supported。资料不能证明用户有相应技能，仓库只读不执行。缺真实Embedding时dense不可用、hybrid明确BM25降级，未部署ES/Reranker。

读public_knowledge.py::search/reference/validate_reference → interview_tools.py → interview_api.py::review → scripts/eval_v3_public.py。替代整库塞上下文适合十条规模但会暴露答案且难扩展，所以私有rubric与公开索引分开。
