"""Synthetic real HTTP probe, run build/reload as distinct OS processes."""
import argparse,json,os,sys
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic,sleep
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.expansion_baseline import running,FILES,TEXT


def main():
    import httpx
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.postgres_projects import postgres_persistence
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    from job_agent.resume_workspace.evidence_reference import EvidenceReference
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['build','reload'],required=True)
    parser.add_argument('--state',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume-db',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('output exists')
    if args.phase=='build' and args.state.exists():parser.error('state exists')
    runtime=RetrievalRuntime.from_env();counts={'documents':0,'queries':0}
    if runtime.backend:
        original_documents=runtime.backend.embed_documents;original_query=runtime.backend.embed_query
        def documents(texts):counts['documents']+=1;return original_documents(texts)
        def query(text):counts['queries']+=1;return original_query(text)
        runtime.backend.embed_documents=documents;runtime.backend.embed_query=query
    ws=SqliteResumeRepository(args.resume_db)
    dispatch_mode=os.environ.get('JOB_AGENT_INDEX_DISPATCH','polling')
    bundle=postgres_persistence(os.environ['JOB_AGENT_PROJECT_DSN'],schema=os.environ['JOB_AGENT_PROJECT_SCHEMA'],dispatch_mode=dispatch_mode)
    result={'phase':args.phase,'pid':os.getpid(),'transport':'real_loopback_http','project_backend':'postgresql',
        'model':asdict(runtime.identity) if runtime.identity else None,'checks':[],'queries':[],
        'data':'authored CC0 synthetic only','human_quality_verified':False,'dispatch_mode':dispatch_mode}
    current={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
        for base in ('src','tests','scripts') for p in (ROOT/base).rglob('*.py') if '__pycache__' not in p.parts}
    result['source_identity']=sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()
    try:
        with bundle.database._connection() as db:
            result['server_version']=db.execute('SHOW server_version').fetchone()['server_version']
            result['listen_addresses']=db.execute('SHOW listen_addresses').fetchone()['listen_addresses']
            assert result['listen_addresses']==''
        app=create_resume_app(ws,resolve_identity={'synthetic-a':'alice','synthetic-b':'bob'}.get,
            project_persistence=bundle,retrieval_runtime=runtime,task_worker_enabled=args.phase=='build' and dispatch_mode=='polling')
        result['embedding_calls_after_startup']=dict(counts)
        with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer synthetic-a'},timeout=90) as client:
            def call(method,path,**kw):
                response=client.request(method,path,**kw)
                assert response.status_code<400,(path,response.status_code,response.text[:250])
                return response.json()
            if args.phase=='build':
                p=call('POST','/api/v2/projects',json={'name':'Synthetic PostgreSQL HTTP','license_note':'CC0-1.0'})
                pid=p['project_id'];buffer=BytesIO()
                with ZipFile(buffer,'w') as archive:
                    for path,text in FILES.items():archive.writestr(path,text)
                p=call('POST',f'/api/v2/projects/{pid}/zip',content=buffer.getvalue());snapshot=p['current_snapshot']
                task=call('POST',f'/api/v2/projects/{pid}/index-tasks',json={'snapshot_id':snapshot,'request_key':'s5-real-http-task'})
                tid=task['task_id'];deadline=monotonic()+90
                if dispatch_mode=='redis':
                    import subprocess
                    result['dispatch_processes']=[]
                    for role in ('publish','work'):
                        command=[sys.executable,str(ROOT/'scripts/v3_index_dispatch.py'),role,'--once','--database',str(args.resume_db)]
                        process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        stdout,stderr=process.communicate(timeout=180)
                        result['dispatch_processes'].append({'role':role,'pid':process.pid,'exit_code':process.returncode,
                            'output':stdout.strip(),'stderr_digest':sha256(stderr.encode()).hexdigest()})
                        assert process.returncode==0,(role,process.returncode,stderr[-200:])
                while task['status'] not in ('SUCCEEDED','FAILED'):
                    if monotonic()>deadline:raise RuntimeError('s5_index_timeout')
                    sleep(.1);task=call('GET',f'/api/v2/tasks/{tid}')
                assert task['status']=='SUCCEEDED',task
                result['task']=task;result['checks'].append('zip_snapshot_persistent_task_atomic_publication')
                source=call('POST','/api/v2/sources',json={'kind':'original_resume','label':'Synthetic','text':TEXT})
                draft=call('POST',f"/api/v2/sources/{source['source_id']}/parse",json={'mode':'local_rules'})
                v=call('POST',f"/api/v2/drafts/{draft['draft_id']}/accept",json={'title':'Synthetic PG fixture',
                    'expected_source_hash':source['content_hash'],'user_reviewed':True})
                interview=call('POST',f"/api/v2/resumes/{v['resume_id']}/interviews",json={
                    'request_key':'s5-pg-project-interview','version_id':v['version_id'],'expected_content_hash':v['content_hash'],
                    'use_retrieval':True,'track':'project','project_id':pid,'snapshot_id':snapshot,'jd_text':'save_receipt callers'})
                assert interview['current']['references'] and interview['tool_trace'][0]['tool']=='code_search'
                result['interview_trace']=interview['tool_trace'];result['checks'].append('project_interview_reads_selected_pg_code')
                state={'project_id':pid,'snapshot_id':snapshot,'task_id':tid,'interview_id':interview['session_id']}
            else:
                state=json.loads(args.state.read_text());pid=state['project_id'];snapshot=state['snapshot_id'];tid=state['task_id']
                assert call('GET',f'/api/v2/tasks/{tid}')['status']=='SUCCEEDED'
                assert call('GET',f'/api/v2/interviews/{state["interview_id"]}')['current']['references']==state['interview_references']
                result['checks'].append('new_process_task_and_cross_domain_interview_reference_survived')
            before_documents=counts['documents']
            for method in (('keyword','dense','hybrid') if runtime.backend else ('keyword','code_aware')):
                found=call('POST',f'/api/v2/projects/{pid}/search',json={'snapshot_id':snapshot,'query':'save_receipt callers','method':method,'limit':5})
                assert found['hits']
                for hit in found['hits']:
                    ref=EvidenceReference.model_validate(hit['reference'])
                    assert app.state.code_service.validate_reference('alice',ref)==ref
                result['queries'].append({'method':method,'evidence_ids':[h['reference']['evidence_id'] for h in found['hits']],
                    'references':[h['reference'] for h in found['hits']],'trace':found['retrieval_trace']})
            assert counts['documents']==before_documents
            result['checks'].append('queries_reuse_persisted_vectors_without_document_encoding')
            if args.phase=='build':
                state['queries']=result['queries']
                state['interview_references']=call('GET',f'/api/v2/interviews/{state["interview_id"]}')['current']['references']
                args.state.parent.mkdir(parents=True,exist_ok=True);args.state.write_text(json.dumps(state,indent=2))
            else:
                assert [(q['method'],q['evidence_ids'],q['references']) for q in result['queries']]==[(q['method'],q['evidence_ids'],q['references']) for q in state['queries']]
                result['checks'].append('new_process_same_ranked_chunks_and_exact_references')
            for path in (f'/api/v2/projects/{pid}',f'/api/v2/tasks/{tid}',f'/api/v2/interviews/{state["interview_id"]}'):
                assert client.get(path,headers={'Authorization':'Bearer synthetic-b'}).status_code==404
            result['checks'].append('cross_owner_all_three_resources_404')
            with ws._connection() as db:
                shadow={}
                for table in ('v3_projects','v3_project_snapshots','v3_code_indexes','v3_tasks'):
                    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                    shadow[table]=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] if exists else 0
                assert not any(shadow.values());result['sqlite_shadow_counts']=shadow
            result['checks'].append('no_sqlite_project_index_or_task_shadow_writes')
        result['embedding_calls_total']=counts
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({'phase':args.phase,'checks':len(result['checks']),'queries':len(result['queries']),'model':runtime.identity.model if runtime.identity else None}),flush=True)
    finally:bundle.close()


if __name__=='__main__':main()
