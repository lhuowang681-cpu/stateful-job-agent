"""Real HTTP: default UI track versus explicit project selection, after heldout.

This measures configured scope routing, not an invented automatic intent router.
No generative provider, user resume, or private remote material is used.
"""
import argparse,json,sqlite3,sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.expansion_baseline import running
from job_agent.knowledge.research_contract import inspect_bundle,OWNER,write_new
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime


def main():
    import httpx
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-path',required=True);p.add_argument('--rerank-path',required=True)
    p.add_argument('--unanswerable-only',action='store_true');args=p.parse_args()
    if args.output.exists():raise ValueError('refuse_overwrite_route_evidence')
    m,data,_=inspect_bundle(ROOT,args.bundle)
    if not (args.bundle/'heldout-reservation.json').exists():raise ValueError('route_probe_only_after_heldout_reservation')
    result={'version':'real-route-http-1','transport':'real_loopback_http','generative_calls':0,
        'requested_mode':'local_demo','scope_selection':'actual UI default job versus explicit project',
        'auto_intent_routing_implemented':False,'model_quality':None,'human_reviewed':0,
        'subset':'unanswerable_only' if args.unanswerable_only else 'all_cases','rows':[],'status':'running'}
    runtime=RetrievalRuntime.from_env({'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen','JOB_AGENT_WORKSPACE_EMBEDDING_PATH':args.model_path,
        'JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE':'cuda:0','JOB_AGENT_WORKSPACE_RERANK_PATH':args.rerank_path,
        'JOB_AGENT_WORKSPACE_RERANK_DEVICE':'cuda:0'})
    result['runtime']=runtime.capabilities()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        temp=args.output.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(args.output)
    try:
        for split in ('dev','test'):
            with TemporaryDirectory(prefix='review-real-route-') as folder:
                copy=Path(folder)/'research.sqlite'
                with sqlite3.connect(args.bundle/(split+'.sqlite')) as original,sqlite3.connect(copy) as target:original.backup(target)
                ws=SqliteResumeRepository(copy)
                app=create_resume_app(ws,resolve_identity={'review-route-synthetic':OWNER}.get,task_worker_enabled=False,demo_only=True,retrieval_runtime=runtime)
                with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer review-route-synthetic'},timeout=120) as c:
                    def call(path,body):
                        response=c.post('/api/v2'+path,json=body)
                        if response.status_code!=201:raise RuntimeError('synthetic_setup_http_'+str(response.status_code))
                        return response.json()
                    source=call('/sources',{'kind':'original_resume','label':'CC0 synthetic route shell',
                        'text':'姓名：合成同学\n项目经历\n本地原型 | 开发 | 2025\n- 参与本地原型开发。'})
                    draft=call('/sources/'+source['source_id']+'/parse',{'mode':'local_rules'})
                    v=call('/drafts/'+draft['draft_id']+'/accept',{'title':'Synthetic route shell','expected_source_hash':source['content_hash'],'user_reviewed':True})
                    scope=m['scopes'][split]
                    for case in (c for c in data.cases if c.split==split):
                        if args.unanswerable_only and case.answerable:continue
                        for selected in (False,True):
                            body={'request_key':str(uuid4()),'version_id':v['version_id'],'expected_content_hash':v['content_hash'],
                                'jd_text':case.query,'mode':'local_demo','max_turns':2,'use_retrieval':True,'track':'project' if selected else 'job'}
                            if selected:body.update(project_id=scope['project_id'],snapshot_id=scope['snapshot_id'])
                            response=c.post('/api/v2/resumes/'+v['resume_id']+'/interviews',json=body)
                            view=response.json();refs=(view.get('current') or {}).get('references',[])
                            row={'case_id':case.case_id,'split':split,'query':case.query,'answerable':case.answerable,
                                'entry':'explicit_project_selection' if selected else 'default_job_track_natural_text',
                                'http_status':response.status_code,'business_status':view.get('status'),'returned_track':view.get('track'),
                                'detail':view.get('detail'),'references':refs,'question':(view.get('current') or {}).get('prompt'),
                                'requested_project_scope_match':bool(refs) and all(r['scope']=='private_project' and r['project_id']==scope['project_id'] and r['snapshot_id']==scope['snapshot_id'] for r in refs),
                                'retrieved_other_scope':any(r['scope']!='private_project' for r in refs),
                                'tool_trace':view.get('tool_trace'),'semantic_answer_quality':None}
                            if view.get('session_id'):
                                with ws._connection() as db:
                                    state=json.loads(db.execute('SELECT state_json FROM rw_interviews WHERE session_id=?',(view['session_id'],)).fetchone()[0])
                                row['retrieval_policies']=[{'answer_policy':p['answer_policy'],'missing':p['missing']}
                                    for p in state.get('evidence_packs',[])]
                            result['rows'].append(row);save()
        result['summary']={entry:{'attempts':sum(r['entry']==entry for r in result['rows']),
            'http_201':sum(r['entry']==entry and r['http_status']==201 for r in result['rows']),
            'requested_project_scope_match':sum(r['entry']==entry and r['requested_project_scope_match'] for r in result['rows']),
            'other_scope':sum(r['entry']==entry and r['retrieved_other_scope'] for r in result['rows'])}
            for entry in ('default_job_track_natural_text','explicit_project_selection')}
        result['status']='completed'
    except Exception as exc:result.update(status='failed',error_type=type(exc).__name__)
    finally:save()
    print(json.dumps({'status':result['status'],'rows':len(result['rows']),'summary':result.get('summary')}))


if __name__=='__main__':main()
