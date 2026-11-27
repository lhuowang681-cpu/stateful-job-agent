# V3 数据登记

当前不读取私人简历、JD、原始数据库或密钥。现有冻结集保持原样；V3 使用明确标识的合成资料以及带来源和许可的公共项目。

| 数据 | 用途 | 来源/许可 | 状态 |
|---|---|---|---|
| 旧 Evidence/R12 | 历史复现 | 保留旧报告的原来源和范围 | 不改标签、不转用于V3质量结论 |
| V3 synthetic-dev | 开发与安全集成 | 原创CC0 6文件Python/TS回执样例 | 已落盘docs/demo/assets/synthetic-receipts.zip，非冻结题调参样本 |
| V3 synthetic-frozen-v1 | 确定性检索/来源对照 | 原创CC0、机械gold，非人工语义盲评 | F0已冻结，40题×5方法已跑 |
| 公共开源项目 | 导入/符号/引用集成 | Starlette0.46.2，BSD-3-Clause，固定commit/归档hash | 104文件真实导入，未执行上游测试，非人工语义gold |
| public-tag-diagnostic-v1 | 术语索引开发诊断 | 原创10题公开tags派生40项/39不同query | 实现后生成，不称冻结盲测；修复前后保留同标签结果 |
| 真实模型质量样本 | JD/改写/面试效果 | 需授权与人工gold | LIVE_PENDING |

## 首个已冻结集合

`tests/fixtures/v3_frozen/code_queries.json`：40题（20 exact、20 cross-file），40个合成Python文件，CC0-1.0，程序构造直接import调用gold；不代表语义改写或真实面试效果。SHA256 `b1e59321b5d6631f3860e3a6fc461b70eed363d0ecf0ef493292ab0f6686edec`。未接触模型提示词前冻结。禁止修改此版标签；新增资料单独版本。

公开Starlette归档SHA256 `792a950c58e4727b8e7afe728a4b68b4ddc24d91ac28441bac3c37b59caea881`，commit `4a811767bcba6e933bf7a8b48edef5993ce8948e`；release URL/许可/安全扫描统计见docs/demo/assets/starlette-public-manifest.json。模型不接收任何私人源码；导入不推断用户贡献。
公共诊断`tests/fixtures/v3_diagnostic/public_tag_queries.json` SHA256 `255bf47b9ca165efb96eb97fdab551059f2e9591ede6f734b849a974543d9486`，gold是精确tag membership，同标签可能对应多题；不用于宣传语义相关性。建议的30组真实JD/25改写/20轮人工盲评尚不足，明确LIVE_PENDING，不虚构金标补数。
