# R0—R5 本轮复现与演示

本轮入口：docs/devlog/REVIEW-R5.md。新三包在output/review-20261023/delivery-r5-v1，delivery.json记录包hash与逐文件清单；verification.json记录解包后实际执行结果。旧output/expansion包不覆盖。源码包包含可审计代码、公开测试材料和本轮证据；真实研究包只含已审计的项目源码派生索引，不含用户数据库、模型权重、环境或密钥。项目原文仅有内部评测授权，不额外声称CC0。

支持实测为Linux/Python3.11.15与Windows/Python3.12.14。Linux可在解压源码新目录执行：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install '.[dev,workbench]' -c docs/evaluation/expansion/requirements-ci-review-linux-20261023.txt
.venv/bin/python -m pip check
.venv/bin/python -I scripts/review_installed_http_smoke.py installed-main.json --launcher
.venv/bin/python scripts/expansion_ci.py --output output/new-offline-run
```

最后一条使用公开SQL重建专用合成研究索引，BM25门槛不降低，同时跑稳定工程合同，不加载生成模型或私有服务。Windows把环境解释器换为`.venv/Scripts/python.exe`，采用独立Windows观察锁；本机受限回环须在允许本地HTTP的环境运行。不要把全仓1051/16/84称全绿，原始缺失条件见r5-remaining-legacy-conditions-v1.json。

10分钟演示：先读R1真实socket修前/修后JSON，比较status/revision/turns/调用/观察；再读最终DeepSeek改写HTTP中的非照抄候选与显式审批；最后读fixed-reference-learning-v2中正确/部分/错误/不会/证据不足的实际逐项状态及同题新场。原模型小、提示失败和测试题面错配原件均保留，未要求再次付费复跑。

真实研究包解压后，用源码包中的脚本并显式指定本地已存在的Qwen与重排权重：

```bash
python scripts/expansion_research.py replay --bundle /new/research/r4-real-index-v3 --reference /new/reference/test --output /new/replay.json --split test --model-path /local/Qwen3-Embedding-0.6B --rerank-path /local/mmarco-mMiniLMv2-L12-H384-v1
```

reference目录需要原始test run.json和queries.jsonl，可从研究包docs/devlog/evidence/review-20261023/r4-real-test-v3.json及同名前缀queries.jsonl复制成这两个文件。主集dev/test各140组合引用/候选顺序重放通过、文档编码0；补充设计集独立保存。GPU环境不是CPU空安装环境，不混写。默认入口路由与同范围召回分开，项目引用有效不证明回答支持正确。人工8题稍后核，仍0。
