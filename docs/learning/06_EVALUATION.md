# 怎样讲实验才可信

先分工程正确性与模型效果。owner隔离、引用切片、租约、审批可以确定性断言；“优化更好”“追问更有效”需要真实模型和人工评价。测试数增加不等于准确率提高。

F0冻结40题：精确符号/跨文件gold由源定义和直接import机械构造，hash不可变。每种方法同候选库/query/top5，文件Recall按每题必要文件命中占比再macro平均；MRR是第一个相关结果排名倒数；跨文件完整率要求所有必要文件在top5内。没有返回的引用准确率应null，不能记100%。

README-only在该冻结库无候选，0分不能证明战胜一份有内容的README；flat没有符号metadata，符号定位0也不能说文件没找到。保留这些不利于宣传的限制。真实开源Starlette另作导入/引用集成，不与合成检索成绩混用。

公共40项是实现后标签派生诊断，只有39种query；标签方法与gold共用元数据，因此不算盲评/泛化。BM25漏标签的失败和修复都留下；hybrid未配置向量，指标相同只是降级，不是向量效果。

真实JD抽取/25改写/人工面试质量/Single-Sequential-Feedback消融仍LIVE_PENDING：无真实模型授权，无独立人工标注，不拿历史R12的17JD/101原子93.07%/97.30%代替。LLM-as-Judge不能成为唯一正确性依据。

复现脚本eval_v3_code.py、eval_v3_public.py、verify_v3_local_recovery.py；原始行结果与失败见evaluation/results和FAILURE_CASES.md。先读协议BASELINES.md，再读结果与局限，最后决定是否值得新增Embedding/重排/数据库。
