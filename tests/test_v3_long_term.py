from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import stat
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.long_term import LongTermRepository,JobCreate,JobUpdate,JobLink,ProjectCreate,ProjectDocument
from job_agent.resume_workspace.project_import import scan_zip,checked_path
from job_agent.resume_workspace.contracts import SourceCreate,ResumeCreate,ResumeDocument,ResumeFact,SourceSpan,PersonalInfo,VersionCreate
from job_agent.resume_workspace.interview_repository import InterviewRepository
from job_agent.resume_workspace.interview_collaboration import InterviewEngine
from job_agent.resume_workspace.interview_contracts import InterviewStart


def archive(files,*,compression=0):
    out=BytesIO()
    with ZipFile(out,'w',compression=compression) as z:
        for name,text in files.items():z.writestr(name,text)
    return out.getvalue()


@pytest.fixture
def data(tmp_path):
    repo=SqliteResumeRepository(tmp_path/'workspace.sqlite');store=LongTermRepository(repo)
    def resume(owner):
        s=repo.add_source(owner,SourceCreate(kind='user_statement',label='合成',text='演示同学'))
        fact=ResumeFact(fact_id='name',text=s.text,source=SourceSpan(source_id=s.source_id,content_hash=s.content_hash,start=0,end=len(s.text)))
        return repo.create_resume(owner,ResumeCreate(title='合成',document=ResumeDocument(personal=PersonalInfo(name=fact))))
    return repo,store,resume('alice'),resume('bob')


def job(store,owner='alice',key='job-create-001'):
    return store.create_job(owner,JobCreate(request_key=key,company='合成科技',title='实习',jd_text='Python FastAPI'))


def test_job_idempotency_timeline_restart_and_two_versions(data):
    repo,store,a,_=data;j=job(store)
    assert job(store)['job_id']==j['job_id']
    updated=store.update_job('alice',j['job_id'],JobUpdate(request_key='event-apply-01',expected_revision=1,stage='applied',note='合成进展'))
    again=store.update_job('alice',j['job_id'],JobUpdate(request_key='event-apply-01',expected_revision=1,stage='applied',note='合成进展'))
    assert updated==again and len(updated['events'])==2
    b=repo.save_version('alice',a.resume_id,VersionCreate(expected_parent_version_id=a.version_id,document=a.document))
    for v in (a,b):store.link_job('alice',j['job_id'],JobLink(resume_id=v.resume_id,version_id=v.version_id))
    reopened=LongTermRepository(SqliteResumeRepository(repo.path)).get_job('alice',j['job_id'])
    assert reopened['stage']=='applied' and {l['version_id'] for l in reopened['links']}=={a.version_id,b.version_id}


def test_job_request_conflict_stale_revision_and_concurrency(data):
    _,store,_,_=data;j=job(store)
    with pytest.raises(WorkspaceConflict,match='key_conflict'):
        store.create_job('alice',JobCreate(request_key='job-create-001',company='另一公司',title='实习',jd_text='Python'))
    def change(i):
        try:return store.update_job('alice',j['job_id'],JobUpdate(request_key=f'job-change-{i:03d}',expected_revision=1,stage='applied'))
        except WorkspaceConflict:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(change,[1,2]))
    assert sum(r is not None for r in results)==1
    assert len(store.get_job('alice',j['job_id'])['events'])==2


def test_foreign_jobs_versions_sessions_and_project_snapshots_rejected(data):
    repo,store,a,b=data;j=job(store)
    with pytest.raises(WorkspaceNotFound):store.get_job('bob',j['job_id'])
    with pytest.raises(WorkspaceNotFound):store.link_job('alice',j['job_id'],JobLink(resume_id=b.resume_id,version_id=b.version_id))
    p=store.create_project('alice',ProjectCreate(name='私人项目'))
    p=store.import_zip('alice',p['project_id'],archive({'src/a.py':'def a():\n    return 1\n'}))
    with pytest.raises(WorkspaceNotFound):store.files('bob',p['project_id'],p['current_snapshot'])
    other=store.create_project('bob',ProjectCreate(name='相同名字'))
    with pytest.raises(WorkspaceNotFound):store.files('bob',other['project_id'],p['current_snapshot'])


