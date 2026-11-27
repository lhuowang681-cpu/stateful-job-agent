# 第三轮有限复现

使用本轮源码包解压目录，Python3.11或3.12。先读[当前Spec](../tech-specs/CURRENT_SPEC.md)与[F4报告](../devlog/RAG-F4.md)。以下命令是复现入口，具体已经执行的版本/结果只以阶段报告及同目录原件为准，不表示每台机器都运行过。

CPU工程：`python -m pip install -e ".[dev,workbench]"`；`python scripts/expansion_ci.py --output output/round3-local-check`。输出目录必须新建。Windows若系统临时目录受限，把TEMP/TMP设为项目下可写临时目录。门禁不调用模型/PG/Redis，条件跳过另计。

真实HTTP：`python scripts/expansion_delivery_smoke.py --output output/round3-http.json`，在本机随机端口验证鉴权、前端和Trace路由，使用合成空资料，无外部服务和模型。源码包包含既有前端构建及PDF worker；前端未改，旧构建测试结果属历史。

真实检索研究包含`research/f2-new16-index-v1/`和F4纯源固定索引。它们是本项目内部源码，未声明公开授权。不要上传未知服务或执行导入源码。新16正式预约已消耗，重放/诊断必须明确为已见，不删除预约伪装新留出，也不修改原gold。原始528行、标签/锁和后补默认诊断在`docs/devlog/evidence/rag-round3-20261023/`。

F4只支持现有离线权重：设置`JOB_AGENT_WORKSPACE_EMBEDDING=local_qwen`及本机Embedding路径/device；可选显式本地reranker路径/device。`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`。7B在GPU0、Embedding与重排在GPU1，原远端两卡各24GiB；模型不随包分发，不隐式下载。模型路径/权重hash在model-identity.json，不是API凭据。

`python scripts/rag_round3_joint.py prepare --source-git <实际提交> --bundle output/new-fixed-source`创建纯源索引；`... pilot --bundle output/new-fixed-source --output output/new-pilot`运行三例。正式10场在脚本里固定；每个bundle父目录持久40尝试总上限，包含失败，正式结果已见，不可称新泛化验收。不要覆盖原报告、降低门禁或无限调试模型。API的同意字段是合成人设操作，不替代真人云端授权；本轮付费/云端调用0。

真实联合是否通过、失败案例、完整学习例的引用身份和实际次数见F4报告；人工支持关系/教学效果仍未核。第三轮包hash、CRC、解压/安装/HTTP/离线门禁证据在交付目录verification.json，不能仅看ZIP成功就说业务通过。
