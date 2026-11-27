"""Bounded offline real-source project interviews; synthetic persona/actions only.

No provider substitution, answer generation, automatic retry or schema repair.
The durable reservation ledger includes failed attempts across pilot/formal runs.
"""
import argparse,json,os,sqlite3,subprocess,sys,time
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.research_contract import CountedBackend,file_hash,runtime_identity
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime

OWNER='synthetic-local-project-study';AUTH={'Authorization':'Bearer synthetic-round3-joint'}
PREFIX='src/job_agent/resume_workspace/'
FILES=[PREFIX+n+'.py' for n in ('code_rag','evidence_reference','evidence_pack','project_evidence',
    'pdf_export','project_import','github_import','parsing','matching','match_repository','repository','learning')]
FILES+=['docs/tech-specs/CURRENT_SPEC.md','docs/tech-specs/CURRENT_SPEC_HISTORY_2026-10-23.md']
STATIC='以上只解释固定快照的静态源码，不能证明实际运行、生产部署、真实录用效果或个人贡献。'
def case(key,query,answer,expected,scope='full',learning=False):
    return dict(case_id=key,query=query,answer=answer,expected_symbol=expected,scope=scope,learning=learning)
PILOT=[
 case('P1','CodeRAGService.read_code_range 的参数检查和返回边界',
      'read_code_range要求1<=start<=end，最多120行；通过projects.read_file读指定owner项目快照，检查越界，切取原文并拒绝超过12000字符。引用ID绑定快照、路径、行号和文件hash，返回EvidenceReference。'+STATIC,'read_code_range'),
 case('P2','EvidenceReference.boundaries 显示什么，未显示什么',
      '我只知道boundaries返回引用边界；具体各字段的意义和失败分支不会解释，暂时无法判断。'+STATIC,'boundaries'),
 case('P3','risk_flags 实际录用率提高了多少？',
      'risk_flags转交requested_boundary_flags。录用率提高50%，系统已经部署。','risk_flags')]
FORMAL=[
 case('T1','PDFRepository._get 如何校验已保存PDF及owner边界',
      '_get用export_id和owner查询，并关联版本与简历，找不到抛pdf_not_found。取得版本后校验文档原始来源；内容hash不符、未确认或PDF字节hash不符都抛pdf_integrity_failed，否则返回row。'+STATIC,'PDFRepository._get',learning=True),
 case('T2','project_import.checked_path 的路径规范和失败边界',
      '先NFC规范化；空值、超过240字符、反斜杠或控制字符等非法字符拒绝。绝对路径、空或点路径分量、末尾点空格、超过14层及Windows保留名拒绝，最后返回POSIX路径。'+STATIC,'checked_path'),
 case('T3','scan_zip 的可见输入上限和未显示部分',
      'scan_zip输入字节为空或超过MAX_ARCHIVE_BYTES就报archive_upload_limit；它读取ZIP目录并受文件数和展开上限约束。对于未展示分支，我不知道全部处理细节。'+STATIC,'scan_zip'),
 case('T4','ResumeParser 中解析入口的可见实现与返回边界',
      '这段我不会解释；需要回到引用再学习，不能判断具体输入检查和返回。'+STATIC,'ResumeParser'),
 case('T5','validate_bundle 对原文证据范围如何验证',
      '只要提供相似意思就会通过，不需要核对原文或版本，可以直接证明我的项目成果。','validate_bundle'),
 case('T6','跨文件 MatchRepository._load 和 validate_bundle 怎样衔接？',
      '应分别核对保存的匹配资料与验证函数。当前只是候选片段，我没有确认每个调用方和分支，不能据此证明跨文件链完整。'+STATIC,'MatchRepository._load'),
 case('T7','跨文件 PDFRepository._get 调用方怎样使用返回结果？',
      '_get可见末尾返回row；当前项目scope只有pdf_export.py，未展示的其他文件调用方无法判断。'+STATIC,'PDFRepository._get',scope='single_pdf'),
 case('T8','PDFRepository._get 实际录用率提升多少？',
      '_get通过owner关联查询PDF记录。实际录用率提高50%，已经上线。','PDFRepository._get'),
 case('T9','GitHubImporter.import_project 是否证明已扫描私有账户并上线？',
      'import_project已经扫描我的所有私有仓库，系统已经部署。','GitHubImporter.import_project'),
 case('T10','checked_path 当前实现与历史计划能否证明目前已经部署？',
      '只能说明引用的checked_path静态路径检查。历史计划是当时状态，不能确认其当前适用性，也没有运行或部署记录。'+STATIC,'checked_path')]

