"""Freeze real project source and AI-candidate questions before retrieval scoring."""
import argparse,ast,json,subprocess,sys
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.evaluation_contract import EvaluationDataset
from job_agent.knowledge.index_manifest import fingerprint

# File/family partitions are explicit. Whole functions are intentionally strict
# gold spans: a fragment cannot masquerade as the complete implementation.
FAMILIES=[
 ('dev','code_rag','read_code_range','validate_reference','代码行范围读取如何拒绝过大的请求，并把引用重新绑定到原始内容？','read_code_range 与 validate_reference 分别怎样保证行范围和固定引用有效？','multi'),
 ('dev','code_parser','module_name','is_test_path','Python 文件路径如何转换成模块名？包初始化文件怎样处理？','module_name 和 is_test_path 如何分别识别模块与测试文件？','multi'),
 ('dev','repository','_source','_validate_document','按来源标识读取正文时，怎样同时检查所有者和内容完整性？','_source 与 _validate_document 如何把文档中的事实重新核对到所属来源？','multi'),
 ('dev','claim_audit','deterministic_hard_issues','additional_hard_issues','改稿新增数字、技术或删除参与范围时，程序如何拦截？','deterministic_hard_issues 与 additional_hard_issues 对无依据成果和因果归因分别检查什么？','multi'),
 ('dev','rewrite','conservative_rewrite','materials','本地受限措辞改写实际做哪些替换，是否调用模型？','局部改写已使真实用户录用率提高了多少？','none'),
 ('dev','execution_state','role_context','validate_binding','发给角色的共享上下文如何避免暴露所有者和执行令牌？','共享执行状态已在生产抵挡过多少次越权访问？','none'),
 ('dev','unified_trace','envelope','render','统一追踪信封如何计算根运行用量并标明缺失信息？','该统一追踪服务本季度生产可用率达到多少？','none'),
 ('dev','evidence_pack','make_plan','risk_flags','证据检索计划怎样识别运行指标、跨文件和精确符号意图，并绑定已有检索预算？','证据工具的线上吞吐基准和压测机器配置是什么？','none'),
 ('dev','evidence_reference','boundaries','boundaries','引用的行号顺序和私有所有者字段怎样验证？','EvidenceReference.boundaries 如何处理公开引用与私有引用的 owner_id 要求？','normal'),
 ('dev','sqlite_code_indexes','put_vector','vector','SQLite 代码索引如何保存并读取绑定特定身份的向量载荷？','put_vector 与 vector 的键由哪些作用域字段组成？','normal'),
 ('test','learning','usable_evaluation_source','_payload_for','历史模型评价缺少逐项证据时，为什么不能继续驱动学习观察？','usable_evaluation_source 与 _payload_for 如何共同让不完整旧评价的观察失效？','multi'),
 ('test','interview_repository','answer','claim','面试回答请求怎样按请求键处理重复提交并避免并发执行？','answer 与 claim 分别在哪一步记录请求和领取执行租约？','multi'),
 ('test','long_term','publish_files','read_file','项目文件发布怎样把内容hash绑定快照，并限制文件数、大小和版本数？','publish_files 和 read_file 如何保证读取的是指定快照中的固定内容？','multi'),
 ('test','tasks','guard','heartbeat','索引任务的工作者怎样判断自己仍有有效发布资格？','guard 与 heartbeat 怎样把租约和领取令牌绑定到同一次索引尝试？','multi'),
 ('test','postgres_projects','finish_in_transaction','complete','PG 索引任务如何在当前事务内写入终态和进度？','PostgreSQL 生产集群目前支持多少并发租户及故障切换时延？','none'),
 ('test','index_streams','publish','reclaim','Redis Stream 索引消息发布时只发送哪些定位字段？','Redis 索引调度线上端到端延迟的全年分位数是多少？','none'),
 ('test','index_dispatch','decode_delivery','assert_mode','收到 Stream 消息时怎样拒绝缺失定位字段或伪造的数据类型？','现有 Outbox 已在生产确保零次消息丢失的证据是什么？','none'),
 ('test','project_storage','persistence_from_env','sqlite_persistence','项目持久化如何按显式环境配置选择 SQLite 或 PostgreSQL？','所有客户的数据已经完成无损跨库迁移的生产验收报告在哪里？','none'),
 ('test','public_knowledge','public_entry','safe_entry','公开知识条目怎样移除私有题目评分字段，防止泄漏参考要点？','public_entry 和 safe_entry 在公开条目与私有题目字段边界上各负责什么？','normal'),
 ('test','retrieval_runtime','local_model_revision','capabilities','本地检索模型目录怎样形成可核对的权重配置版本身份？','capabilities 暴露了哪些实际加载身份，又如何声明质量尚未独立验证？','normal'),
]


