# FINAL-F7 — 本地连续Demo与最终材料

状态LOCALLY_VERIFIED / LIVE_PENDING：业务与最终界面修复已冻结，完整本地连续验收通过，阻塞项保留。2026-10-21，main/067bfc7 dirty，未提交或push；所有既存改动保留。

## 问题与方案
多个模块单测通过不代表用户能连续操作。复用既有界面与存储，给出一套合成PDF/JD/源码种子，固定来源/许可，不需要付费模型。公开合成账号只作本地演示，真实模型/人工质量/生产依赖单列限制。

## 已实际操作
8019真实浏览器文件选择器上传合成PDF→自动填写16项→人工核对保存v1→输入JD→看FastAPI线索和LangGraph/RAG/Redis待补材料→局部改写审批v2→单独确认→PDF.js预览→真实点击下载。下载文件已复制到artifacts/f7-confirmed-v2-classic.pdf，并用pypdf检查1页、文字可选择、含接受后的“基于Python”。截图f7-pdf-v2/f7-pdf-v2-detail。
同一账号创建“V3连续演示源码”→实际文件选择器上传ZIP→后台任务显示排队→自动完成，6文件/8符号/6静态边→搜索定义/调用/测试。截图f7-async-index。回v2简历→项目面试固定刚上传快照→不完整回答→测试来源追问（真实工具3次）→结束复盘公共资料。重启服务后v2/导出/项目与面试历史保留；从历史进入源码薄弱项练习，实际路由AST题（首次泛Schema误召已修）。

## 交付材料与代价
README、PROJECT_AUDIT、INTERVIEW_SOURCE_GUIDE、resume_notes、learning/00…06与32问答、architecture/Code RAG与交接、evaluation/逐行结果/失败、demo/脚本/部署/合成来源均已更新。Docker配置只绑定宿主127.0.0.1，非root+持久卷；本机无Docker，NOT_RUN，不把静态配置当部署成功。
公开PDF长样例6/5页已逐页渲染，输入PDF另已检查；OFL字体必须完整打包。源代码包不能含env/私人材料/数据库/运行态/依赖目录；用安全白名单与文件hash核验，保留压缩包内许可。

## 验证
最后业务修改相关78/0/0（work/v3-f7-related.xml，24.12秒）；最终完整回归855通过/2 Redis失败/50条件跳过（f7-final-full，169.92秒）。最后前端13/0/0/build通过（f7-ui-final-tests/build）；只对浏览器发现的卡片关联数量未同步做小修，面试下拉改为日期/中文状态，真实新增第三关联即时同步。没有改后端合同/评测标签。
浏览器三模式都实际回答并结束；补弱AST题回答后显示不同题不算提升，岗位关联v1+v2源码面试+v2补弱共3条，投递事件保存。第二用户无主用户简历、仅1自身项目。scripts/verify_v3_demo_state.py只读HTTP断言全部通过，公开脱敏trace保存devlog/traces/v3-source-interview.json；不是拿脚本替代浏览器。
公开源码包候选703文件CRC与逐文件hash通过，解压独立目录确保导入包内job_agent、种子2主项目/10摘要、前端可服务、PDF上传→解析→确认→导出与字体实际可用。使用现有依赖runtime，不冒充全新依赖安装或容器启动；记录f7-package-smoke.json。最后仅文档/验证脚本补齐后重打包并重验CRC/hash与实现树一致性。

## 限制/验收原则
真实模型/Embedding/人工语义gold与协作消融LIVE_PENDING；OCR两个CPU运行时本机初始化失败BLOCKED；新产品PG/Redis适配及容器实测未完成，不说全量全过或完全生产可用。独立旧模块按边界保留。

## 学习与面试
一小时路线见learning/00_READ_FIRST；核心追问32条见INTERVIEW_QA，均能定位源码。重点解释为何短材料直读、为何来源与真实性分层、为何反馈要改变工具目标、为何静态边不能当执行结果、为何索引可重建而未知付费调用不可盲重放。

## 停止条件
FINAL_HANDOVER已生成；最终公开源码/学习包重打包校验后停止工程修改。未来授权的真实模型/生产集成另立验证任务，不继续添功能。