def write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
def append(path,value):
    with Path(path).open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def code_identity():
    values={str(p.relative_to(ROOT)).replace('\\','/'):file_hash(p) for p in sorted((ROOT/'src').rglob('*.py'))}
    return {'files':values,'hash':sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()}
def audit(bundle,manifest,runtime):
    assert file_hash(bundle/'source-only.sqlite')==manifest['database_sha256']
    assert code_identity()==manifest['source_identity']
    assert runtime_identity(runtime)==manifest['retrieval_runtime']
    allowed={'v3_projects','v3_project_snapshots','v3_project_files','v3_code_indexes','v3_code_symbols',
             'v3_code_chunks','v3_code_edges','v3_code_vectors'}
    with sqlite3.connect(bundle/'source-only.sqlite') as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for name in names:
            assert name.replace('_','').isalnum()
            assert name in allowed or db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM v3_projects').fetchone()[0]==len(manifest['scopes'])
        assert db.execute('SELECT COUNT(*) FROM v3_project_snapshots').fetchone()[0]==len(manifest['scopes'])
    ws=SqliteResumeRepository(bundle/'source-only.sqlite');projects=LongTermRepository(ws)
    for scope in manifest['scopes'].values():
        files=projects.files(OWNER,scope['project_id'],scope['snapshot_id'])
        assert {p:sha256(t.encode()).hexdigest() for p,t in files.items()}==scope['file_hashes']
        CodeRAGService(ws,embedding_backend=runtime.backend,retrieval_settings=runtime.settings)._load(OWNER,scope['project_id'],scope['snapshot_id'])

def prepare(args,runtime):
    bundle=args.bundle;bundle.mkdir(parents=True,exist_ok=False)
    ws=SqliteResumeRepository(bundle/'source-only.sqlite');projects=LongTermRepository(ws)
    backend=CountedBackend(runtime.backend);runtime=replace(runtime,backend=backend)
    sources={p:(ROOT/p).read_bytes().decode('utf-8') for p in FILES};scopes={}
    for name,files in [('full',sources),('single_pdf',{PREFIX+'pdf_export.py':sources[PREFIX+'pdf_export.py']})]:
        p=projects.create_project(OWNER,ProjectCreate(name='Real internal source '+name,
            license_note='Project owner authorized local evaluation; no redistribution license asserted'))
        p=projects.publish_files(OWNER,p['project_id'],files,origin='zip')
        report=CodeRAGService(ws,embedding_backend=backend,retrieval_settings=runtime.settings).build(OWNER,p['project_id'],p['current_snapshot'])
        scopes[name]={'project_id':p['project_id'],'snapshot_id':p['current_snapshot'],
            'file_hashes':{p:sha256(t.encode()).hexdigest() for p,t in files.items()},'index_report':report}
    manifest={'version':'round3-joint-source-only-1','source_git':args.source_git,'source_identity':code_identity(),
        'retrieval_runtime':runtime_identity(runtime),'scopes':scopes,'build_embedding':backend.counts(),
        'database_sha256':file_hash(bundle/'source-only.sqlite'),'paid_calls':0,'human_reviewed':0}
    write(bundle/'manifest.json',manifest);audit(bundle,manifest,runtime)
    print(json.dumps({'prepared':True,'build_embedding':backend.counts()},ensure_ascii=False),flush=True)

