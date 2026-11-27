from io import BytesIO
from hashlib import sha256
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import SourceCreate, ResumeCreate, ResumeDocument, PersonalInfo, ResumeFact, SourceSpan, Project, VersionCreate
from job_agent.resume_workspace.pdf_export import PDFRepository, PDFRequest, render_pdf
from job_agent.resume_workspace.repository import SqliteResumeRepository, WorkspaceConflict, WorkspaceNotFound


def make_version(repo, *, long=False):
    link='https://example.invalid/'+'long-project-path/'*15+'?a=1&b=2'
    text = '合成同学\nPython\n求职工作台\n' + ('完成接口设计与确定性来源校验，保留请求标识用于恢复。\n'*8 if long else '完成接口设计与确定性来源校验。')
    if long:text+='\n'+link
    source=repo.add_source('alice',SourceCreate(kind='user_statement',label='合成PDF材料',text=text))
    def fact(key, value):
        start=source.text.index(value)
        return ResumeFact(fact_id=key,text=value,source=SourceSpan(source_id=source.source_id,content_hash=source.content_hash,start=start,end=start+len(value)))
    body=text.split('\n',3)[3].split('\nhttps://')[0].strip()
    doc=ResumeDocument(personal=PersonalInfo(name=fact('name','合成同学'),links=[fact('url',link)] if long else []),skills=[fact('skill','Python')],projects=[
        Project(entry_id=f'p{i}',name=fact(f'name{i}','求职工作台'),bullets=[fact(f'body{i}',body)]) for i in range(20 if long else 1)])
    return repo.create_resume('alice',ResumeCreate(title='合成',document=doc))


@pytest.fixture
def data(tmp_path):
    repo=SqliteResumeRepository(tmp_path/'workspace.sqlite')
    return repo,PDFRepository(repo),make_version(repo)


def confirm(repo,v):
    return repo.confirm_version('alice',v.resume_id,v.version_id,expected_content_hash=v.content_hash)


def test_requires_confirmation_and_correct_version_hash(data):
    repo,pdfs,v=data
    with pytest.raises(WorkspaceConflict,match='confirmation_required'):
        pdfs.export('alice',v.resume_id,v.version_id,PDFRequest(expected_content_hash=v.content_hash))
    confirm(repo,v)
    with pytest.raises(WorkspaceConflict,match='version_changed'):
        pdfs.export('alice',v.resume_id,v.version_id,PDFRequest(expected_content_hash='0'*64))


@pytest.mark.parametrize('template',['classic','compact'])
def test_selectable_chinese_deterministic_and_metadata_pinned(data,template):
    repo,pdfs,v=data;v=confirm(repo,v)
    request=PDFRequest(expected_content_hash=v.content_hash,template=template)
    first=pdfs.export('alice',v.resume_id,v.version_id,request)
    assert first==pdfs.export('alice',v.resume_id,v.version_id,request)
    raw=pdfs.download('alice',first['export_id'])
    reader=PdfReader(BytesIO(raw));text='\n'.join(p.extract_text() for p in reader.pages)
    assert '合成同学' in text and '完成接口设计与确定性来源校验' in text and 'Python' in text
    assert v.version_id in reader.metadata.subject and v.content_hash in reader.metadata.subject
    assert sha256(raw).hexdigest()==first['pdf_hash']
    assert render_pdf(v,template)==raw
    assert 'not_verified' not in text


@pytest.mark.parametrize('template',['classic','compact'])
def test_long_projects_paginate_with_searchable_text(tmp_path,template):
    repo=SqliteResumeRepository(tmp_path/'long.sqlite');v=confirm(repo,make_version(repo,long=True))
    reader=PdfReader(BytesIO(render_pdf(v,template)))
    assert 2<=len(reader.pages)<=12
    assert reader.pages[0].extract_text().replace('\n','').count('long-project-path/')==15
    assert all('�' not in page.extract_text() for page in reader.pages)
    assert sum(page.extract_text().count('完成接口设计') for page in reader.pages)==160


def test_historical_download_restart_owner_and_delete(data):
    repo,pdfs,v=data;v=confirm(repo,v)
    item=pdfs.export('alice',v.resume_id,v.version_id,PDFRequest(expected_content_hash=v.content_hash))
    raw=pdfs.download('alice',item['export_id'])
    newer=repo.save_version('alice',v.resume_id,VersionCreate(expected_parent_version_id=v.version_id,document=v.document,note='新版本'))
    assert newer.version_id!=v.version_id
    reopened=PDFRepository(SqliteResumeRepository(repo.path))
    assert reopened.download('alice',item['export_id'])==raw
    with pytest.raises(WorkspaceNotFound):reopened.download('bob',item['export_id'])
    repo.delete_resume('alice',v.resume_id)
    with pytest.raises(WorkspaceNotFound):reopened.download('alice',item['export_id'])
    with repo._connection() as db:assert db.execute('SELECT COUNT(*) FROM rw_pdf_exports').fetchone()[0]==0


def test_http_pdf_and_jd_upload_do_not_create_candidate_sources(data):
    repo,_,v=data;v=confirm(repo,v)
    with TestClient(create_resume_app(repo,resolve_identity={'a':'alice','b':'bob'}.get)) as client:
        h={'Authorization':'Bearer a'}
        item=client.post(f'/api/v2/resumes/{v.resume_id}/versions/{v.version_id}/pdf',headers=h,json={'expected_content_hash':v.content_hash}).json()
        response=client.get('/api/v2/pdfs/'+item['export_id'],headers=h)
        assert response.status_code==200 and response.headers['content-type']=='application/pdf'
        assert response.headers['cache-control']=='no-store'
        assert client.get('/api/v2/pdfs/'+item['export_id'],headers={'Authorization':'Bearer b'}).status_code==404
        before=len(repo.list_sources('alice'))
        jd=client.post('/api/v2/jd/extract?filename=job.txt',headers=h,content='岗位要求：Python 接口开发'.encode()).json()
        assert jd['extraction_only'] and 'Python' in jd['text']
        assert len(repo.list_sources('alice'))==before


def test_corrupted_cached_pdf_is_rejected(data):
    repo,pdfs,v=data;confirm(repo,v)
    item=pdfs.export('alice',v.resume_id,v.version_id,PDFRequest(expected_content_hash=v.content_hash))
    with repo._connection(write=True) as db:db.execute('UPDATE rw_pdf_exports SET pdf_bytes=?',(b'bad',))
    with pytest.raises(WorkspaceConflict,match='integrity_failed'):pdfs.download('alice',item['export_id'])
