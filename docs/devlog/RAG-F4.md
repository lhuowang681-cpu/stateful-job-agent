# RAG-F4 · 真实项目与本地模型联合

2026-10-23，有限真实联合及完整项目学习流程已验，模型质量未达稳定。实施前Spec已写，硬上限40本地生成/付费0，先3pilot再冻结正式场景；真实文本模型已调用，模型格式和语义有明显限制，不提前签出整体业务质量。

试跑v1：实际7B三次stop/未截断，三场皆被R1原门禁拒绝（原句不匹配、错用claim-0编号）。云端0，初次源索引2文档编码232片段；应用公共种子另2文档编码20片段，线上6查询。原始输出保留在evidence/rag-round3-20261023/f4-pilot-v1，不计联合通过。第一次提示调整明确ID和逐字原句，未供标签，未改门禁；提示身份rag-project-source-2。相关v3因误把dataclass SkillSpec当Pydantic使用出现2失败，已改为先拼instructions再构造；v4实际50通过/1缺torch跳过，12.70秒。v1测试路径误写无测试，v2沙箱HTTP阻塞后定向停止，均不称通过。


## 正式结果与身份

固定源码Git137cd348b0ab39c3d36c785aff9d1185d67024fb，337份src逐字hash与本轮当前产品代码相同；F2研究排序核心保持不再调。两项目纯源模板（完整白名单14文件/单PDF文件），原始内部源码不标CC0，不执行；纯源库已逐表/owner/snapshot/hash/向量完整性审计。新构建文档2调用，应用公共种子启动另2调用20段；正式线上13查询（总15含启动2），在线文档0。7B在GPU0、Embedding和CrossEncoder在GPU1，模型精确权重/配置hash见model-identity.json，未下载/云端/付费0。

提示第一次调整后pilot-v2：P1/P2完成真实评价、结束及各3观察，P3缺p1/p2被原R1拒绝；5次真实生成。P1模型把静态/运行区别的回答仍判p2不充分，P2对含糊实现给p0 correct，均是模型语义待核/可能误判，不冒称评分准确。

正式10场按固定场景执行，无调参/换题/重试。实际均定位目标符号；4例完成来源观察，6例被门禁拒绝。T2路径规范、T3 ZIP片段、T6多文件候选及T7明确单文件scope完成；T1 PDF与T10历史适用性因quote并非原答被拒，T4不会/T5错误解释/T8录用率/T9部署错前提缺完整逐项评价被拒。10例不是10个成功，也不是回答准确率。T6引用实际2个文件但仍限定片段，不称全链；T7 partial/single scope不代表全仓没有调用方。T8为topic_only/needs_input，T9为partial，T10为topic_only；T10未同时定位历史/当前资料，不能把它写成真实conflict联合已验。F3冲突合同用合成来源，另探真实历史pack并如实记录。

首pilot3调用+二pilot5+正式14=22本地派发，输入62346/输出3973 token，全为stop、无截断；无自动格式修复/运输重试，没有规则接替生成。源码工厂API使用真实仓储/检索/Provider，HTTP为进程内TestClient，不冒称经生产main或网络socket；包后另做真实socket启动。失败场次不推进revision、不生成学习观察，原始模型输出未填correct。人工语义/教学效果null。

T1原定学习失败保留。另在正式结果不变的前提下，用已完成T2进行同题固定来源流程延续，最多2新生成，Spec先登记；不会把独立演示改计为正式T1成功。T2延续实际完成，原正式10例不变。

## 30分钟学习增量

5分钟源码/索引/模型三身份，8分钟`rag_round3_joint.py::run`看真实Provider计量与原API，7分钟`InterviewEngine.execute`看R1拒绝而非修输出，5分钟`LearningRepository.practice_context`看已答Question来源，5分钟读原始失败与有限延续。备选无限重试或换强云端材料未获明确本轮范围，本轮不采用。题面由现有引擎构造，模型只评分/下一步，避免把静态题面当LLM问答能力。

五问：①exit0是否全过？仅表示测量完成，逐行status才是结果。②quote为何必须来自回答？否则模型可拿参考答案替用户作答。③source_sufficient是否事实充分？只是窄题引用几何。④同答案再练是否证明学习？不证明，合成人设与实际用户不同。⑤失败不观察为何仍有价值？防止不完整评价变成持续的虚假画像，但不能宣传模型质量已好。


## 完整流程实际收尾

f4-project-loop-v1完成：T2来源观察p0→合成人设confirm/correct(unsure)/mark_reviewed/schedule0→原APIpractice→同prompt/引用/边界、新question_id、空turns→同7B真实评价与下一步→finish→3条新来源观察。全部independent_mastery=not_established，未认定真人掌握；同一答案再练p1从correct变uncertain，不能拿它宣传教学提升或稳定准确率。实际2新增派发，输入5076/输出295；全轮合计24本地生成、输入67422/输出4268、付费/云端0，预算40剩余未用，不再调模型。

真实原项目历史补探检索到project_evidence.py与当前/历史两Spec，返回conflict/needs_input及version_applicability_unresolved、mixed_current_historical_sources；这是实际API来源状态证据，未执行该混合pack上的额外模型评价，不伪称正式T10已通过混合冲突联合。原始pack保存在延续run.json/history_probe。延续启动公共种子2次文档编码20片段、总3查询，单列不并成正式线上文档0。两份业务copy库均不入包，原正式源索引与run原件不变。

此次有限目标结论：真实项目窄正例、跨文件/不足限定、错前提停止、实际历史状态及一条完整固定来源项目学习已取得证据；不将4/10完成解读成RAG/评分全面达标。缺项仍是小模型明确弱点，语义和人工质量未验。没有请求未授权云端材料、没有绕过原门禁，工程/实验可收口，若以后改用更强模型需另固定材料与预算。
