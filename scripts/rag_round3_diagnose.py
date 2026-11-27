"""Freeze separate AI support labels, inspect eight failures, and probe a long symbol.

No legacy dataset/result is rewritten. Labels come from original source text,
not the returned chunks. New metrics are never described as retrieval gains.
"""
import argparse,ast,json,sys
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.evaluation_contract import EvaluationDataset,EvalCase,GoldSpan
from job_agent.knowledge.support_evaluation import SupportLabel,LocatedSpan,evaluate_support

OLD=ROOT/'docs/devlog/evidence/review-20261023'
NEW=ROOT/'docs/devlog/evidence/rag-round3-20261023'
DATA=ROOT/'docs/evaluation/expansion'
LABELS=DATA/'rag-round3-diagnostic-labels-v1.json'


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write_new(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
def datasets():return {k:EvaluationDataset.model_validate(read(DATA/name)) for k,name in (
    ('code','review-real-project-chinese-v3.json'),('design','review-real-design-addendum-v1.json'))}
def span(doc,start,end):return GoldSpan(document_id=doc.document_id,content_hash=doc.content_hash,start_line=start,end_line=end,
                                        quote=''.join(doc.text.splitlines(keepends=True)[start-1:end]))


def freeze():
    data=datasets();code=data['code'];docs={d.document_id:d for d in code.corpus.documents}
    doc=docs['dev-code/src/job_agent/resume_workspace/evidence_pack.py']
    tree=ast.parse(doc.text);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BoundedEvidenceRetriever')
    function=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='retrieve')
    long_case=EvalCase(case_id='diagnostic-long-retrieve',family='diagnostic-seen-evidence-pack',source_snapshot=code.corpus.snapshot_id,
        query='BoundedEvidenceRetriever.retrieve 如何限制工具和引用字符预算，并把不足原因放入结果？',
        category='exact_symbol',answerable=True,gold=[span(doc,function.lineno,function.end_lineno)],split='dev',
        annotation_note='Additional diagnostic only, already-seen source; not new heldout. Whole function exceeds one80-line chunk.',retrieval_scope='project')
    # Explicit minimal source intervals are frozen before per-query score analysis.
    rows=[]
    definitions=[
      ('code','real-test-postgres_projects-1',[(0,269,272)],'natural Chinese; current transaction guard, terminal write and event are jointly necessary'),
      ('code','real-test-retrieval_runtime-2',[(1,45,51)],'Capabilities returns identities/flags and quality_verified=False. Old extra local_model_revision gold is not required by this question; retained in legacy score.'),
      ('code','real-test-learning-2',[(0,106,117),(1,145,149),(2,103,125)],'Assessment completeness, observation invalidation and authenticated source recheck are separate requirements.'),
      ('code','real-test-interview_repository-2',[(0,155,169),(1,172,182),(2,65,71)],'Request no-replay, interview lease/inflight guard and task retry eligibility are all required.'),
      ('code','real-dev-code_rag-2',[(0,163,173),(1,176,181),(2,27,31)],'Range bounds, hash/source reconstruction, owner and citation validation require three pieces.'),
      ('design','design-addendum-S6-8',None,'Design text describes guarantees and limits, not a measured zero-loss operational result.'),
      ('code','real-dev-rewrite-2',[],'No actual hiring-rate measurements in this scope; a citation about rewriting does not establish an outcome.'),
    ]
    for kind,case_id,intervals,reason in definitions:
        dataset=data[kind];case=next(c for c in dataset.cases if c.case_id==case_id);mapping={d.document_id:d for d in dataset.corpus.documents}
        minimum=case.gold if intervals is None else [span(mapping[case.gold[index].document_id],start,end) for index,start,end in intervals]
        symbols=[g for g in case.gold if mapping[g.document_id].kind=='code']
        if case_id=='real-test-retrieval_runtime-2':symbols=[case.gold[1]]
        label=SupportLabel(case_id=case_id,corpus_snapshot=dataset.corpus.snapshot_id,answerable=case.answerable,
            minimal_spans=minimum,symbol_ranges=symbols,rationale=reason)
        rows.append({'dataset':kind,'case':case.model_dump(),'label':label.model_dump()})
    lines=doc.text.splitlines()
    def line(text):return next(i for i,l in enumerate(lines,1) if text in l)
    minimum=[span(doc,line('def call(name,arguments):')+1,line('result=self.invoke(name,arguments,deadline)')),
             span(doc,line('if usage.quote_chars+len(ref.quote)>budget.quote_chars:'),line('items.append(PackItem(')),
             span(doc,line('required_missing=any('),function.end_lineno)]
    label=SupportLabel(case_id=long_case.case_id,corpus_snapshot=code.corpus.snapshot_id,answerable=True,minimal_spans=minimum,
                        symbol_ranges=long_case.gold,rationale='Tool/deadline/model budgets, quote omission and final insufficiency policy are necessary; original function exceeds80 lines.')
    rows.append({'dataset':'code','case':long_case.model_dump(),'label':label.model_dump()})
    write_new(LABELS,{'version':'rag-diagnostic-labels-1','annotation_status':'ai_candidate','human_reviewed':0,
        'legacy_files_unchanged':True,'legacy_source_git':'5d9e94b6efdb2aa5258f8fc52d1dc5231af90f25',
        'data_hashes':{k:sha256((DATA/name).read_bytes()).hexdigest() for k,name in (
            ('code','review-real-project-chinese-v3.json'),('design','review-real-design-addendum-v1.json'))},'cases':rows})
    print(json.dumps({'status':'labels_frozen','cases':len(rows)}))


