from io import BytesIO
import json
import socket
from zipfile import ZipFile
import httpx
import pytest
from job_agent.resume_workspace.github_import import PublicGitHubImporter,GitHubImport,repository_slug,check_public_host
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict


@pytest.mark.parametrize('url',[
    'http://github.com/a/b','https://127.0.0.1/a/b','https://github.com.evil.test/a/b',
    'https://user:token@github.com/a/b','https://github.com:443/a/b','https://github.com/a/b?redirect=localhost',
    'https://github.com/a/b#token','https://github.com/a/b/../../x','https://github.com/../b',
    'https://github.com/a/b/tree/main','file:///a/b','https://github.com/a/%2e%2e',
])
def test_only_exact_public_https_repository_urls(url):
    with pytest.raises(WorkspaceConflict):repository_slug(url)


def test_no_dns_private_address_or_unknown_hosts(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(WorkspaceConflict,match='private_address'):check_public_host('api.github.com')
    with pytest.raises(WorkspaceConflict,match='host_not_allowed'):check_public_host('example.invalid')


def fake_importer(tmp_path,*,redirect=False,private=False,bad_zip=False):
    store=LongTermRepository(SqliteResumeRepository(tmp_path/'ws.sqlite'));p=store.create_project('alice',ProjectCreate(name='public import'))
    out=BytesIO()
    with ZipFile(out,'w') as z:z.writestr('upstream-abc/src/app.py' if not bad_zip else '../bad.py','def run():\n    return 1\n')
    requests=[]
    def respond(request):
        requests.append(request)
        assert 'authorization' not in request.headers
        assert request.url.host in {'api.github.com','codeload.github.com'}
        if redirect:return httpx.Response(302,headers={'Location':'http://127.0.0.1/private'})
        if request.url.host=='codeload.github.com':return httpx.Response(200,content=out.getvalue())
        if '/commits/' in request.url.path:return httpx.Response(200,json={'sha':'a'*40})
        return httpx.Response(200,json={'private':private,'default_branch':'main','license':{'spdx_id':'MIT'}})
    client=httpx.Client(transport=httpx.MockTransport(respond),follow_redirects=False,trust_env=False)
    return store,p,PublicGitHubImporter(store,client=client,host_guard=lambda host:None),requests


def test_public_import_pins_commit_license_and_does_not_execute(tmp_path):
    store,p,service,requests=fake_importer(tmp_path)
    result=service.import_project('alice',p['project_id'],GitHubImport(url='https://github.com/example/public.git'))
    snap=result['snapshots'][0]
    assert snap['commit_sha']=='a'*40 and snap['metadata']['license']=='MIT'
    assert 'a'*40 in str(requests[-1].url)
    assert list(store.files('alice',p['project_id'],result['current_snapshot']))==['src/app.py']
    assert snap['metadata']['executed'] is False


@pytest.mark.parametrize('failure',['redirect','private','bad_zip'])
def test_redirect_private_and_zip_failure_never_publish(tmp_path,failure):
    store,p,service,requests=fake_importer(tmp_path,**{failure:True})
    with pytest.raises(WorkspaceConflict):service.import_project('alice',p['project_id'],GitHubImport(url='https://github.com/example/public'))
    assert store.get_project('alice',p['project_id'])['current_snapshot'] is None
    if failure=='redirect':assert len(requests)==1


@pytest.mark.parametrize('comment',['a'*40,'b'*40,''])
def test_full_sha_requires_official_git_archive_comment(tmp_path,comment):
    store=LongTermRepository(SqliteResumeRepository(tmp_path/'full.sqlite'));p=store.create_project('alice',ProjectCreate(name='SHA'))
    archive=BytesIO()
    with ZipFile(archive,'w') as z:
        z.comment=comment.encode();z.writestr('repo-'+('a'*40)+'/src/run.py','def run():\n    return 1\n')
        z.writestr('repo-'+('a'*40)+'/pyproject.toml','[project]\nlicense = "MIT"\n')
    requests=[]
    def reply(request):
        requests.append(request);assert request.url.host=='codeload.github.com' and 'authorization' not in request.headers
        return httpx.Response(200,content=archive.getvalue())
    client=httpx.Client(transport=httpx.MockTransport(reply),trust_env=False,follow_redirects=False)
    importer=PublicGitHubImporter(store,client=client,host_guard=lambda _:None)
    req=GitHubImport(url='https://github.com/example/repo',ref='a'*40)
    if comment=='a'*40:
        result=importer.import_project('alice',p['project_id'],req)
        assert result['snapshots'][0]['metadata']['commit_verified_by']=='git_archive_comment'
        assert result['snapshots'][0]['metadata']['license']=='MIT'
    else:
        with pytest.raises(WorkspaceConflict,match='commit_mismatch'):importer.import_project('alice',p['project_id'],req)
        assert store.get_project('alice',p['project_id'])['current_snapshot'] is None
    assert len(requests)==1
