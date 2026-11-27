# V3实际实验结果（2026-10-21）

这里的检索数字只用于指定数据和检索合同，不是模型问答/简历事实/面试教学准确率。原始行结果保留在results/，失败保留而不修改标签。

## 冻结代码检索：40题，20精确、20跨文件
来源：F0冻结的40个合成Python文件，程序构造定义与直接import gold，CC0；SHA256见DATASETS.md。相同query、源库、top5，无模型。`python scripts/eval_v3_code.py`，结果v3-code-frozen-v1.json。

| 方法 | 文件Recall@5 macro | MRR | 跨文件完整数/20 | 校验成功/返回引用 |
|---|---:|---:|---:|---:|
| flat BM25 | 1.00 | .75 | 20/20 | 200/200 |
| keyword AST块 | 1.00 | .75 | 20/20 | 200/200 |
| symbol | .75 | 1.00 | 0/20 | 40/40 |
| code_aware | 1.00 | 1.00 | 20/20 | 200/200 |

没有文件召回增益，符号/关系改善首个相关排名；不能泛化到自然语言/跨仓库问题。README-only无候选（冻结文件没有README），其0不是有效质量比较。flat无符号元数据，symbol recall0不等于文件召回0。Dense、真正Hybrid和Reranker未配置，NOT_RUN。延迟逐条/p50/p95见JSON，单机小样本不宣传生产吞吐。

公开Starlette 0.46.2 commit 4a811767bcba6e933bf7a8b48edef5993ce8948e，BSD-3-Clause，104文件真实安全导入并在浏览器检索；1693符号/3733静态边是规模，1948未解析引用明确保留。上游测试未执行，无人工边误报率标签，不混入上述合成质量分母。

## 公共题库：40项标签诊断，39个不同query，10题
实现后依据公开标签机械构造gold，只作开发诊断，非F0冻结盲测/人工语义标注。标签路由与gold共享元数据，不能用其1.00宣传泛化。`python scripts/eval_v3_public.py`，同一dataset hash `255bf47b9ca165efb96eb97fdab551059f2e9591ede6f734b849a974543d9486`。

| 版本/方法 | Recall@5 macro | MRR | 返回引用校验 |
|---|---:|---:|---:|
| v1标题正文BM25 | .50 | .525 | 35/35 |
| v2加入公开标签BM25 | 1.00 | .9875 | 57/57 |
| tag | 1.00 | 1.00 | 42/42 |
| no retrieval | 0 | 0 | 无返回，准确率null |

v1失败完整保留v3-public-diagnostic-v1.json。v2只修索引遗漏，不改语料或诊断标签，引用仍核对原标题/正文，旧引用hash不变。Hybrid本机明确降级BM25，与BM25同分不代表向量效果。无独立人工相关性/答案教学评分。

## 可靠性和全量回归
- 真实HTTP+两个独立Worker进程：公开104文件索引提交后故障退出70，任务RUNNING；租约到期重建并SUCCEEDED，attempts2，同键同任务、第二用户404。7.899秒包含启动/故障等待，不能写成索引延迟。记录docs/devlog/evidence/v3/f5-live-worker-recovery.json。
- F5首次全量：853 passed / 3 failed / 50 skipped，142.11秒。2 Redis连接拒绝；1旧UI深路径文件创建失败。未改旧业务逻辑，短临时路径针对性61项通过。
- F6短路径全量：855 passed / 2 failed / 50 skipped，135.68秒，work/v3-f6-full.xml/log。2项仍Redis127.0.0.1:63799缺服务。50跳过=34 PG不可用+16真实模型/路径/显式opt-in条件，未冒充通过。现有测试没有删改或绕过Redis。
- 前端13 passed/0 failed/0 skipped，Vite build通过；最后构建work/v3-f5-ui-build.log。随后若有新模块改动需单独复验，不能沿用次数冒充新结果。

最终冻结复验：work/v3-f7-final-full.xml/log，**855 passed / 2 failed / 50 skipped，169.92秒**；2失败/50跳过原因与前述一致。末次复盘相关78/0/0，24.12秒。随后仅岗位界面关联数与中文日期显示修复，前端最终13/0/0/build与真实新增第三关联即时显示验证通过（f7-ui-final-tests/build）。解压独立公开包烟测实际使用包内源代码/构建/样例完成PDF输入到导出与字体验证；这复用现有依赖运行时，不能叫全新安装或Docker部署。

## 模型/人工质量与协作消融
JD≥30组人工gold、改写≥25语义案例、面试≥20轮人工盲评、Single/Sequential/Feedback真实模型对照：BLOCKED/LIVE_PENDING（未获付费/私人外发授权、无独立人工gold）。Provider替身验证角色独立/动态目标/真工具调度、代码引用和终止，不能推断LLM收益。
历史R12 17未调优JD/101原子、Evidence Accuracy93.07%和Supported Precision97.30%保留旧统计范围，不作为V3新成绩。当前不得新增“多Agent提升X%”“真实用户规模/生产部署”描述。
