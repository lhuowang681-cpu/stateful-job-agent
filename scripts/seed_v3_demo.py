"""Explicit synthetic-only seed. No private inputs, external calls or source execution."""
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED,ZipInfo
from hashlib import sha256
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService

FILES={
    'app/storage.py':'def save_receipt(request_id, store):\n    """Reuse the receipt for the same request identity."""\n    if request_id not in store:\n        store[request_id] = "done"\n    return store[request_id]\n',
    'app/api.py':'from .storage import save_receipt\n\ndef handle(request_id, store):\n    return save_receipt(request_id, store)\n',
    'tests/test_storage.py':'from app.storage import save_receipt\n\ndef test_duplicate():\n    store = {}\n    assert save_receipt("a", store) == save_receipt("a", store)\n',
    'client.ts':'export function receiptKey(id: string): string { return `receipt:${id}`; }\n',
    'README.md':'# Synthetic receipt example\nOriginal CC0 demo, not a production system.\nIn-memory receipts disappear on restart. No cross-process transaction or external exactly-once guarantee.\nReading this snapshot does not execute its tests.\n',
    'LICENSE':'CC0-1.0. Original synthetic teaching example, dedicated to the public domain.\n',
}


def seed():
    dest=ROOT/'docs/demo/assets';dest.mkdir(parents=True,exist_ok=True)
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for path,text in sorted(FILES.items()):
            info=ZipInfo(path,date_time=(2026,10,20,0,0,0));info.compress_type=ZIP_DEFLATED
            z.writestr(info,text)
    archive=stream.getvalue();(dest/'synthetic-receipts.zip').write_bytes(archive)
    ws=SqliteResumeRepository(ROOT/'output/demo-v3/workspace.sqlite');store=LongTermRepository(ws);code=CodeRAGService(ws)
    result=[]
    for owner,name in [('synthetic-demo-user','合成回执项目（源码练习）'),('synthetic-second-user','第二用户隔离样例')]:
        p=next((p for p in store.list_projects(owner) if p['name']==name),None)
        p=p or store.create_project(owner,ProjectCreate(name=name,contribution='虚构教学样例；不声称实际生产部署或性能。',license_note='CC0-1.0'))
        p=store.import_zip(owner,p['project_id'],archive)
        index=code.build(owner,p['project_id'],p['current_snapshot'])
        result.append({'owner':owner,'project_id':p['project_id'],'snapshot':p['current_snapshot'],'files':index['files'],'symbols':index['symbols']})
    public=dest/'starlette-public-0.46.2.zip'
    if public.is_file():
        from job_agent.resume_workspace.project_import import scan_zip
        data=public.read_bytes()
        if sha256(data).hexdigest()!='792a950c58e4727b8e7afe728a4b68b4ddc24d91ac28441bac3c37b59caea881':raise RuntimeError('public demo archive checksum mismatch')
        name='Starlette公开源码学习样例（非本人贡献）';owner='synthetic-demo-user'
        p=next((p for p in store.list_projects(owner) if p['name']==name),None)
        p=p or store.create_project(owner,ProjectCreate(name=name,contribution='公开开源阅读样例，不声称是本人开发、运行或生产部署。',license_note='BSD-3-Clause'))
        files,meta=scan_zip(data,strip_single_root=True)
        with ZipFile(BytesIO(data)) as z:
            if z.comment.decode()!='4a811767bcba6e933bf7a8b48edef5993ce8948e':raise RuntimeError('public demo commit mismatch')
        p=store.publish_files(owner,p['project_id'],files,origin='github',commit_sha='4a811767bcba6e933bf7a8b48edef5993ce8948e',metadata={**meta,'license':'BSD-3-Clause','source_url':'https://github.com/Kludex/starlette','public_access_basis':'verified_packaged_public_archive'})
        code.build(owner,p['project_id'],p['current_snapshot'])
    report={'synthetic':True,'license':'CC0-1.0','archive_sha256':sha256(archive).hexdigest(),'projects':result,'source_execution':'not_run','model_calls':0}
    if not (dest/'synthetic-receipts-manifest.json').is_file() or (dest/'synthetic-receipts-manifest.json').read_text(encoding='utf-8')!=json.dumps(report,ensure_ascii=False,indent=2):
        (dest/'synthetic-receipts-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':seed()
