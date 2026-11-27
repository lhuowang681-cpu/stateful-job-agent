"""Versioned 72 AI candidates with exact spans; never manufactures human labels."""
import ast,json,sys
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.freeze_expansion_eval import build as first_build
from job_agent.knowledge.evaluation_contract import EvaluationDataset
from job_agent.knowledge.index_manifest import fingerprint


EXTRA={
 'dev-code/serialize.py':'''import json

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def payload_digest(value):
    from hashlib import sha256
    return sha256(canonical(value).encode("utf-8")).hexdigest()
''',
 'dev-code/rules.py':'''def choose_mode(semantic_configured):
    return "hybrid" if semantic_configured else "keyword"

def needs_rebuild(saved_identity, current_identity):
    return saved_identity != current_identity
''',
 'dev-code/tests/test_rules.py':'''from rules import choose_mode, needs_rebuild

def test_disabled_semantics():
    assert choose_mode(False) == "keyword"

def test_identity_change():
    assert needs_rebuild("old", "new")
    assert not needs_rebuild("same", "same")
''',
 'dev-code/docs/scope.md':'''# Receipt teaching fixture
## Sources
Only the fixed source revision is cited; a source reference is not a performance measurement.
## Limits
There is no durable database and no benchmark in this teaching fixture.
## Budget
Return at most five complete passages. Omit a whole passage when it does not fit the quote budget.
## Verification
A test file contains source assertions. This document does not report executing those tests.
''',
 'test-code/filters.py':'''def bounded_records(records, allowed_ids, limit):
    allowed = [row for row in records if row["id"] in allowed_ids]
    return allowed[:limit]

def visible(row, owner):
    return row["owner"] == owner and not row.get("deleted", False)
''',
 'test-code/tests/test_filters.py':'''from filters import bounded_records, visible

def test_filter_before_limit():
    rows = [{"id": "outside"}, {"id": "inside"}]
    assert bounded_records(rows, {"inside"}, 1) == [{"id": "inside"}]

def test_deleted_row():
    assert not visible({"owner": "alice", "deleted": True}, "alice")
''',
 'test-code/docs/visibility.md':'''# Visibility teaching fixture
## Trust
The allowed IDs come from a trusted server session. User query text is not a permission filter.
## Retention
A deletion marker hides a record; it does not prove physical erasure of archived records.
## Evidence
This fixture has no database connection and no execution logs.
''',
 'test-code/events.py':'''def append_event(events, event_id, payload):
    if event_id in events:
        return events[event_id]
    events[event_id] = payload
    return payload
''',
}