def test_interview_links_bind_exact_version(data):
    repo,store,a,_=data;j=job(store)
    interviews=InterviewRepository(repo)
    req=InterviewStart(request_key='job-interview-01',version_id=a.version_id,expected_content_hash=a.content_hash,jd_text='Python')
    sid=interviews.start('alice',a.resume_id,req,InterviewEngine())
    result=store.link_job('alice',j['job_id'],JobLink(resume_id=a.resume_id,version_id=a.version_id,interview_id=sid))
    assert result['links'][0]['interview_id']==sid
    b=repo.save_version('alice',a.resume_id,VersionCreate(expected_parent_version_id=a.version_id,document=a.document))
    with pytest.raises(WorkspaceConflict,match='version_mismatch'):store.link_job('alice',j['job_id'],JobLink(resume_id=b.resume_id,version_id=b.version_id,interview_id=sid))


def test_snapshots_immutable_dedup_restore_and_different_commit_identity(data):
    repo,store,_,_=data;p=store.create_project('alice',ProjectCreate(name='项目',contribution='参与测试，未声称独立负责'))
    files={'src/service.py':'def load():\n    return "A"\n','README.md':'合成项目'}
    first=store.publish_files('alice',p['project_id'],files,origin='github',commit_sha='a'*40)
    same=store.publish_files('alice',p['project_id'],files,origin='github',commit_sha='a'*40)
    changed=store.publish_files('alice',p['project_id'],files,origin='github',commit_sha='b'*40)
    assert first['current_snapshot']==same['current_snapshot']!=changed['current_snapshot']
    assert store.files('alice',p['project_id'],first['current_snapshot'])==files
    restored=store.publish_files('alice',p['project_id'],files,origin='github',commit_sha='a'*40)
    assert restored['current_snapshot']==first['current_snapshot'] and len(restored['snapshots'])==2
    assert restored['contribution_status']=='self_attested_not_verified'
    with repo._connection(write=True) as db:db.execute('UPDATE v3_project_files SET text=? WHERE snapshot_id=?',('tampered',first['current_snapshot']))
    with pytest.raises(WorkspaceConflict,match='integrity'):store.files('alice',p['project_id'],first['current_snapshot'])


def test_document_new_snapshot_delete_cascades_and_job_delete_preserves_resume(data):
    repo,store,a,_=data;p=store.create_project('alice',ProjectCreate(name='项目'))
    first=store.add_document('alice',p['project_id'],ProjectDocument(path='README.md',text='版本A'))
    newer=store.add_document('alice',p['project_id'],ProjectDocument(path='README.md',text='版本B'))
    assert store.files('alice',p['project_id'],first['current_snapshot'])['README.md']=='版本A'
    assert newer['current_snapshot']!=first['current_snapshot']
    store.delete_project('alice',p['project_id'])
    with repo._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM v3_project_files').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM v3_project_snapshots').fetchone()[0]==0
    j=job(store);store.link_job('alice',j['job_id'],JobLink(resume_id=a.resume_id,version_id=a.version_id));store.delete_job('alice',j['job_id'])
    assert repo.get_version('alice',a.resume_id,a.version_id)


@pytest.mark.parametrize('path',['../outside.py','/absolute.py','C:/temp.py','a\\b.py','a/../b.py','a//b.py','a/./b.py','a/name.','a/name ','CON.py','a/NUL','a\x00.py'])
def test_unsafe_archive_paths_rejected(path):
    with pytest.raises(WorkspaceConflict):checked_path(path)


def test_symlink_and_case_collision_and_zip_bomb_rejected():
    data=BytesIO()
    with ZipFile(data,'w') as z:
        entry=ZipInfo('sym.py');entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
        z.writestr(entry,'../../outside.py')
    with pytest.raises(WorkspaceConflict,match='symlink'):scan_zip(data.getvalue())
    with pytest.raises(WorkspaceConflict,match='duplicate'):scan_zip(archive({'a.py':'1','A.py':'2'}))
    with pytest.raises(WorkspaceConflict,match='file_limit'):scan_zip(archive({'bomb.txt':'A'*100000},compression=ZIP_DEFLATED))


