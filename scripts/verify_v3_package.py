"""Extract our public release, verify hashes, then exercise its own isolated code."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
from uuid import uuid4
from zipfile import ZipFile
import argparse,json,subprocess,sys,os
ROOT=Path(__file__).resolve().parents[1]

SMOKE=r'''
import sys,json,io,contextlib
from pathlib import Path
root=Path.cwd();sys.path[:0]=[str(root/'src'),str(root)]
import job_agent
assert Path(job_agent.__file__).resolve().is_relative_to(root)
from scripts.seed_v3_demo import seed
with contextlib.redirect_stdout(io.StringIO()):seed()
from scripts.demo_resume_workbench import build_demo_app
from fastapi.testclient import TestClient
from pypdf import PdfReader
app=build_demo_app(root/'output/demo-v3/workspace.sqlite')
h={'Authorization':'Bearer job-agent-synthetic-demo-only-2026'}
with TestClient(app) as c:
 assert c.get('/').status_code==200
 assert c.get('/api/v2/knowledge/status',headers=h).json()['documents']==10
 assert len(c.get('/api/v2/projects',headers=h).json())==2
 data=(root/'docs/demo/assets/synthetic-resume-source.pdf').read_bytes()
 r=c.post('/api/v2/imports?filename=synthetic.pdf',headers=h,content=data);assert r.status_code==201,r.status_code
 upload=r.json()
 r=c.post('/api/v2/sources/'+upload['source_id']+'/parse',headers=h,json={'mode':'local_rules','allow_external_processing':False});assert r.status_code==201,r.text
 draft=r.json()
 r=c.post('/api/v2/drafts/'+draft['draft_id']+'/accept',headers=h,json={'title':'Isolated package synthetic','expected_source_hash':upload['content_hash'],'user_reviewed':True});assert r.status_code==201,r.text
 v=r.json();rid=v['resume_id'];vid=v['version_id']
 r=c.post(f'/api/v2/resumes/{rid}/versions/{vid}/confirm',headers=h,json={'expected_content_hash':v['content_hash']});assert r.status_code==200
 r=c.post(f'/api/v2/resumes/{rid}/versions/{vid}/pdf',headers=h,json={'expected_content_hash':v['content_hash'],'template':'compact'});assert r.status_code==201,r.text
 raw=c.get('/api/v2/pdfs/'+r.json()['export_id'],headers=h).content
 text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
 assert '演示同学' in text and 'Python' in text
print(json.dumps({'isolated_package_import':True,'frontend_served':True,'seeded_primary_projects':2,'public_documents':10,'synthetic_pdf_import_parse_accept_confirm_export':True,'embedded_font_works':True,'model_calls':0}))
'''


def main(archive):
    archive=archive.resolve();folder=ROOT.parent/('v3-smoke-'+uuid4().hex[:8]);folder.mkdir()
    with ZipFile(archive) as z:
        for name in z.namelist():
            parts=PurePosixPath(name).parts
            if name.startswith('/') or '..' in parts or '\\' in name:raise RuntimeError('unsafe archive path')
        assert z.testzip() is None
        z.extractall(folder)
    extracted=folder/'job-agent-v3';manifest=json.loads((extracted/'DELIVERY_MANIFEST.json').read_text(encoding='utf-8'))
    for name,expected in manifest['sha256'].items():
        assert sha256((extracted/name).read_bytes()).hexdigest()==expected,name
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    run=subprocess.run([sys.executable,'-c',SMOKE],cwd=extracted,capture_output=True,text=True,encoding='utf-8',timeout=90,creationflags=flags)
    if run.returncode:
        # Only synthetic fixture errors can occur here. Keep bounded diagnostics.
        print(run.stderr[-4000:]);raise RuntimeError('isolated package smoke failed')
    verification=json.loads(run.stdout.strip().splitlines()[-1])
    implementation={n:h for n,h in manifest['sha256'].items() if n.startswith(('src/','frontend/','fit_verdict_engine/'))}
    report={'candidate_archive_sha256':sha256(archive.read_bytes()).hexdigest(),'manifest_files_checked':len(manifest['sha256']),
        'implementation_tree_sha256':sha256(json.dumps(implementation,sort_keys=True).encode()).hexdigest(),
        'scope':'fresh extraction using only packaged application/build/assets and existing dependency runtime; does not prove clean dependency installation or Docker',
        **verification}
    dest=ROOT/'docs/devlog/evidence/v3/f7-package-smoke.json';dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);main(p.parse_args().archive)