def build():
    documents=[d.model_dump() for d in first_build().corpus.documents]
    for name,text in EXTRA.items():
        documents.append({'document_id':name,'kind':'project_documentation' if name.endswith('.md') else 'code',
            'split':'dev' if name.startswith('dev-') else 'test','text':text,'content_hash':sha256(text.encode()).hexdigest(),
            'origin':'project_authored_synthetic','source_version':'expansion-final-fixture-2','license':'CC0-1.0'})
    documents.sort(key=lambda d:d['document_id']);lookup={d['document_id']:d for d in documents}
    snapshot='corpus-'+fingerprint(documents);cases=[]
    def span(name,start=1,end=None):
        d=lookup[name];lines=d['text'].splitlines(keepends=True);end=end or len(lines)
        assert 1<=start<=end<=len(lines)
        return {'document_id':name,'content_hash':d['content_hash'],'start_line':start,'end_line':end,'quote':''.join(lines[start-1:end])}
    def function(name,symbol):
        node=next(n for n in ast.walk(ast.parse(lookup[name]['text'])) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==symbol)
        return span(name,node.lineno,node.end_lineno)
    def section(name,heading):
        lines=lookup[name]['text'].splitlines();start=next(i for i,line in enumerate(lines) if line==heading)
        end=next((i for i in range(start+1,len(lines)) if lines[i].startswith('#')),len(lines))
        return span(name,start+1,end)
    def add(split,family,query,gold=(),category='natural_language',scope='project',requirement='all',reason=None):
        cases.append({'case_id':f'{split}-final-{1+sum(c["split"]==split for c in cases):02}',
            'family':family,'source_snapshot':snapshot,'query':query,'category':category,'answerable':bool(gold),
            'gold':list(gold),'gold_requirement':requirement,'split':split,'retrieval_scope':scope,
            'annotation_status':'ai_candidate','annotation_note':'AI authored candidate; exact spans checked mechanically. Human support and semantic duplicate review pending.',
            'unanswerable_reason':reason})
    store='dev-code/app/storage.py';api='dev-code/app/api.py';test='dev-code/tests/test_storage.py'
    serial='dev-code/serialize.py';rules='dev-code/rules.py';rtest='dev-code/tests/test_rules.py';scope_doc='dev-code/docs/scope.md'
    dev=[
      ('receipt-symbol','save_receipt 的函数定义在哪个原文范围？',[function(store,'save_receipt')],'exact_symbol'),
      ('receipt-route','handle 把请求交给哪个保存函数？',[function(api,'handle')],'exact_symbol'),
      ('receipt-test','test_duplicate 的两个调用如何构造相同请求？',[function(test,'test_duplicate')],'exact_symbol'),
      ('receipt-mechanism','重复键已经有回执时，如何避开第二次赋值？',[span(store,3,4)]),
      ('receipt-mechanism','第一次请求写入什么值，返回哪份结果？',[span(store,5,6)]),
      ('receipt-callchain','入口函数到回执实现跨越哪些代码位置？',[function(api,'handle'),function(store,'save_receipt')],'multi_evidence'),
      ('receipt-verification','同时找到去重实现与重复请求断言，不把测试存在当执行结果。',[function(store,'save_receipt'),function(test,'test_duplicate')],'multi_evidence'),
      ('receipt-doc','项目README如何概括同一个键再次到达的行为？',[span('dev-code/README.md',2,3)],'documentation'),
      ('serialization-order','字典插入顺序不同时，canonical用什么参数固定序列化键顺序？',[function(serial,'canonical')]),
      ('serialization-hash','payload_digest 把什么内容编码后送给 SHA256？',[function(serial,'payload_digest')],'exact_symbol'),
      ('serialization-chain','从规范JSON到摘要，需要连读哪两个函数？',[function(serial,'canonical'),function(serial,'payload_digest')],'multi_evidence'),
      ('serialization-unicode','序列化如何保留非ASCII字符，再怎样转换成摘要输入字节？',[function(serial,'canonical'),function(serial,'payload_digest')],'multi_evidence'),
      ('fixture-source-policy','设计文档允许引用哪一版源码，引用能否当性能测量？',[section(scope_doc,'## Sources')],'documentation'),
      ('fixture-limit-policy','这份教学样例是否提供持久数据库或benchmark？',[section(scope_doc,'## Limits')],'documentation'),
      ('fixture-budget-policy','不足以容纳下一段原文时，预算约定如何处理该段？',[section(scope_doc,'## Budget')],'documentation'),
      ('fixture-verification-policy','测试源码和文档一起能否证明这些断言实际运行通过？',[function(test,'test_duplicate'),section(scope_doc,'## Verification')],'multi_evidence'),
      ('retrieval-selection','语义后端未配置时，choose_mode返回什么？',[function(rules,'choose_mode')],'exact_symbol'),
      ('cache-invalidation','needs_rebuild怎样判定保存的身份不能复用？',[function(rules,'needs_rebuild')],'exact_symbol'),
      ('retrieval-selection','哪条测试明确断言关闭语义配置会采用keyword？',[function(rtest,'test_disabled_semantics')]),
      ('cache-invalidation','身份变化与身份相同的两个分支，各由什么实现和断言支持？',[function(rules,'needs_rebuild'),function(rtest,'test_identity_change')],'multi_evidence'),
    ]
    for row in dev:add('dev',*row)
    add('dev','receipt-production-unknown','这套回执实现的真实线上P95延迟是多少？',category='unanswerable',reason='The fixed corpus has no benchmark or production telemetry.')
    add('dev','receipt-contribution-unknown','用户独立负责该回执模块的雇佣与贡献证明存在哪里？',category='unanswerable',reason='Source fixtures have no personal attribution or employment records.')
    def public(split,family,query,ids,category='natural_language'):
        add(split,family,query,[span(i) for i in ids],category,scope='public')
    for family,query,ids in [
      ('checkpoint-state','一次线程的继续运行需要保留什么状态？',['doc-checkpoint']),
      ('checkpoint-state','新任务还想使用用户偏好，和当前运行检查点应如何区分？',['doc-checkpoint']),
      ('checkpoint-state','内存Saver退出后，恢复能力还需要什么存储条件？',['doc-checkpoint']),
      ('unknown-side-effect','重复投递如何标识同一个逻辑操作？',['doc-idempotency']),
      ('unknown-side-effect','操作超时但结果未知，应先采取什么核对动作？',['doc-idempotency']),
      ('unknown-side-effect','消费组的待确认消息为什么要与业务完成状态分开看？',['doc-idempotency']),
      ('fusion-rank','BM25与向量分值差很多时，融合依据为什么选排名？',['doc-rrf']),
      ('fusion-rank','加入向量与重排后，选择是否保留需要比较哪些代价与结果？',['doc-rrf']),
      ('static-analysis','提取函数、参数和行位置为什么无需运行陌生项目？',['doc-ast']),
      ('static-analysis','动态绑定与反射无法静态解析时，能否按名字认定执行关系？',['doc-ast']),
      ('citation-version','旧版引用为什么不能重定向到同路径的最新文件？',['doc-citation']),
      ('citation-version','来源被删除后，能否用相似片段替代旧引用？',['doc-citation']),
      ('fact-provenance','公共技术说明、私人源码与个人自述各能证明哪一层？',['doc-provenance']),
      ('fact-provenance','查不到候选人的经历材料，应怎样表达结论和下一步？',['doc-provenance']),
    ]:public('dev',family,query,ids)
    lease='test-code/lease.py';publish='test-code/publish.py';ltest='test-code/tests/test_lease.py'
    filters='test-code/filters.py';ftest='test-code/tests/test_filters.py';visibility='test-code/docs/visibility.md';events='test-code/events.py'
    heldout=[
      ('lease-definition','can_publish 的定义同时涉及哪些输入参数？',[function(lease,'can_publish')],'exact_symbol'),
      ('lease-publish-order','publish的租约校验与返回artifact顺序在哪里？',[function(publish,'publish')],'exact_symbol'),
      ('lease-token-check','任务token不同但时间仍有效时，为什么不能发布？',[function(lease,'can_publish')]),
      ('lease-time-check','到期时间等于now时，租约判断是否仍允许提交？',[function(lease,'can_publish')]),
      ('lease-rejection-tests','哪条断言专门检查旧token被拒绝？',[function(ltest,'test_old_token')]),
      ('lease-rejection-tests','哪条断言专门检查已经过期的时间？',[function(ltest,'test_expired')]),
      ('lease-callchain','返回artifact的路径如何调用token与到期检查？',[function(publish,'publish'),function(lease,'can_publish')],'multi_evidence'),
      ('lease-implementation-tests','检查租约实现及两种拒绝断言，定位全部必要证据。',[function(lease,'can_publish'),function(ltest,'test_old_token'),function(ltest,'test_expired')],'multi_evidence'),
      ('fixture-no-database','从任一原文说明找到：这份租约教学样例没有实际数据库连接。',[span('test-code/README.md',3,3),section(visibility,'## Evidence')],'documentation','any'),
      ('scope-filter-order','bounded_records是在截取limit之前还是之后筛选允许ID？',[function(filters,'bounded_records')],'exact_symbol'),
      ('scope-filter-order','被允许的记录以什么原始顺序出现在有限结果中？',[function(filters,'bounded_records')]),
      ('visibility-deletion','有deleted标记的记录如何从visible判断排除？',[function(filters,'visible')],'exact_symbol'),
      ('visibility-owner','记录owner与查询owner不同，即使未删除会怎样？',[function(filters,'visible')]),
      ('visibility-tests','哪段测试断言被删除记录对原owner也不可见？',[function(ftest,'test_deleted_row')]),
      ('scope-filter-verification','第一条记录不被允许时，如何用实现与断言验证不会占掉limit？',[function(filters,'bounded_records'),function(ftest,'test_filter_before_limit')],'multi_evidence'),
      ('trusted-filter-policy','allowed IDs的可信来源是什么，用户查询文本可以代替吗？',[section(visibility,'## Trust')],'documentation'),
      ('retention-policy','设置删除标记能否证明归档也已物理擦除？',[section(visibility,'## Retention')],'documentation'),
      ('visibility-policy-implementation','同时定位删除标记的可见性实现和保留边界说明。',[function(filters,'visible'),section(visibility,'## Retention')],'multi_evidence'),
      ('event-id-deduplication','append_event 对已经存在的event_id返回什么？',[function(events,'append_event')],'exact_symbol'),
      ('event-id-deduplication','同一个event_id第二次带不同payload，会不会覆盖原值？',[function(events,'append_event')]),
    ]
    for row in heldout:
        family,query,gold,*extra=row;category=extra[0] if extra else 'natural_language';requirement=extra[1] if len(extra)>1 else 'all'
        add('test',family,query,gold,category,requirement=requirement)
    add('test','lease-recovery-unknown','这份固定样例在真实Redis重启后恢复了多少条消息？',category='unanswerable',reason='The fixture has source and assertions but no database, Redis connection, or execution logs.')
    add('test','lease-cost-unknown','部署这份样例的月度服务账单是多少？',category='unanswerable',reason='No deployment, billing, or pricing record exists in the fixed corpus.')
    for family,query,ids in [
      ('async-scheduling','只调用async函数会发生什么，怎样才开始调度？',['doc-asyncio']),
      ('async-scheduling','同步SDK阻塞事件循环时，对其他任务有什么影响？',['doc-asyncio']),
      ('async-scheduling','任务从等待IO变为大量CPU计算时，应重新考虑哪种执行方式？',['doc-asyncio']),
      ('async-scheduling','客户端取消请求为何不能证明远端副作用已撤销？',['doc-asyncio']),
      ('output-schema-validation','JSON字段类型正确为什么还不能当业务事实正确？',['doc-schema']),
      ('output-schema-validation','接受模型材料前，权限与原文版本还需要做什么检查？',['doc-schema']),
      ('output-schema-validation','模型连续修复仍失败时，重试策略应有什么边界？',['doc-schema']),
      ('output-schema-validation','简历数字和职责的支持关系能否由JSON格式成功推出？',['doc-schema']),
      ('js-parser-degradation','JS解析得到语法树，是否同时完成类型检查和运行验证？',['doc-tree-sitter']),
      ('js-parser-degradation','语法插件缺失时，能保留什么结果并应怎样标记？',['doc-tree-sitter']),
      ('js-parser-degradation','降为文本后为什么不能凭猜测补调用关系？',['doc-tree-sitter']),
      ('transaction-outbox','任务与待发送记录为什么应在同一数据库事务里保存？',['doc-transaction']),
      ('transaction-outbox','发布成功但确认丢失为什么还会重复投递，消费者依据什么去重？',['doc-transaction']),
      ('transaction-outbox','本地事务的原子性为什么不能直接保证外部副作用恰好一次？',['doc-transaction']),
    ]:public('test',family,query,ids)
    assert len(cases)==72 and sum(c['split']=='dev' for c in cases)==36
    return EvaluationDataset.model_validate({'dataset_version':'expansion-final-candidates-3','corpus':{'snapshot_id':snapshot,'documents':documents},
        'cases':cases,'policy':'72 AI candidates. Known-scope controlled retrieval; not product routing or human quality. Exact spans; source/family split; holdout scored only after strategy freeze. Human semantic/duplicate review pending. Old v1 results remain separate.'})


def write():
    data=build();path=ROOT/'docs/evaluation/expansion/candidates-v3.json';serialized=data.model_dump_json(indent=2)
    if path.exists() and path.read_text(encoding='utf-8')!=serialized:raise ValueError('frozen_final_dataset_changed; create a new version')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(serialized,encoding='utf-8')
    print(json.dumps({'version':data.dataset_version,'cases':len(data.cases),'documents':len(data.corpus.documents),'dev':36,'test':36,'human_reviewed':0,'snapshot':data.corpus.snapshot_id}))


if __name__=='__main__':write()