def freeze(output):
    if output.exists():raise ValueError('refuse_overwrite_real_corpus')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    docs=[];functions={};paths={}
    for split,module,*_ in FAMILIES:
        relative='src/job_agent/resume_workspace/'+module+'.py'
        path=ROOT/relative;text=path.read_text(encoding='utf-8')
        document_id=split+'-code/'+relative
        if document_id in paths:raise ValueError('duplicate_source_family')
        paths[document_id]=relative
        tree=ast.parse(text)
        # Prefer implementation methods over one-line nested HTTP route wrappers.
        symbols={}
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                old=symbols.get(node.name)
                if old is None or node.end_lineno-node.lineno>old.end_lineno-old.lineno:symbols[node.name]=node
        functions[module]=(document_id,text,symbols)
        docs.append({'document_id':document_id,'kind':'code','split':split,'text':text,
            'content_hash':sha256(text.encode()).hexdigest(),'origin':relative,
            'source_version':revision,'license':'Project owner authorized internal evaluation; no redistribution license asserted'})
    for split,name in [('dev','CURRENT_SPEC.md'),('test','CURRENT_SPEC_HISTORY_2026-10-23.md')]:
        relative='docs/tech-specs/'+name;text=(ROOT/relative).read_text(encoding='utf-8')
        docs.append({'document_id':split+'-code/'+relative,'kind':'project_documentation','split':split,'text':text,
            'content_hash':sha256(text.encode()).hexdigest(),'origin':relative,'source_version':revision,
            'license':'Project owner authorized internal evaluation; no redistribution license asserted'})
    snapshot='corpus-'+fingerprint(sorted(docs,key=lambda d:d['document_id']))
    cases=[]
    def gold(module,symbol):
        docid,text,symbols=functions[module];node=symbols[symbol];lines=text.splitlines(keepends=True)
        return {'document_id':docid,'content_hash':sha256(text.encode()).hexdigest(),
            'start_line':node.lineno,'end_line':node.end_lineno,'quote':''.join(lines[node.lineno-1:node.end_lineno])}
    for split,module,one,two,q1,q2,kind in FAMILIES:
        for i,query in enumerate((q1,q2)):
            answerable=not(i==1 and kind=='none')
            spans=[gold(module,one)] if answerable else []
            if i==0 and module=='evidence_pack':spans.append(gold(module,two))
            if i==1 and answerable and two!=one:spans.append(gold(module,two))
            cross={
                'code_rag':('evidence_reference','boundaries','引用字段边界由 EvidenceReference.boundaries 怎样补充约束？'),
                'code_parser':('code_rag','_chunks','解析出的符号范围在 _chunks 中怎样转为分块？'),
                'repository':('evidence_reference','boundaries','引用对象的 boundaries 校验与来源正文核验有何不同？'),
                'claim_audit':('rewrite','hard_constraints','改写模块 hard_constraints 怎样复用这些约束？'),
                'learning':('interview_repository','_load','原面试 _load 如何重查来源身份？'),
                'interview_repository':('tasks','claim','与索引任务 claim 的领取条件相比有哪些差别？'),
                'long_term':('project_storage','sqlite_persistence','sqlite_persistence 怎样把项目和索引仓储接到同一持久化配置？'),
                'tasks':('postgres_projects','guard','PG 后端 guard 怎样实现相同的发布资格约束？')}
            if i==1 and kind=='multi':
                other,symbol,extra=cross[module];spans.append(gold(other,symbol));query+=' '+extra
            category='unanswerable' if not answerable else 'multi_evidence' if i==1 and kind=='multi' else 'exact_symbol' if i else 'natural_language'
            cases.append({'case_id':f'real-{split}-{module}-{i+1}','family':split+'-'+module,
                'source_snapshot':snapshot,'query':query,'category':category,'answerable':answerable,'gold':spans,
                'gold_requirement':'all','split':split,'annotation_status':'ai_candidate','retrieval_scope':'project',
                'annotation_note':'AI-authored candidate from actual project source. Whole implementation functions are strict gold; human semantic verification deferred.',
                'unanswerable_reason':None if answerable else 'Frozen source describes implementation, not production measurements, actual user outcomes, or completed production migration.'})
    data={'dataset_version':'review-real-project-chinese-3','corpus':{'snapshot_id':snapshot,'documents':docs},'cases':cases,
        'policy':'40 AI candidates; 20 dev/20 new test; disjoint source-file families; current design dev and dated history test distractor; no generated answers in corpus; human reviewed 0.'}
    validated=EvaluationDataset.model_validate(data)
    assert len(validated.cases)==40 and sum(not c.answerable for c in validated.cases)==8
    assert sum(c.category=='multi_evidence' for c in validated.cases)==8
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    audit={'dataset_sha256':sha256(output.read_bytes()).hexdigest(),'corpus_snapshot':snapshot,'source_revision':revision,
        'documents':len(docs),'corpus_characters':sum(len(d['text']) for d in docs),'cases':40,'human_reviewed':0,
        'family_source_overlap':sorted({d['origin'] for d in docs if d['split']=='dev'} & {d['origin'] for d in docs if d['split']=='test'}),
        'source_hashes':{d['origin']:d['content_hash'] for d in docs},'evaluation_answers_in_corpus':False,
        'gold_granularity':'complete implementation function; strict and potentially harder than minimal answer spans',
        'semantic_support_verified':False,'status':'frozen_not_scored'}
    output.with_suffix('.audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k!='source_hashes'}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();freeze(args.output)
