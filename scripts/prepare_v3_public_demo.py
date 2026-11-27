"""Fetch a public, licensed source snapshot; never read private material/keys."""
from pathlib import Path
import sys,json,hashlib
import httpx
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R/'src'),str(R)]
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.github_import import PublicGitHubImporter,GitHubImport
from job_agent.resume_workspace.code_rag import CodeRAGService


class Capture(PublicGitHubImporter):
    def _download(self,client,url,limit):
        raw=super()._download(client,url,limit)
        if url.startswith('https://codeload.github.com/'):self.archive=raw
        return raw


def main():
    workspace=SqliteResumeRepository(R/'output/demo-v3/workspace.sqlite')
    store=LongTermRepository(workspace);owner='synthetic-demo-user'
    name='Starlette公开源码学习样例（非本人贡献）'
    existing=next((p for p in store.list_projects(owner) if p['name']==name),None)
    project=existing or store.create_project(owner,ProjectCreate(name=name,
        contribution='只作为公开开源源码阅读与面试练习样例，不声称是本人开发、运行或生产部署的项目。',
        license_note='上游BSD-3-Clause，保留上游许可和固定版本。'))
    client=httpx.Client(timeout=httpx.Timeout(25,connect=8),follow_redirects=False,trust_env=False)
    importer=Capture(store,client=client)
    try:project=importer.import_project(owner,project['project_id'],GitHubImport(url='https://github.com/Kludex/starlette',ref='4a811767bcba6e933bf7a8b48edef5993ce8948e'))
    finally:client.close()
    snapshot=project['current_snapshot'];entry=next(s for s in project['snapshots'] if s['snapshot_id']==snapshot)
    if entry['metadata']['license']!='BSD-3-Clause':raise RuntimeError('unexpected public dataset license')
    index=CodeRAGService(workspace).build(owner,project['project_id'],snapshot)
    dest=R/'docs/demo/assets';dest.mkdir(parents=True,exist_ok=True)
    archive=dest/'starlette-public-0.46.2.zip';archive.write_bytes(importer.archive)
    result={'source_url':'https://github.com/Kludex/starlette','ref':'0.46.2','commit':entry['commit_sha'],
        'ref_to_commit_verification':'https://github.com/Kludex/starlette/releases/tag/0.46.2',
        'license':'BSD-3-Clause','archive':archive.name,'archive_sha256':hashlib.sha256(importer.archive).hexdigest(),
        'safety':entry['metadata'],'index':index,'project_id':project['project_id'],'snapshot_id':snapshot,
        'user_contribution':'not_claimed','test_execution':'not_run','model_calls':0}
    (dest/'starlette-public-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('source_url','commit','license','project_id','snapshot_id','archive_sha256')}))
    print(json.dumps({k:index[k] for k in ('files','symbols','chunks','edges','unresolved_references','total_elapsed_ms')}))


if __name__=='__main__':main()
