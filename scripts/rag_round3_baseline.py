"""Actual existing project-interview entry, default BM25, copied real-source index."""
import argparse,json,sqlite3,sys
from pathlib import Path
from contextlib import closing
from tempfile import TemporaryDirectory
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.expansion_baseline import running
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.api import create_resume_app
from job_agent.knowledge.research_contract import inspect_bundle,OWNER


def main():
    import httpx
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--observed-policy-change',action='store_true')
    args=parser.parse_args();assert not args.output.exists()
    manifest,data,current_algorithm=inspect_bundle(ROOT,args.bundle,strict_algorithm=not args.observed_policy_change)
    scope=manifest['scopes']['dev'];cases={c.case_id:c for c in data.cases}
    report={'version':'rag-f0-baseline-1','configuration':'default BM25; embedding/rerank/generation disabled',
            'product':'explicit track/snapshot -> practice topics; not question-answer chat',
            'paid_calls':0,'generative_calls':0,'rows':[],'human_reviewed':0,'status':'running'}
    report.update(prepared_algorithm=manifest['algorithm_identity'],current_algorithm=current_algorithm,
                  observed_policy_change=args.observed_policy_change)
    try:
        with TemporaryDirectory(prefix='rag-f0-') as folder:
            path=Path(folder)/'research-copy.sqlite'
            with closing(sqlite3.connect(args.bundle/'dev.sqlite')) as original,closing(sqlite3.connect(path)) as target:original.backup(target)
            ws=SqliteResumeRepository(path)
            app=create_resume_app(ws,resolve_identity={'round3-synthetic-shell':OWNER}.get,task_worker_enabled=False,demo_only=True)
            with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer round3-synthetic-shell'},timeout=45,trust_env=False) as client:
                def post(route,body,status=201):
                    response=client.post('/api/v2'+route,json=body);assert response.status_code==status,(route,response.status_code)
                    return response.json()
                source=post('/sources',{'kind':'original_resume','label':'Synthetic shell for real project study',
                    'text':'姓名：合成同学\n项目经历\n本地原型 | 开发 | 2025\n- 仅以项目源码进行练习，不证明个人贡献。'})
                draft=post('/sources/'+source['source_id']+'/parse',{'mode':'local_rules'})
                version=post('/drafts/'+draft['draft_id']+'/accept',{'title':'Synthetic shell','expected_source_hash':source['content_hash'],'user_reviewed':True})
                for case_id,track in [('real-dev-code_rag-2','job'),('real-dev-code_rag-2','project'),('real-dev-rewrite-2','project')]:
                    body={'request_key':uuid4().hex,'version_id':version['version_id'],'expected_content_hash':version['content_hash'],
                          'jd_text':cases[case_id].query,'mode':'local_demo','max_turns':2,'use_retrieval':True,'track':track}
                    if track=='project':body.update(project_id=scope['project_id'],snapshot_id=scope['snapshot_id'])
                    response=client.post('/api/v2/resumes/'+version['resume_id']+'/interviews',json=body)
                    view=response.json();row={'case_id':case_id,'track':track,'topic':cases[case_id].query,'http_status':response.status_code,'view':view}
                    if view.get('session_id'):
                        with ws._connection() as db:state=json.loads(db.execute('SELECT state_json FROM rw_interviews WHERE session_id=?',(view['session_id'],)).fetchone()[0])
                        row.update(evidence_packs=state['evidence_packs'],plan=state['plan'],messages=state['messages'])
                    report['rows'].append(row)
        assert report['rows'][0]['view']['track']=='job'
        assert report['rows'][1]['http_status']==201 and report['rows'][1]['view']['current']['references']
        report['status']='completed'
    except Exception as exc:report.update(status='failed',error_type=type(exc).__name__)
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'status':report['status'],'rows':[(r['track'],r['http_status']) for r in report['rows']]}))
    if report['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
