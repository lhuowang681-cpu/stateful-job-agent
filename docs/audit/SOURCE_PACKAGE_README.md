# 最终代码包使用说明

原始说明对应 2026-10-18 审计基线；2026-10-20 的升级 M2 包另包含 React 源码/构建、
文档导入解析与版本编辑。当前启动与验证范围以 `docs/upgrade/02_IMPORT_PARSE_EDITOR.md` 为准，
下面的旧全量结果仍只属于历史基线。
完整包包含源码、测试、脚本、文档和公开 fixtures/eval。
包内 `SOURCE_PACKAGE_MANIFEST.json` 逐文件列出 SHA-256。

明确排除：真实 `.env`、私人 JD/简历/knowledge corpus、Git 历史、虚拟环境/缓存、数据库、
旧压缩包和原业务运行输出。原始备份仍单独保留，未因打包而删除。
`docs/audit/` 中的日志是本次 synthetic 测试与公开汇总验证证据。

## 源码使用

在解压后的 `agent-backend-service` 根目录执行，使用 Python 3.11+：

```bash
python -m venv .venv
# 激活 .venv；Windows 使用 .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,ui,career-knowledge]"
git init
python -m pytest -q
```

`git init` 只为 privacy-ignore 合同测试提供 Git 工作区；代码包未附带原始历史，不需要提交。
直接运行 `scripts/` 时还需将仓库根目录与 src 放入 PYTHONPATH（包含根目录 fit_verdict_engine）：
Windows 为 `$env:PYTHONPATH='.;src'`，Linux 为 `export PYTHONPATH=.:src`。

未启动独立 PG/Redis 时，数据库条件测试会跳过，两个直接访问 Redis 的测试会连接失败。
相关 fixture 会 TRUNCATE 专用测试表、FLUSH 测试 Redis DB，务必使用可丢弃的独立实例。
仓库 Compose 是一种可选复现方式；**本轮实际用的是临时 Linux 原生 PG14.24/Redis7.4.6，同机测试**，
不是声称在本轮验证了 Compose 的 PostgreSQL16 全部署。

```bash
# 仅供准备独立测试依赖的复现示例；本轮未执行此 Docker 命令。
docker compose -p job-agent-closeout -f compose.backend.yml up -d postgres redis
python -m pytest -q
```

最终结果：568 passed / 0 failed / 16 skipped。剩余项目需要真实模型路径或显式 live opt-in，
不能把跳过说成模型验收通过。无模型环境可以运行 synthetic 合同与 mock 测试；
live UI 还依赖外部 release skill root、模型配置和环境中的密钥，代码包不提供这些私人配置。

完整证据与边界请阅读 `docs/PROJECT_AUDIT.md`、`docs/INTERVIEW_SOURCE_GUIDE.md`、
`docs/resume_notes.md`。当前架构已冻结；本包用于基于现有代码准备技术面试。