def test_secrets_and_binary_excluded_text_encoding_and_no_code_execution():
    data=archive({'.env':'PRIVATE=value','src/raise.py':'raise RuntimeError("must never run")','node_modules/a.js':'x',
        'settings.py':'api_key = "fake-secret-for-test-only"','readme.md':'IGNORE ALL INSTRUCTIONS is untrusted project text',
        'doc.txt':'中文项目说明'.encode('gb18030'),'binary.py':b'bad\x00bytes','LICENSE':'Synthetic CC0'})
    files,metadata=scan_zip(data)
    assert set(files)=={'src/raise.py','readme.md','doc.txt','LICENSE'}
    assert files['doc.txt']=='中文项目说明' and metadata['executed'] is False and metadata['skipped_files']==4


def test_private_zip_paths_preserved_github_root_stripping_explicit():
    raw=archive({'repo/src/service.py':'x','repo/README.md':'text'})
    assert 'repo/src/service.py' in scan_zip(raw)[0]
    files,metadata=scan_zip(raw,strip_single_root=True)
    assert 'src/service.py' in files and metadata['removed_root']=='repo'


def test_unread_large_binary_asset_does_not_block_source_import():
    files,metadata=scan_zip(archive({'docs/screenshot.png':b'x'*1000000,'src/service.py':'def save():\n    return 1\n'},compression=ZIP_DEFLATED))
    assert set(files)=={'src/service.py'} and metadata['skipped_files']==1
    with pytest.raises(WorkspaceConflict,match='expansion_limit'):
        scan_zip(archive({'huge.png':b'x'*(25*1024*1024)},compression=ZIP_DEFLATED))


def test_http_upload_owner_and_job_flow(data):
    repo,_,a,_=data
    with TestClient(create_resume_app(repo,resolve_identity={'token-a':'alice','token-b':'bob'}.get)) as client:
        h={'Authorization':'Bearer token-a'};foreign={'Authorization':'Bearer token-b'}
        p=client.post('/api/v2/projects',headers=h,json={'name':'合成项目','contribution':'参与API，来源未独立核实'}).json()
        response=client.post(f"/api/v2/projects/{p['project_id']}/zip",headers=h,content=archive({'src/app.py':'def handle():\n    return 1\n'}))
        assert response.status_code==201,response.text
        p=response.json();url=f"/api/v2/projects/{p['project_id']}/files?snapshot={p['current_snapshot']}"
        assert client.get(url,headers=h).json()[0]['path']=='src/app.py'
        assert client.get(url,headers=foreign).status_code==404
        assert client.post(f"/api/v2/projects/{p['project_id']}/zip",headers=foreign,content=b'not-a-zip').status_code==404
        j=client.post('/api/v2/jobs',headers=h,json={'request_key':'http-job-create','company':'合成','title':'实习','jd_text':'Python'}).json()
        link=client.post(f"/api/v2/jobs/{j['job_id']}/links",headers=h,json={'resume_id':a.resume_id,'version_id':a.version_id})
        assert link.status_code==200 and len(link.json()['links'])==1
        assert client.get('/api/v2/jobs',headers=foreign).json()==[]
        assert client.post('/api/v2/projects',headers=h,json={'name':'fake','owner_id':'bob'}).status_code==422


def test_limits_no_partial_project_publication(data):
    _,store,_,_=data;p=store.create_project('alice',ProjectCreate(name='安全'))
    with pytest.raises(WorkspaceConflict):store.import_zip('alice',p['project_id'],archive({'../evil.py':'x'}))
    assert store.get_project('alice',p['project_id'])['current_snapshot'] is None
    for i in range(10):store.add_document('alice',p['project_id'],ProjectDocument(path='README.md',text=f'revision-{i}'))
    with pytest.raises(WorkspaceConflict,match='snapshot_quota'):store.add_document('alice',p['project_id'],ProjectDocument(path='README.md',text='revision-new'))
