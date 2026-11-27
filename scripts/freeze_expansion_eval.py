"""Create AI-candidate fixtures, never human gold or a holdout scoring run."""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.knowledge.evaluation_contract import EvaluationDataset
from job_agent.resume_workspace.public_seed import seed_entries
from scripts.expansion_baseline import FILES


def build():
    documents=[]
    for path,text in FILES.items():
        documents.append(dict(document_id='dev-code/'+path,kind='project_documentation' if path.endswith('.md') else 'code',
            split='dev',text=text,content_hash=sha256(text.encode()).hexdigest(),origin='project_authored_synthetic',
            source_version='expansion-fixture-1',license='CC0-1.0'))
    test_files={
        'lease.py':'def can_publish(current_token, attempt_token, lease_until, now):\n    return current_token == attempt_token and lease_until > now\n',
        'publish.py':'from lease import can_publish\n\ndef publish(current, attempt, expires, now, artifact):\n    if not can_publish(current, attempt, expires, now):\n        raise ValueError("lease_lost")\n    return artifact\n',
        'tests/test_lease.py':'from lease import can_publish\n\ndef test_old_token():\n    assert not can_publish("new", "old", 100, 1)\n\ndef test_expired():\n    assert not can_publish("same", "same", 1, 2)\n',
        'README.md':'# Lease fixture\nThis fixture checks a token and an expiry time before returning an artifact.\nIt does not connect to a database or publish messages.\n',
    }
    for path,text in test_files.items():
        documents.append(dict(document_id='test-code/'+path,kind='project_documentation' if path.endswith('.md') else 'code',
            split='test',text=text,content_hash=sha256(text.encode()).hexdigest(),origin='project_authored_synthetic',
            source_version='expansion-fixture-1',license='CC0-1.0'))
    dev_topics={'checkpoint','idempotency','rrf','ast','citation','provenance'}
    for entry in seed_entries():
        if entry['kind']!='doc':continue
        text=entry['title']+'\n'+entry['body']
        documents.append(dict(document_id=entry['entry_id'],kind='public_knowledge',
            split='dev' if entry['entry_id'].removeprefix('doc-') in dev_topics else 'test',text=text,
            content_hash=sha256(text.encode()).hexdigest(),origin=entry['source_url'],
            source_version=entry['source_version'],license=entry['license']))
    documents=sorted(documents,key=lambda d:d['document_id'])
    snapshot='corpus-'+fingerprint(documents);lookup={d['document_id']:d for d in documents};cases=[]
    def add(split,family,query,ids=(),category='natural_language',requirement='all',reason=None):
        gold=[]
        for name in ids:
            d=lookup[name]
            gold.append(dict(document_id=name,content_hash=d['content_hash'],start_line=1,
                end_line=len(d['text'].splitlines()),quote=d['text']))
        cases.append(dict(case_id=f'{split}-{1+sum(c["split"]==split for c in cases):02}',family=family,source_snapshot=snapshot,
            query=query,category=category,answerable=bool(ids),gold=gold,gold_requirement=requirement,split=split,
            annotation_status='ai_candidate',annotation_note='AI authored candidate; exact source mechanically validated; semantic support and near-duplicate human review pending.',
            unanswerable_reason=reason))
    add('dev','receipt-symbol','save_receipt 的完整定义在哪里？',['dev-code/app/storage.py'],'exact_symbol')
    add('dev','receipt-route','handle 如何把请求交给保存回执的函数？',['dev-code/app/api.py'],'exact_symbol')
    add('dev','receipt-test','test_duplicate 测试引用了哪个函数？',['dev-code/tests/test_storage.py'],'exact_symbol')
    add('dev','receipt-mechanism','重复到达的同一个键为什么不会再写一次？',['dev-code/app/storage.py'])
    add('dev','receipt-mechanism','保存后的回执是从什么容器取回的？',['dev-code/app/storage.py'])
    add('dev','receipt-callchain','从入口到回执存储要跨哪两个文件？',['dev-code/app/api.py','dev-code/app/storage.py'],'multi_evidence')
    add('dev','receipt-verification','实现与重复请求断言分别在哪里？',['dev-code/app/storage.py','dev-code/tests/test_storage.py'],'multi_evidence')
    add('dev','receipt-doc','这个合成项目说明了哪条重复请求规则？',['dev-code/README.md'],'documentation')
    add('dev','receipt-runtime-missing','这个项目在生产环境的每秒吞吐量是多少？',category='unanswerable',reason='No benchmark or production telemetry in the fixed corpus.')
    add('dev','receipt-attribution-missing','能否证明用户独立负责了这个回执服务？',category='unanswerable',reason='Synthetic code has no verified personal contribution evidence.')
    add('dev','receipt-deployment-missing','回执服务的 Kubernetes 部署清单位于哪一行？',category='unanswerable',reason='No deployment manifest exists in the fixed source list.')
    add('dev','checkpoint','程序重启后内存检查点还能用于恢复吗？',['doc-checkpoint'])
    add('dev','checkpoint','跨会话用户偏好与一次运行状态应该分别放在哪里？',['doc-checkpoint'])
    add('dev','unknown-side-effect','外部操作超时后为什么应先核对回执？',['doc-idempotency'])
    add('dev','fusion','不同召回器的分数尺度不同如何融合？',['doc-rrf'])
    add('dev','fusion','融合关键词与向量之后还需要做什么校验？',['doc-rrf'])
    add('dev','syntax','不执行陌生源码可以获得哪些函数位置信息？',['doc-ast'])
    add('dev','citation','新版本出现后历史引用为什么不能直接指向最新文件？',['doc-citation'])
    add('dev','provenance','没有检索到个人证据能否断言候选人不会该技能？',['doc-provenance'])
    add('dev','source-and-support','哈希核对通过和检索相关为什么都不等于个人事实已核实？',['doc-citation','doc-provenance'],'multi_evidence')
    add('test','async-runtime','同步阻塞SDK放进事件循环会有什么问题？',['doc-asyncio'])
    add('test','output-validation','JSON字段类型都对时为什么仍可能不能接受模型结果？',['doc-schema'])
    add('test','js-parser','JS或TS解析器缺失时如何表示结果而不猜调用关系？',['doc-tree-sitter'])
    add('test','transaction-dispatch','提交任务后进程退出为何需要一条持久待投递记录？',['doc-transaction'])
    add('test','async-transaction','客户端取消与数据库提交为什么不能简单理解为副作用已撤销？',['doc-asyncio','doc-transaction'],'multi_evidence')
    add('test','parser-validation','语法树解析成功和Schema结构正确分别还缺什么保证？',['doc-tree-sitter','doc-schema'],'multi_evidence')
    add('test','lease-symbol','can_publish 同时检查哪两个条件？',['test-code/lease.py'],'exact_symbol')
    add('test','lease-route','publish 在返回artifact前如何拒绝失效租约？',['test-code/publish.py','test-code/lease.py'],'multi_evidence')
    add('test','lease-test','旧token和已过期时间的拒绝分别由什么测试说明？',['test-code/tests/test_lease.py'])
    add('test','lease-doc','这份租约样例是否实际连接数据库？',['test-code/README.md'],'documentation')
    add('test','lease-runtime-missing','这份样例在真实Redis崩溃后恢复了几条消息？',category='unanswerable',reason='Fixture explicitly does not connect to a database or publish messages; no run log.')
    add('test','lease-accuracy-missing','面试评价模型在这份数据上达到了多少语义准确率？',category='unanswerable',reason='No interviewer model evaluation or human labels in this corpus.')
    data=dict(dataset_version='expansion-candidates-1',corpus={'snapshot_id':snapshot,'documents':documents},cases=cases,
        policy='AI candidates only. Dev/test families and gold source partitions separated. Only static holdout validation before strategy freeze. Human semantic and near-duplicate review pending. Never tune on test results.')
    return EvaluationDataset.model_validate(data)


if __name__=='__main__':
    path=ROOT/'docs/evaluation/expansion/candidates-v1.json';path.parent.mkdir(parents=True,exist_ok=True)
    data=build();serialized=data.model_dump_json(indent=2,exclude={'cases':{'__all__':{'retrieval_scope'}}})
    if path.exists() and path.read_text(encoding='utf-8')!=serialized:
        raise ValueError('frozen_dataset_changed; create a new version instead of overwriting this one')
    path.write_text(serialized,encoding='utf-8')
    print(json.dumps({'cases':len(data.cases),'dev':sum(c.split=='dev' for c in data.cases),'test':sum(c.split=='test' for c in data.cases),
        'documents':len(data.corpus.documents),'snapshot':data.corpus.snapshot_id,'human_reviewed':0}))
