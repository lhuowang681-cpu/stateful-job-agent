# 演示数据来源与许可

- synthetic-resume-source.pdf：本项目生成的虚构“演示同学/示例大学”简历，邮箱example.invalid，CC0，无真人联系方式。生成脚本create_v3_demo_resume.py，中文字体另受OFL许可。
- synthetic-receipts.zip：原创CC0 Python+TypeScript回执教学源码，6文件、8符号；只示范内存去重，不是生产实现。未执行导入源码或其中测试。固定ZIP timestamp便于复现hash，见synthetic-receipts-manifest.json。
- starlette-public-0.46.2.zip：公开Starlette commit 4a811767bcba6e933bf7a8b48edef5993ce8948e，BSD-3-Clause，保留归档内LICENSE.md；SHA256 792a950c58e4727b8e7afe728a4b68b4ddc24d91ac28441bac3c37b59caea881。来源和真实导入报告见同目录starlette-public-manifest.json。用于阅读，不能声称用户开发或运行过。
- 公共技术整理/题：public_seed.py原创10摘要+10题，CC0，引用官方技术资料URL/版本；不是官方逐字镜像。题目参考要点只服务内部/结束复盘，不公开活动答案。
- 代码冻结40题：tests/fixtures/v3_frozen/code_queries.json，F0先冻结；开发回执样例与其函数名不同，未调冻结标签。公共40项标签诊断是在实现后构造，只有39种query，不冒充独立人工gold。

`python scripts/seed_v3_demo.py`只写output/demo-v3合成数据库与这些公开演示manifest，不连接私人数据库、不调用模型/远程推送。两合成用户有独立项目ID与快照；公共口令仅供本地演示。数据库、原始上传和运行态不打入源码包；新环境运行seed重建。

assets原始样例与artifacts真实输出/截图分开。正式PDF由确认版本生成，不能拿输入PDF冒充输出。NotoSansSC.ttf完整17.8MB及OFL/FONT_SOURCE.json需随源码保留，不能因包大小静默漏掉。
