# 连续演示脚本

预先运行DEPLOYMENT.md的persistent --seed命令，全部使用合成/公开样例，无LLM调用，屏幕保留合成/规则模式提示。5–8分钟是展示目标，不是本轮自动测得的完成耗时。

## 新手完整演示（目标5–8分钟）
1. 用主合成口令进入工作台，上传assets/synthetic-resume-source.pdf。自动填16项，逐项核对教育/项目/技能，保存v1；说明这是用户自述，不是第三方认证。
2. 分析目标JD：`招聘Python AI Agent开发实习生。要求使用FastAPI开发接口；理解LangGraph Checkpoint、RAG检索、Redis Streams与幂等处理。` 观察已有FastAPI词面线索与其余待补材料；规则模式不作语义支持，未找到不等于不会。
3. 展开局部措辞优化，选择“使用Python和FastAPI…”条目，本地改写为“基于Python和FastAPI…”。查看Writer/Reviewer交接、核对后接受为新C1，产生v2，再单独确认。
4. 生成classic/compact模板PDF，查看真实PDF.js预览，下载并选择复制文字。已确认版hash与导出绑定。Reviewer拦截虚构年限/数字的反例见test_v3_rewrite.py的真实测试，不把规则演示伪装成现场LLM生成负例。
5. 创建“连续演示源码”项目，贡献写“合成教学样例，未生产部署”。上传assets/synthetic-receipts.zip，点后台建立索引，观察排队→完成；离开页面可重开任务历史。搜索`save_receipt callers references`，查看定义/调用方/测试，明确未运行代码。
6. 回到v2简历，模拟面试选项目源码，固定上述项目/快照；JD输入`save_receipt callers references；Python API、幂等回执和测试边界。` 首题定位storage函数。回答“我想先查看测试，暂不清楚”，下一题展示tests/test_storage.py。展开真实工具与协作记录，看到code_search/get_symbol/find_references，而不是假轨迹。
7. 结束，查看已答复盘/公共AST资料。点根据待补充项准备专项练习；源码边界缺口路由到AST/引用知识题，回答后结束。对照只在同题、同rubric/alias/模型时计算参考要点变化；不同题明确不算提升。
8. 岗位与投递：建立手工卡片，关联v1/v2及本场面试，记录一次投递进展。刷新/服务重启后重新登录查看历史，确认仍可追踪。第二用户使用独立空间，不应看到主用户私人数据。

真实操作截图：artifacts/f7-pdf-v2.png、f7-pdf-v2-detail.png、f7-async-index.png及f4-project-followup/f4-tool-trace。公开Starlette另可查run_in_threadpool，固定commit，明确不是本人作品；ZIP样例没有Git commit则显示不可变快照，不能编造SHA。

## 招聘方展示（目标2–3分钟）
- 30秒：展示简历原文/字段、v1/v2、已确认PDF，讲“事实和表达分开”。
- 60秒：源码面试不完整回答→真实工具取回测试→下一题改变，打开角色交接/工具预算，讲“反馈改变决策，私有答案不泄漏”。
- 30秒：显示故障恢复JSON与文件/行/版本引用，讲“读取源码不是执行，代码存在不是作者/运行证明”。
- 30秒：展示冻结实验负结果flat已全召回、复杂方案只改排名；说明真实LLM/人工质量、OCR和PG/Redis集成限制，避免夸大。

## 中断/失败时
任务排队可回项目查看；未配置模型不改成假在线结果。GitHub分支API配额失败可使用包内公开ZIP或验证完整SHA；不尝试私人凭据。源已删除的历史引用应不可读。不要重置数据库以隐藏失败，保留任务和开发日志。
