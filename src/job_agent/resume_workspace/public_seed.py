"""Original, CC0 teaching summaries/questions. Linked docs are not mirrored.

Curated 2026-10-20. Official links support background; project design advice is
our synthesis, not a verbatim statement or guarantee by the linked publishers.
"""
TOPICS=[
 ('checkpoint','Checkpoint与长期记忆',['LangGraph','checkpoint','state','memory','状态','恢复'],
  'https://docs.langchain.com/oss/python/langgraph/persistence','LangGraph rolling docs; checked 2026-10-20',
  'Checkpoint保存一次线程运行的状态，便于继续对话、中断恢复和人工交互。Store保存跨线程使用的业务信息，例如用户偏好。内存Saver在进程退出后会丢失，持久化需要相应存储。本项目的业务版本、岗位档案与执行检查点是不同数据，不能把保存聊天记录说成实现了全部恢复机制。',
  'Checkpoint和跨会话长期记忆分别应该保存什么？',
  [('线程运行状态',['线程','thread','当前任务']),('跨会话业务信息',['跨会话','偏好','长期记忆','store']),('内存与持久化边界',['持久化','重启','内存'])],
  ['请说明你会把待执行动作保存在什么范围。','下一次新任务开始时，哪些信息还需要使用？','服务重启后，两类数据分别会怎样？']),
 ('idempotency','外部超时与幂等回执',['幂等','idempotency','request_id','回执','超时'],
  'https://redis.io/docs/latest/commands/xreadgroup/','Redis rolling command reference; checked 2026-10-20',
  '消费组的待确认消息需要与业务完成状态区分。本项目采用的可靠性原则是：相同逻辑操作使用稳定请求键，先查回执；外部请求超时不等于操作失败。数据库状态无法和任意外部服务形成一个本地事务，结果未知时应查询、核对或等待人工处理，不能盲目重发。该设计原则是本项目综合，不是Redis提供跨系统恰好一次保证。',
  '外部请求超时后，为什么不能直接把任务当失败重试？',
  [('稳定操作标识',['幂等','请求键','request_id','idempotency']),('核对回执和实际状态',['回执','查询','核对']),('未知结果不盲目重放',['未知','不盲目','人工','uncertain'])],
  ['两次投递怎样判断是否属于同一个逻辑动作？','你会去哪里核对上次动作的结果？','如果现在无法确认结果，下一步应怎样选择？']),
 ('asyncio','协作式并发与阻塞边界',['asyncio','Python','协程','并发','阻塞'],
  'https://docs.python.org/3.12/library/asyncio-task.html','Python 3.12 documentation',
  '仅调用async函数会得到协程对象，不会自动执行；需要await或调度Task。协程适合可等待的IO任务。同步阻塞库直接运行在事件循环里会拖住其他任务，可考虑受限线程；CPU密集计算应根据运行环境另选进程等方案。取消请求也需要处理清理工作，不能把客户端超时理解为远端副作用已撤销。',
  'Python接口服务里，asyncio、线程和进程应怎样选择？',
  [('IO与协作式等待',['IO','I/O','等待','await']),('同步阻塞不能拖住循环',['阻塞','线程','blocking']),('计算任务的执行方式',['CPU','进程','计算'])],
  ['请求时间主要消耗在哪里？','同步SDK调用期间，其他请求能否继续？','如果工作变成大量计算，方案会怎样调整？']),
 ('schema','结构化输出与业务校验',['Pydantic','schema','JSON','校验','结构化'],
  'https://fastapi.tiangolo.com/tutorial/body/','FastAPI rolling tutorial; checked 2026-10-20',
  'Pydantic模型约束请求字段、类型和取值，FastAPI据此解析请求体。字段结构正确不代表业务事实正确；还需验证owner、版本、引用原文和状态迁移。模型输出同样要做Schema与业务两层校验，修复与重试都应有限。简历中数字、职责和来源是否支持，需要额外审查，不能由JSON格式成功推出。',
  '模型已经返回符合JSON Schema的内容，为什么仍然可能不能使用？',
  [('结构与业务语义分开',['结构','语义','业务']),('确定性来源和权限检查',['来源','权限','hash','owner','原文']),('有限重试与拒绝',['上限','有限','拒绝','停止'])],
  ['可以举一个字段类型正确但业务错误的例子吗？','系统接受内容前，还应检查哪些材料？','连续修复仍失败时，如何终止而不误报成功？']),
 ('rrf','关键词、向量与RRF融合',['BM25','RRF','hybrid','检索','融合'],
  'https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion','Elasticsearch rolling reference; checked 2026-10-20',
  '关键词召回适合准确术语，向量召回用于语义相近表达。不同检索器分数尺度通常不能直接相加，RRF按排名倒数贡献融合；参数和候选深度会影响结果。融合后仍要去重并验证引用。是否保留向量或重排，应在相同查询与标注下比较召回、成本和失败，不预设更复杂一定更好。本项目没有因此部署Elasticsearch。',
  'BM25和向量分数不在同一尺度时，为什么可以考虑RRF？',
  [('按排名融合',['排名','rank','倒数']),('精确与语义互补',['精确','关键词','语义']),('同口径评测成本',['评测','成本','召回'])],
  ['两个分数相差很大时，直接相加可能出现什么？','准确函数名和自然语言描述是否适合同一种检索？','你会用什么证据判断融合值得保留？']),
 ('ast','AST符号与静态分析边界',['AST','Python','符号','静态','源码'],
  'https://docs.python.org/3.12/library/ast.html','Python 3.12 documentation',
  'ast.parse将Python文本解析为语法树，可提取函数、类、参数和行位置，不需要导入并执行代码。静态分析能解析部分导入与直接调用；对象动态绑定、反射或运行时修改不能只按名字猜。本项目把这些边标为静态可解析引用，不能据此声称函数实际执行过，测试文件存在也不代表测试通过。',
  '怎样从项目源码建立可引用的符号索引？静态调用图有什么局限？',
  [('解析而非执行',['AST','解析','语法树']),('符号与原文位置',['符号','行号','位置','函数']),('动态行为需要克制',['动态','反射','不能推断','不等于运行'])],
  ['导入一个陌生项目模块来收集函数有什么风险？','回答引用怎样回到准确的文件范围？','如果对象的方法是在运行时决定的，该如何表示？']),
 ('tree-sitter','JS/TS语法解析与降级',['Tree-sitter','TypeScript','JavaScript','TSX','解析'],
  'https://tree-sitter.github.io/py-tree-sitter/','py-tree-sitter 0.26 documentation',
  'Tree-sitter的语言语法和解析器可构建语法树，定位JS、TS及TSX中的声明。解析成功不等于类型检查或程序运行成功。本项目提取函数、方法和导入引用，遇到语法错误或插件缺失会明确降级为文本，不构造猜测的关系。引用仍依赖快照、文件哈希与行原文校验。',
  'JS/TS代码解析失败时，怎样降级而不误导后续Agent？',
  [('语言解析器和节点',['语法','节点','parser','Tree-sitter']),('降级状态要明确',['降级','文本','标记']),('不伪造调用关系',['关系','不能猜','静态','不伪造'])],
  ['解析器得到的节点能证明类型正确吗？','哪些信息还能作为文本检索线索？','下游应怎样知道某条调用关系没有得到解析支持？']),
 ('transaction','业务事务与消息投递',['PostgreSQL','事务','Outbox','原子','transaction'],
  'https://www.postgresql.org/docs/14/tutorial-transactions.html','PostgreSQL 14 tutorial',
  '事务把一组数据库修改作为整体提交或回滚。任务记录与待投递消息可以在同一数据库事务内落盘，再由发布者发送消息；这就是项目旧后端Outbox路径的设计。发布者中断或确认丢失仍可能造成重复投递，消费者必须依据持久任务状态和操作键去重。本地数据库事务不能直接保证外部消息系统与副作用恰好一次。',
  '为什么任务记录和消息投递之间需要考虑Outbox以及消费者去重？',
  [('同一事务保存任务与待发送记录',['事务','原子','Outbox']),('投递仍可能重复',['重复','重投','至少一次']),('消费者按状态和操作键去重',['去重','幂等','请求键','状态'])],
  ['数据库提交后、发送消息前进程退出，会发生什么？','消息发送成功但回执丢失时，应该预期什么？','消费者如何判断此前是否已经处理过？']),
 ('provenance','检索相关性与事实支持',['RAG','证据','来源','支持','相关性'],
  'https://docs.langchain.com/oss/python/deepagents/retrieval','Retrieval rolling documentation; checked 2026-10-20',
  '检索用于在查询时提供相关外部上下文，减少一次性塞入全部材料的需求。相关片段本身不是事实支持判定。本项目把公共技术解释、私人源码和个人自述分域处理：公共资料不能证明用户有该技能，代码只能定位某版实现，自述仍需核实。缺证据应表达不确定或请求补充，不能推断用户没有能力。该事实分级是本项目约束。',
  '检索到技术相关文档后，为什么不能直接把该技术写进用户简历？',
  [('相关不等于支持',['相关','支持','不等于']),('公共知识与个人事实分离',['公共','自述','经历','用户']),('缺材料时保留不确定',['不确定','补充','缺证据','不能推断'])],
  ['资料能够说明技术概念，能够说明用户的什么？','项目代码存在时，还缺少哪些个人贡献信息？','没有检索到材料时，应怎样向用户表达？']),
 ('citation','快照引用、哈希与版本',['SHA256','引用','commit','快照','hash'],
  'https://docs.python.org/3.12/library/hashlib.html','Python 3.12 documentation',
  '内容哈希便于核对文本身份，但哈希一致不能证明真实经历或语义结论。本项目的代码引用绑定owner、项目、快照、commit、路径、行范围与原文；引用旧版时不能悄悄指向最新文件。索引重建可替换派生结构，历史源码快照保持不变；删除来源后，旧引用应不可解析，而非回退到相似资料。',
  '文件更新或重建索引后，怎样保证历史代码引用没有悄悄变义？',
  [('固定不可变版本',['版本','commit','快照']),('核对哈希行号原文',['hash','哈希','原文','行号']),('删除失效不替换来源',['失效','删除','不能替换','不回退'])],
  ['只保存文件路径会有什么问题？','检索结果展示之前，需要核对哪些位置与内容？','原始来源已经删除时，应该怎样处理旧答案？']),
]


def seed_entries():
    result=[]
    for key,title,tags,url,version,body,prompt,points,followups in TOPICS:
        base={'tags':tags,'source_url':url,'source_version':version,'license':'CC0-1.0',
              'content_basis':'project_authored_summary_not_official_quote','updated_at':'2026-10-20','applicable_role':'AI Agent / Python后端实习'}
        result.append({**base,'entry_id':'doc-'+key,'kind':'doc','title':title,'body':body,'difficulty':'intermediate'})
        result.append({**base,'entry_id':'question-'+key,'kind':'question','title':title+' · 练习','body':prompt,'difficulty':'intermediate',
                       'technical_doc_id':'doc-'+key,'answer_points':[p for p,_ in points],
                       'aliases':[a for _,a in points],'followups':followups})
    return result
