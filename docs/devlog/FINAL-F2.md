# FINAL-F2 — 长期岗位、项目管理与权限底座

- 日期：2026-10-20；基线main/067bfc7，保留全部dirty工作。
- 状态：DONE（本地岗位/项目权限底座，GitHub与索引归F3）。真实模型不调用。

## 1. 业务问题与基线

已有简历/JD/面试历史按简历存储，缺岗位卡片、投递事件、代码项目快照。长期工作台需要把同一岗位的不同版本及面试关联起来，不能只保存聊天文本。

## 2. 方案与权衡

复用现有SQLite事务与身份解析。岗位事件保留历史，版本/面试关联必须同owner；项目和源码快照分离，导入先检查再原子发布。没有理由为单机演示新加向量数据库、消息总线或独立账号服务；部署保留可信Bearer映射并支持两个合成用户隔离。

## 3. 功能轨迹

- `frontend/src/JobsPanel.jsx::JobsPanel` → `api.py::create_resume_app`安装长程路由 → `long_term.py::LongTermRepository.create_job/update_job/link_job` → v3_jobs/events/links：请求键、revision、同owner且同面试版本。
- `ProjectsPanel.jsx::ProjectsPanel` → `LongTermRepository.import_zip` → `project_import.py::scan_zip/checked_path/excluded` → `publish_files`：内存安全扫描后一次事务发布；不落盘解包/不安装/不执行项目。
- `publish_files/files`：项目owner+snapshot匹配、解码文本UTF8哈希/manifest/commit身份，不同commit相同文件仍不同快照；历史引用固定，不挪到head。
- `delete_project/delete_job`：项目文件/快照外键级联；岗位删除不删除简历，简历删除清关联。贡献字段保持self_attested_not_verified。
- 默认Python路径前缀src/job_agent/resume_workspace；API和前端沿用既有应用，不新增后端框架。

## 4. 验证计划

新增测试覆盖两用户两项目、同岗位两个版本、事件乐观并发、重启、跨用户绑定拒绝；ZIP路径穿越/符号链接/大小/压缩比/敏感文件/重复文件/删除传播。先安全检查再开放导入。

实际：新增/相关42通过（F1 19+F2 23），work/v3-f2-new.xml/log；F2最终受影响回归 `python -m pytest -q ... tests/test_v3_long_term.py --basetemp=../../work/v3-f2-final --junitxml=../../work/v3-f2-final.xml`，333通过/0失败/0跳过，27.60秒。旧测试全部保留。前端 `npm run build`通过，work/v3-f2-build-final.log。
浏览器8019完成保存岗位卡片→记录已投递事件→创建贡献受限项目→保存PROJECT_NOTES.md快照，截图docs/demo/artifacts/f2-project-space.png。ZIP经真实FastAPI/TestClient raw bytes上传通过，不宣称已完成OS文件选择器浏览器验收。
真实服务同库停止/启动后，岗位1/项目1、2个投递事件/1个项目快照，完整HTTP结果SHA256前后相同；第二个合成用户项目列表为空。证据evidence/v3/f2-live-restart.json。首轮验证因httpx继承代理502且未成功保存before，不计通过；修复验证脚本trust_env=False后重新完成完整前后对照，没有改业务逻辑。

## 5. 前后对比

此前没有岗位与项目持久实体；现在本地产品接通。没有模型质量或召回提升数字；文件导入成功明确显示待索引，不冒充RAG完成。

## 6. 安全与限制

仓库导入不执行代码、不安装依赖；私库鉴权和外部模型未获授权，保持关闭。项目贡献只作用户自述，不由代码存在推断用户作者身份。

## 7. 学习路线

45分钟：JobsPanel/ProjectsPanel入口5分钟 → LongTermRepository事务/身份15分钟 → scan_zip路径与资源限制10分钟 → publish_files/files不可变血缘10分钟 → test_v3_long_term5分钟。

## 8. 面试问题

1. 为什么岗位独立于简历？同一机会可能多轮投递/多版简历，job_links保留准确版本，不用最新head替代历史。
2. 如何隔离用户？可信owner解析并进入每个资源SQL查询；跨用户资源统一404，客户端不能自选owner。
3. ZIP为何不直接extractall？路径/符号链接/膨胀与执行风险；先在配额内读允许文本，事务发布。
4. 相同源码不同commit如何处理？snapshot身份包含origin和commit，不能把A的引用指到B；文件哈希单独校验。
5. 源码存在证明用户写过吗？不证明，贡献只保存为自述，源码/测试文件都不代表已运行或独立贡献。
6. 请求超时重试怎样避免重复？岗位和事件有请求键/输入hash，快照按内容及版本身份去重，状态更新检查revision。
7. SQLite重启算Worker恢复吗？只是持久业务记录，本阶段真实重启已验；异步任务/未知副作用恢复属于F5。
8. 隐私删除是否真的删索引？目前文件/快照级联已验，F3新增索引必须同样外键级联并测试，尚不存在的向量缓存不能声称已验证。

## 9. 下一阶段

F3在已校验快照上解析和建立索引；禁止在有安全扫描前直接解压/运行用户项目。
限制：GitHub/代码索引/检索仍未接，完整公开登录/OIDC未实现；当前使用可信Bearer映射，新增两个公开合成Demo用户。`scripts/demo_resume_workbench.py --port 8019 --persistent`保留合成数据，默认不带persistent仍为临时库。模型/私库授权边界不变。
