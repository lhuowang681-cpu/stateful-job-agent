# RAG-F0 · 真实产品合同与基线

2026-10-23，in_progress。基线main/240d1b0，实施前Spec见docs/tech-specs/expansion/RAG-F0.md；尚未产生本轮运行结果，不以静态代码存在代替通过。旧资料/实验/包、并行学习与人工0保留。实际功能轨迹、失败、命令和20—40分钟导读随进展追加。

## 实际基线（产品尚未修改）

默认BM25真实HTTP完成3请求：默认job进入公共题库；显式项目主题read_code_range/validate_reference建立项目练习；“真实录用率提高多少”也建立项目练习，实际引用risk_flags而未回答录用率。三者201/active，pack均limited_source_only；这证明未识别该成果前提并显式限定主题，不证明已经生成了虚假数字。v1所有HTTP已完成，但Windows临时SQLite备份连接未显式close导致清理PermissionError；v2用closing关闭备份连接后完整退出。两份原件保留，不能把v1清理错误说成产品HTTP失败。

入口：InterviewPanel.start固定track/snapshot/use_retrieval；API→prepare→retrieve_pack→code_search→引用原文校验→按symbol构造题目。文本模型只评价/选追问，不生成任意项目答案。默认无Embedding/重排；GPU0/1各仅13MiB、已有7B/14B与Embedding/重排权重目录可用，尚未加载不能称模型通过。远端新output/rag-round3-20261023创建，旧目录未覆盖，DeepSeek环境为空，付费0。

F3要解决的具体边界是：有限来源主题发生更换时向用户说明不足及限定，并把状态/理由传给题目、评价与观察；不能按评测新造问答入口。F0合同核对与默认基线verified，增强运行在F2/F4另记。

## 20分钟导读与取舍

5分钟InterviewPanel.start→InterviewStart，5分钟RetrievalInterviewEngine.prepare/_invoke，5分钟InterviewTools.retrieve_pack→BoundedEvidenceRetriever.retrieve，5分钟f0-product-http-before-v2.json。前端显式选轨道/快照→检索→固定题面与来源→评价/动作→观察；备选自动问答路由会改变产品范围，本轮不选。

五追问：①jd_text是待回答问题吗？project轨道是主题，实际题面另生成。②默认job进题库是bug吗？符合显式track合同。③limited_source_only是充分吗？仅允许来源限定，不证明主题成果。④真实项目引用代表用户贡献吗？不代表。⑤三请求201代表质量吗？只证明HTTP/范围与状态，不证明语义或真实模型。