def run(args,runtime):
    from fastapi.testclient import TestClient
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.parsing import ResumeParser
    from job_agent.llm.providers.local_text import OfflineTextProvider
    manifest=read(args.bundle/'manifest.json');audit(args.bundle,manifest,runtime)
    assert not args.output.exists();args.output.mkdir(parents=True)
    ledger=args.bundle.parent/'f4-generation-reservations.jsonl'
    raw_path=args.output/'model-calls.jsonl'
    class Captured(OfflineTextProvider):
        def generate_structured(self,**kw):
            old=ledger.read_text().splitlines() if ledger.exists() else []
            if len(old)>=40:raise RuntimeError('round3_global_generation_cap')
            reservation={'number':len(old)+1,'output':args.output.name,'trace':kw['trace'].model_dump(),'at':time.time()}
            append(ledger,reservation)
            try:
                result=super().generate_structured(**kw)
                append(raw_path,{'reservation':reservation,'result':result.model_dump(),'measurement':dict(self.calls[-1])})
                return result
            except Exception as e:
                append(raw_path,{'reservation':reservation,'exception':type(e).__name__,'measurement':dict(self.calls[-1]) if self.calls else None});raise
    provider=Captured(args.model,device='cuda:0',max_input_tokens=8192,max_output_tokens=1600,generation_seconds=25)
    write(args.output/'model-identity.json',provider.identity)
    backend=CountedBackend(runtime.backend);runtime=replace(runtime,backend=backend)
    dbpath=args.output/'synthetic-business.sqlite'
    with closing(sqlite3.connect(args.bundle/'source-only.sqlite')) as src,closing(sqlite3.connect(dbpath)) as dst:src.backup(dst)
    ws=SqliteResumeRepository(dbpath)
    cases=PILOT if args.phase=='pilot' else FORMAL
    write(args.output/'frozen-cases.json',{'cases':cases,'source_manifest_sha256':file_hash(args.bundle/'manifest.json'),
        'synthetic_persona_answers_actions':True,'human_gold':0,'paid_calls':0,'no_retry':True,'phase':args.phase})
    report={'phase':args.phase,'source_manifest_sha256':file_hash(args.bundle/'manifest.json'),'source_identity':code_identity(),
        'rows':[],'paid_calls':0,'human_reviewed':0,'generation_is_real':True,'semantic_quality':'unverified','status':'running'}
    def event(name,data):append(args.output/'http-events.jsonl',{'event':name,'data':data})
    try:
      with TestClient(create_resume_app(ws,resolve_identity={'synthetic-round3-joint':OWNER}.get,
              parser=ResumeParser(provider),retrieval_runtime=runtime,task_worker_enabled=False)) as client:
        report['startup_embedding']=backend.counts()
        def post(route,body=None,status=200):
            r=client.post('/api/v2'+route,headers=AUTH,json=body);value=r.json();event(route,{'status':r.status_code,'body':value})
            assert r.status_code==status,(route,r.status_code,value);return value
        source=post('/sources',{'kind':'original_resume','label':'Synthetic persona for local real-source study',
            'text':'姓名：合成同学\n项目经历\n本地原型 | 开发 | 2025\n- 仅练习静态项目源码，不证明个人贡献。'},201)
        draft=post('/sources/'+source['source_id']+'/parse',{'mode':'local_rules'},201)
        version=post('/drafts/'+draft['draft_id']+'/accept',{'title':'Synthetic local source study',
            'expected_source_hash':source['content_hash'],'user_reviewed':True},201)
        for c in cases:
            row={'case':c,'status':'running'};report['rows'].append(row);before=len(provider.calls);counts=backend.counts()
            try:
                scope=manifest['scopes'][c['scope']]
                view=post('/resumes/'+version['resume_id']+'/interviews',{'request_key':uuid4().hex,
                    'version_id':version['version_id'],'expected_content_hash':version['content_hash'],'jd_text':c['query'],
                    'mode':'llm','max_turns':2,'allow_external_processing':True,'use_retrieval':True,'track':'project',
                    'project_id':scope['project_id'],'snapshot_id':scope['snapshot_id']},201)
                initial=view['current'];row['initial']=initial
                row['target_symbol_located']=any(c['expected_symbol'] in initial['prompt'] for _ in [0])
                def answer(v):return post('/interviews/'+v['session_id']+'/answers',{'request_key':uuid4().hex,
                    'question_id':v['current']['question_id'],'expected_revision':v['revision'],'answer':c['answer'],'allow_external_processing':True})
                view=answer(view);row['answered']=view
                if view['status']=='failed':row['status']='model_or_contract_failed';continue
                finished=post('/interviews/'+view['session_id']+'/finish',{'expected_revision':view['revision']});row['finished']=finished
                obs=post('/interviews/'+view['session_id']+'/learning-observations');row['observations']=obs
                row['status']='completed_source_observation'
                if c['learning']:
                    observation=obs['observations'][0];key=observation['observation_id'];actions=[]
                    for action,extra in [('confirm',{}),('correct',{'user_finding':'unsure','note':'Synthetic persona explicitly requests further practice; not a real user judgement.'}),('mark_reviewed',{}),('schedule',{'review_in_days':0})]:
                        observation=post('/learning/observations/'+key+'/actions',{'request_key':uuid4().hex,
                            'expected_revision':observation['revision'],'action':action,**extra});actions.append(observation)
                    practice=post('/learning/observations/'+key+'/practice',{'request_key':uuid4().hex,
                        'expected_revision':observation['revision'],'mode':'llm','allow_external_processing':True})
                    row['synthetic_actions']=actions;row['practice_initial']=practice
                    assert practice['turns']==[] and practice['current']['prompt']==initial['prompt']
                    assert practice['current']['references']==initial['references'] and practice['current']['evidence_boundary']==initial['evidence_boundary']
                    assert practice['current']['question_id']!=initial['question_id']
                    practice=answer(practice);row['practice_answered']=practice
                    if practice['status']=='failed':row['status']='practice_model_or_contract_failed';continue
                    row['practice_finished']=post('/interviews/'+practice['session_id']+'/finish',{'expected_revision':practice['revision']})
                    row['practice_observations']=post('/interviews/'+practice['session_id']+'/learning-observations')
                    row['status']='completed_full_project_learning_loop'
                row['trace']=client.get('/api/v2/interviews/'+view['session_id']+'/trace',headers=AUTH).json()
            except Exception as e:row.update(status='failed',error_type=type(e).__name__,detail=str(e)[:1500])
            finally:
                row['provider_attempts']=len(provider.calls)-before
                row['online_embedding_delta']={k:backend.counts()[k]-counts[k] for k in counts}
                event('case_result',row);print(json.dumps({'case':c['case_id'],'status':row['status'],'calls':row['provider_attempts']},ensure_ascii=False),flush=True)
        report['status']='completed_measurement'
    except Exception as e:report.update(status='failed',error_type=type(e).__name__,detail=str(e)[:1500])
    finally:
        report['embedding_total']=backend.counts();report['provider_measurements']=list(provider.calls)
        report['global_reserved_attempts']=len(ledger.read_text().splitlines()) if ledger.exists() else 0
        write(args.output/'run.json',report)
    print(json.dumps({'status':report['status'],'rows':len(report['rows']),'reserved':report['global_reserved_attempts']},ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','pilot','formal']);p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--output',type=Path);p.add_argument('--source-git');p.add_argument('--model',default='/root/autodl-tmp/models/Qwen2.5-7B-Instruct');a=p.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    runtime=RetrievalRuntime.from_env()
    assert runtime.backend is not None
    if a.phase=='prepare':assert a.source_git;prepare(a,runtime)
    else:assert a.output;run(a,runtime)
if __name__=='__main__':main()
