# V3失败与边界记录

1. PDF在内嵌浏览器iframe空白：文件有效但插件预览不可依赖。换同源PDF.js渲染实际PDF，F1浏览器逐页检查；不以HTTP200代替可见预览。
2. GitHub分支API403配额：明确错误/保留失败，不冒充仓库不存在；固定公开完整SHA的codeload校验archive comment成功。私库和凭据不尝试。
3. 合法大PNG被文本读取单文件上限误拒：总量/路径检查后跳过二进制资产，文本炸弹仍拒，新增回归。
4. 代码基线flat已有全部文件召回：复杂检索没有召回增益，仅定位排名不同；保留结果，不改冻结标签制造提升。README无候选不能作为宣传对照。
5. 公共BM25遗漏公开标签：v1标签诊断Recall .50，修索引后v2为1；标签派生开发集与gold共享信息，不能宣传语义准确率100%。原始JSON都在results。
6. 第一次面试完整回答覆盖规则要点，正确转题而非预期追问：改用明确不完整合成回答验证反馈，不降低评分标准；规则只按词面，不验证整个解释正确性。
7. 项目薄弱项按原问题长句检索误召Schema：改源码边界主题路由；仍为规则教学建议，无个性化效果金标。
8. 独立Worker第一次启动缺ROOT导入路径，ModuleNotFoundError：修入口搜索路径，真实故障流程重跑通过。work/v3-f5-live-recovery.log为失败，fixed.log为通过。
9. 全量旧UI在深Windows临时目录创建长文件名失败：短独立basetemp复验通过，未修改测试/事实逻辑。首次误拼--basetmp被pytest拒绝，未运行测试，不统计为通过或用例失败。
10. Redis2项连接拒绝、PG34项跳过、模型16项条件跳过：当前未提供这些集成条件；历史Linux结果不替代本轮实测。
11. OCR最新CPU运行时1.31.0在本机import直接退出；兼容1.22.1复验明确DLL初始化失败。公开RapidOCR/PDFium依赖仅安装在本轮隔离venv，未识别成功，未把无验证适配接入主链，capabilities.ocr仍false。P1扫描OCR标BLOCKED（Windows原生运行时），文字PDF照常使用；没有外发文档。证据work/v3-ocr-install.log、v3-ocr-runtime-compat.log，官方参考https://github.com/RapidAI/RapidOCR与https://rapidai.github.io/RapidOCRDocs/main/quickstart/。

所有检索引用只定位来源，不证明现实经历、个人贡献或程序运行。动态边无法消歧应缺边，不能猜测调用；找不到测试不等于项目没有测试，查到测试不等于已执行通过。