def probe(args):
    from job_agent.knowledge.research_contract import inspect_bundle,open_services,query_case,VARIANTS
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    m,data,_=inspect_bundle(ROOT,args.bundle)
    runtime=RetrievalRuntime.from_env({'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen','JOB_AGENT_WORKSPACE_EMBEDDING_PATH':args.model_path,
        'JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE':'cuda:1','JOB_AGENT_WORKSPACE_RERANK_PATH':args.rerank_path,'JOB_AGENT_WORKSPACE_RERANK_DEVICE':'cuda:1'})
    code,public,backend=open_services(args.bundle,m,data,'dev',runtime)
    case=EvalCase.model_validate(next(r['case'] for r in read(LABELS)['cases'] if r['case']['case_id']=='diagnostic-long-retrieve'))
    rows=[]
    for variant in VARIANTS:
        found,_,refs=query_case(code,public,m['scopes']['dev'],case,variant)
        rows.append({'case_id':case.case_id,'variant':variant,'repeat':0,'references':refs,'retrieval_trace':found['retrieval_trace'],
                     'warnings':found['warnings'],'elapsed_ms':found['elapsed_ms'],'error':None})
    write_new(args.output,{'status':'completed','kind':'seen-source diagnostic only','rows':rows,'encoder_calls':backend.counts()})


def analyze(args):
    data=datasets();labels=read(LABELS);all_rows=[]
    for stem in ('r4-real-dev-v3','r4-real-test-v3','r4-design-test-v1'):
        all_rows.extend(json.loads(line) for line in (OLD/(stem+'-queries.jsonl')).read_text(encoding='utf-8').splitlines())
    all_rows.extend(read(args.probe)['rows'])
    result=[]
    for annotated in labels['cases']:
        case=EvalCase.model_validate(annotated['case']);label=SupportLabel.model_validate(annotated['label']);dataset=data[annotated['dataset']]
        docs={d.document_id:d for d in dataset.corpus.documents};rows=[]
        report_name='r4-design-test-v1.json' if annotated['dataset']=='design' else 'r4-real-'+case.split+'-v3.json'
        actual_snapshot=read(OLD/report_name)['index_scopes'][case.split]['snapshot_id']
        for row in all_rows:
            if row['case_id']!=case.case_id or row['repeat']!=0:continue
            located=[]
            for ref in row['references']:
                document=docs[case.split+'-code/'+ref['path']]
                located.append(LocatedSpan(span=GoldSpan(document_id=document.document_id,content_hash=ref['content_hash'],
                    start_line=ref['start_line'],end_line=ref['end_line'],quote=ref['quote']),source_version=document.source_version,
                    corpus_snapshot=dataset.corpus.snapshot_id,snapshot_id=ref['snapshot_id']))
            score=evaluate_support(case,dataset.corpus,label,located,snapshot_id=actual_snapshot)
            trace=row['retrieval_trace'];rows.append({'variant':row['variant'],'score':score,'references':row['references'],
                'retrieval_trace':trace,'warnings':row['warnings'],'elapsed_ms':row['elapsed_ms']})
        assert len(rows)==7,case.case_id
        result.append(dict(annotated,results=rows))
    write_new(args.output,{'version':'rag-f1-diagnostic-1','status':'completed','annotation_status':'AI source review only',
        'human_reviewed':0,'labels_sha256':sha256(LABELS.read_bytes()).hexdigest(),'cases':result,
        'note':'New vs legacy score difference is measurement/annotation difference, not a retrieval improvement.'})
    print(json.dumps({'status':'completed','cases':len(result)}))


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['freeze','probe','analyze']);p.add_argument('--bundle',type=Path)
    p.add_argument('--model-path');p.add_argument('--rerank-path');p.add_argument('--output',type=Path);p.add_argument('--probe',type=Path)
    a=p.parse_args()
    if a.command=='freeze':freeze()
    elif a.command=='probe':probe(a)
    else:analyze(a)


if __name__=='__main__':main()
