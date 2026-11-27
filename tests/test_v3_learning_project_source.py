"""Learning source deletion rechecks the selected SQLite or REAL PostgreSQL adapter."""
from fastapi.testclient import TestClient
from test_v3_project_storage import storage
from test_workbench_interview import A,B
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import SourceCreate
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.parsing_contracts import AcceptDraft


def test_learning_project_source_deletion_invalidates_on_read(storage):
    ws,bundle,p,code,runtime=storage;pid=p['project_id'];snapshot=p['current_snapshot'];code.build('alice',pid,snapshot)
    source=ws.add_source('alice',SourceCreate(kind='original_resume',label='Synthetic',text='姓名：合成同学\n技能\nPython'))
    draft=ws.save_draft('alice',ResumeParser().parse(source));v=ws.accept_draft('alice',draft.draft_id,AcceptDraft(title='Synthetic',expected_source_hash=source.content_hash,user_reviewed=True))
    app=create_resume_app(ws,resolve_identity={'alice-token':'alice','bob-token':'bob'}.get,project_persistence=bundle,retrieval_runtime=runtime,task_worker_enabled=False)
    c=TestClient(app)
    r=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json={'request_key':'learning-project-source','version_id':v.version_id,
        'expected_content_hash':v.content_hash,'jd_text':'receipt inputs failures','use_retrieval':True,'track':'project','project_id':pid,'snapshot_id':snapshot})
    assert r.status_code==201,r.text
    view=r.json();sid=view['session_id']
    r=c.post(f'/api/v2/interviews/{sid}/answers',headers=A,json={'request_key':'learning-project-answer','question_id':view['current']['question_id'],
        'expected_revision':0,'answer':'receipt 使用静态源码说明输入输出，边界条件与贡献仍需核实。'})
    assert r.status_code==200,r.text;view=r.json()
    assert c.post(f'/api/v2/interviews/{sid}/finish',headers=A,json={'expected_revision':view['revision']}).status_code==200
    saved=c.post(f'/api/v2/interviews/{sid}/learning-observations',headers=A).json();assert saved['observations']
    o=saved['observations'][0];base='/api/v2/learning/observations/'+o['observation_id']
    assert o['payload']['references'][0]['project_id']==pid
    r=c.post(base+'/actions',headers=A,json={'request_key':'project-confirmed','expected_revision':0,'action':'confirm'});assert r.status_code==200
    r=c.post(base+'/practice',headers=A,json={'request_key':'project-new-practice','expected_revision':1});assert r.status_code==200,r.text
    assert r.json()['project_id']==pid and r.json()['current']['references']==view['turns'][0]['question']['references']
    assert c.delete('/api/v2/projects/'+pid,headers=B).status_code==404
    assert c.delete('/api/v2/projects/'+pid,headers=A).status_code==204
    stale=c.get(base,headers=A).json();assert stale['status']=='invalid' and stale['payload'] is None
    assert all(i['queue_bucket']=='excluded' for i in c.get('/api/v2/learning/observations',headers=A).json())
    assert c.post(base+'/practice',headers=A,json={'request_key':'project-deleted-practice','expected_revision':2}).status_code==409
