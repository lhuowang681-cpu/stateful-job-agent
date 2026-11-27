# 本地运行与部署

当前目标为单机本地Demo，公开演示口令只允许合成/公开资料；不是公网账号服务。默认监听127.0.0.1。已有构建时无需Node；重新构建需Node≥22.12，验证环境Node24.19/Python3.12.14。

## 从源码启动
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[workbench,dev]"
cd frontend
npm ci --ignore-scripts
npm run build
cd ..
.venv\Scripts\python scripts/demo_resume_workbench.py --port 8019 --persistent --seed
```
Linux用`.venv/bin/python`。浏览器打开http://127.0.0.1:8019，主用户公开合成口令`job-agent-synthetic-demo-only-2026`，第二用户`job-agent-second-demo-user-2026`。种子只导入包内公开Starlette与原创合成项目，不联网、不发模型、不执行导入代码。简历输入样例docs/demo/assets/synthetic-resume-source.pdf，导入仍由你核对。

持久数据在output/demo-v3/workspace.sqlite；重启保留，源代码交付包不包含该数据库。项目索引由同进程独立后台线程领取SQLite任务；可用`--no-worker`禁用领取，再运行`python scripts/v3_task_worker.py --database output/demo-v3/workspace.sqlite`独立Worker。HTTP任务查询/刷新可恢复进度。

## 容器方案（本机未运行）
```text
docker compose -f compose.workbench.yml up --build
```
Dockerfile.workbench/compose.workbench.yml已提供：Node构建、非root Python、OFL字体、SQLite命名卷、宿主端口只绑定127.0.0.1；容器内监听0.0.0.0用于端口映射。本环境无Docker/WSL发行版，构建/启动标NOT_RUN，不能称容器部署验收通过。
旧compose.backend.yml对应独立PG/Redis v1，不是该React产品的存储迁移；勿混用验证结果。

## 私人本地工作区与在线模式
`resume_workspace/main.py::create_app`要求由环境提供≥32字符ASCII私有令牌、数据库路径，可选择在线provider。自行本地设置，勿把真实令牌粘贴进README/聊天/版本库。使用`python -m uvicorn job_agent.resume_workspace.main:create_app --factory --app-dir src --host 127.0.0.1 --port 8021`，并在项目根运行以满足旧fit_verdict_engine导入。该模式不是完整注册/OIDC多租户登录。
仅配置Key不会获得外发授权：产品每次在线调用仍要用户同意发送范围；源码片段/经历可能含私人信息，先审查。不自动重放未知模型结果。当前演示真实LLM/Embedding未配置，不能声称在线质量通过。

## 验证
`python scripts/eval_v3_code.py`、`python scripts/eval_v3_public.py`、`python scripts/verify_v3_local_recovery.py`。最后一个脚本创建独立临时公开数据HTTP服务与Worker，只停止自己创建的进程。
Windows全量建议短路径：`python -m pytest -q -ra --basetemp=C:\Users\1\Documents\Codex\v3-new-unique-test-dir`（用新的空路径，避免pytest清理已有数据）。PGCONNECT_TIMEOUT=2只缩短依赖检测，不绕过业务Redis；缺依赖仍真实失败/跳过。

## 已知限制
扫描OCR受本机ONNX原生初始化失败阻塞，cap.ocr=false；文字PDF优先直接抽取。PG/Redis产品集成、私库、真实向量/Reranker、外部模型和人工质量实验、云部署均未验收。合成口令禁止用于公网或私人档案；无需为本地Demo增加无关中间件。
