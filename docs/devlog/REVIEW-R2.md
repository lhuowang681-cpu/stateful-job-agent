# R2 · 从源码安装与可移植门禁

2026-10-23，安装/工程已验证，16项历史资料条件明确保留。两个httpx范围统一>=0.27,<0.29；wheel收集根fit_verdict_engine与prompts资源。Windows/Python3.12.14新环境不继承系统包；安装中断后确认旧进程不存在，完成同一新环境，失败日志保留。最终httpx0.28.1/FastAPI0.115.14/LangGraph1.2.16，pip check通过；python -I从site-packages加载主包/根评分模块/提示。Linux/Python3.11.15另建空环境从源码安装成功，pip check及-I真实HTTP通过，不把3.11称3.12。

安装HTTP v1启动超时；v2补listen并允许本地回环，真实启动/匿名401/来源201/解析201/接受版本201/列表200/关闭通过，见r2-installed-http-v2.json。两条件同时改变，不单独归因边界。新环境核心focused-v2为94通过/2跳过，27.68秒；v1误写不存在文件，未运行，原日志保留。

公开SQL/hash清单重建合成研究DB，旧v1不改。产品audit核原文、scope、symbol/chunk/edge/vector。物理DB序列化hash不同，明确新portable-2 manifest；只重绑原门槛，不改floors/基线。只有研究表有合成数据，简历/面试/学习表空，不夹带用户库。gitattributes防换行损坏hash。portable-gate及fresh-offline-v2中的BM25门禁通过，2可移植合同通过1.16秒。

稳定集合fresh-offline-v2在Windows早期4错误并长期停滞；核实进程后仅停止该测试子进程，原过程保留，不称整集合通过。全仓diagnostic-v1收集17错，缺mcp/faiss/streamlit，区别于旧44运行失败；待补依赖分类，未删测试。普通CI仅BM25质量门槛，确定性Dense/RRF/rerank合同与真实GPU/生成分层。CURRENT_SPEC旧过程移日期历史页，当前页区分工程/业务/候选/人工。

## 25分钟学习单元

5分钟pyproject依赖/根包/资源与-I隔离导入；5分钟review_installed_http_smoke.py::main的socket/鉴权/关闭；10分钟review_materialize_fixture.py::materialize→research_contract.inspect_bundle/_audit_db→evaluate/check_gate；5分钟对照原阈值和新manifest。备选提交二进制不便审计故公开合成SQL；复用旧环境不证明安装故新venv；不降低门槛掩盖重建问题。

五个追问：①pip check证明启动吗？只检查依赖，需HTTP。②cwd导入为何不足？会隐藏漏打包，-I核site-packages。③重建hash为何变？物理布局不同，需新manifest与逻辑audit。④BM25代表Dense质量吗？不代表。⑤为何保留命令失败？区分命令/环境/产品错误，不抹证据。


## 后续实际结果

Linux空环境最终离线门禁604通过/34跳过，64.18秒。首600/4/34保留；四项旧Provider输入改完整uncertain，原工具/安全包断言不变，定向53通过。Windows全仓v3在PGCONNECT_TIMEOUT=3下完成1002通过/58失败/84跳过：41缺历史资料、2旧Redis未启、11 FAISS中文路径、4旧Provider输入。分类原件r2-full-failure-classification-v3.json。早期无限PG等待及默认边界HTTP停滞均保留，不当产品全仓成功。

FAISS中文路径先2项正式红测，再用Path.open与原生流回调修复，保留二进制格式/排名/维度/数量校验及上层原子发布，未复制全量索引。首次相关17通过/2失败：一项历史资料缺失；MCP子进程仍加载旧已安装包。刷新本轮独立环境wheel后46通过/1缺失历史资料，跨进程重启已过。

从仓库现有v4/v5确定性公开构建器原样重建10个缺失工件，当前重建时间、构建器/内容hash另记r2-public-fixture-reconstruction-v1.json。未手工发明gold、不覆盖已有不同文件、不证明任何历史live执行；重建后的25项相关历史资料测试已恢复。仍缺的16项原始资料没有可确认原样构建来源，留具体路径/条件，不删除测试、不默认skip或编造历史评分。旧Redis两项另设真实服务验证，最终全仓复跑待R5。

## 最终全仓分类

r5-full-v1.xml实际结果1051通过、16失败、84跳过，276.21秒。16项全部是原始历史资料FileNotFoundError；逐测试/路径见r5-remaining-legacy-conditions-v1.json。原始stateful/atomic/career资料没有可确认的独立原样构建来源，不能用新发明的gold替换。未删除、改skip或改评分断言。84跳过为原可选PG/真实模型等条件，不能称已执行。独立Redis7.2.16两项本轮真实通过，最终Windows全仓经回环转发使用同一PID140982；原S6实例未动。

最终Windows wheel已刷新；-I正式main.create_app、匿名401、真实来源/解析/接受/列表，以及全部5个前端资源（含PDF .mjs worker）均通过，r5-installed-main-http-v1.json。前端13测试与生产构建通过。CI使用Linux/Python3.11实际观察锁，Windows3.12锁单列；云端Actions未执行不冒称成功。新交付源码的空环境复现见交付目录verification.json。
