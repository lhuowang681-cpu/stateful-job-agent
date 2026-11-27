# S0 当前环境与合成业务基线

版本1.1，2026-10-22；verified（当前基线核验范围）。依据总计划2.0及新开发交接。仅本项目可写。

收尾状态：verified（基线识别/合成链/失败分类）；全仓并非全通过。补UI依赖全仓839/45/50，45项归因41缺历史资源、2 Redis、1 Git、1本次Qwen兼容回归；后者已修复且77定向通过，其他条件待后续处理。证据与学习见EXPAND-S0。

## 场景、目标和非目标

本地为V3 F7解压包，无.git；包内855/2/50非本次复现。用户随后提供SSH运行环境。远端`/root/autodl-tmp/study/agent-backend-service`为旧main/067bfc7d，缺resume_workspace，不覆盖。以本地新版为来源，在独立`/root/autodl-tmp/study/job-agent-v3`运行；先检查目标不存在。密码不写文件、日志或Spec。

目标：核实入口/状态/存储，完成合成简历→JD、项目→索引→可校验引用；留当前回归和环境证据。非目标：私人材料、付费调用、公开发布、伪造Git历史、修改另一个项目。Git留痕尚未授权初始化，先保留修改前hash及增量diff。

## 合同与文件任务

|任务|文件/符号|输入→输出/验收|状态|
|---|---|---|---|
|来源基线|evidence/expansion/s0-start.json|修改前794文件→SHA256；后续差异可查|verified（静态）|
|依赖探针|本地+SSH|模块/设备/端口→已测/缺失，不能按配置推断服务|verified；s0-environment.json|
|合成闭环|scripts/expansion_baseline.py|固定合成输入→版本/JD/引用，owner隔离，C1不升级|verified；s0-http.json及S2真实模型pilot|
|回归|tests/test_resume_*、test_v3_*及全仓|当前源码→原始日志/JUnit；失败/跳过分层|verified（已运行并分类）；不是全绿，见EXPAND-S0|

现有链：可信Bearer→owner→SQLite来源/不可变版本/项目快照；任务→CodeRAGService.build→同库租约fencing发布；面试复用工具Registry/Policy/Executor。旧PG/Redis仍独立，S5/S6才迁移切片。

## 方案、失败与回滚

服务器已有两张4090和本地Qwen3-Embedding-0.6B；模型加载/PG/Redis尚未验证。本地bundled Python缺FastAPI/pytest等；复用远端Python可用包，在新目录隔离安装缺失包，不更新别的环境。备选覆盖旧repo会破坏版本边界，故不选。所有运行使用新合成库；不读取用户私人数据库。停止进程只针对本次创建PID；回滚停用新增目录即可。

## 验收与学习

原始结果记录实际时间、运行目录、源码/输入hash、依赖版本、命令和失败。至少一条核心合成链可复现；环境与业务失败分开。EXPAND-S0报告同步CURRENT_SPEC/CHANGELOG/INDEX，给出状态图、3—5入口、5追问、20—40分钟导读。真实服务、模型、人工质量分别表述。

## 执行中真实偏差

- 基线相关246项通过，真实HTTP合成链通过；含首个增量的相关264项通过。不是全仓通过。
- 扩大全仓首次采集在2个旧Streamlit测试处因缺streamlit而中断，5.59秒，原始s0-full-regression.xml/log保留。按项目ui extra在独立.venv补依赖，再另存第二次结果，不能删除失败或改成跳过凑全绿。
- 新增学习handbook文件由其他工作并发出现；不修改、不计作本次贡献，增量同步排除handbook。基线hash是捕获时内容，不声称整个共享目录冻结。
