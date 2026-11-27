"""Package approved public sources, authored reports and licensed demo assets only."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
from zipfile import ZipFile,ZIP_DEFLATED
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parents[1]/'work';DEST=ROOT.parent


def selected():
    # F0 already classified these text files as public. Never traverse user data.
    with ZipFile(WORK/'v3-f0-public-source-baseline.zip') as z:names=set(z.namelist())
    def add(pattern):
        names.update(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern) if p.is_file() and not p.is_symlink())
    add('src/job_agent/resume_workspace/*.py');add('src/job_agent/resume_workspace/assets/*')
    add('fit_verdict_engine/*.py');add('frontend/src/*');add('frontend/dist/**/*')
    for name in ('package.json','package-lock.json','index.html','vite.config.js'):names.add('frontend/'+name)
    for pattern in ('tests/test_v3_*.py','tests/test_workbench_*.py','tests/test_resume_*.py',
        'tests/fixtures/v3_frozen/*','tests/fixtures/v3_diagnostic/*','docs/roadmap/*.md',
        'docs/devlog/FINAL-F*.md','docs/devlog/evidence/v3/*.json','docs/devlog/traces/v3-*.json','docs/architecture/*.md',
        'docs/evaluation/*.md','docs/evaluation/results/*.json','docs/demo/*.md','docs/licenses/*.txt',
        'docs/demo/artifacts/*.png','docs/demo/artifacts/*.pdf','docs/demo/artifacts/*.json'):
        add(pattern)
    for name in ('00_READ_FIRST','01_END_TO_END','02_MULTI_AGENT','03_PUBLIC_RAG','04_CODE_AWARE_RAG',
        '05_RELIABLE_RUNTIME','06_EVALUATION','INTERVIEW_QA'):names.add('docs/learning/'+name+'.md')
    for name in ('synthetic-receipts.zip','synthetic-receipts-manifest.json','synthetic-resume-source.pdf',
        'starlette-public-0.46.2.zip','starlette-public-manifest.json'):names.add('docs/demo/assets/'+name)
    for name in ('demo_resume_workbench','seed_v3_demo','prepare_v3_public_demo','v3_task_worker',
        'verify_v3_local_recovery','verify_v3_demo_state','verify_v3_package','eval_v3_code','eval_v3_public','create_v3_demo_resume','package_v3_public'):
        names.add('scripts/'+name+'.py')
    names.update({'AGENTS.md','FEATURE_MATRIX.md','FINAL_HANDOVER.md','LICENSE','.gitignore','.dockerignore',
        'Dockerfile.backend','Dockerfile.workbench','Dockerfile.workbench.dockerignore','compose.backend.yml',
        'compose.backend.load.yml','compose.workbench.yml','requirements.backend.txt','workbench.env.example'})
    names.update({'docs/CONTINUE_DEVELOPMENT.md','docs/PROJECT_AUDIT.md','docs/INTERVIEW_SOURCE_GUIDE.md',
        'docs/resume_notes.md','docs/devlog/INDEX.md','docs/devlog/ARCHITECTURE_MAP.md','docs/devlog/DECISIONS.md'})
    forbidden={'node_modules','__pycache__','.git','.venv','venv','output','data','private','private_capture','work'}
    result=[]
    for name in sorted(names):
        parts=PurePosixPath(name).parts;p=ROOT/name
        if any(x in forbidden for x in parts) or name.startswith('/') or '..' in parts:raise RuntimeError('unsafe package path')
        if any(x.startswith('.env') for x in parts) or p.suffix in ('.db','.sqlite','.pyc','.key','.pem'):raise RuntimeError('private package suffix')
        if not p.is_file():raise RuntimeError('required public file missing: '+name)
        if not p.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('path escaped source root')
        if p.is_symlink():raise RuntimeError('symlink is not a packaged source: '+name)
        result.append(name)
    return result


def package(names,path,scope):
    hashes={};total=0
    for name in names:
        raw=(ROOT/name).read_bytes();hashes[name]=sha256(raw).hexdigest();total+=len(raw)
        if Path(name).suffix in ('.py','.md','.json','.js','.jsx','.toml','.yml','.yaml','.txt','.example'):
            # High-precision provider-key guard. Do not print candidate secret values.
            if re.search(rb'\bsk-[A-Za-z0-9]{28,}\b',raw):raise RuntimeError('potential credential in public file: '+name)
    manifest={'scope':scope,'head_baseline':'067bfc7d63408e1e6b0ab6c227e863bd08a5857a','dirty_working_tree':True,
        'files':len(names),'uncompressed_bytes':total,'sha256':hashes,
        'excludes':['private materials','runtime databases/uploads','env/secrets','git history','venv/node_modules','model weights'],
        'note':'Complete public implementation, tests, build and authored evidence. Recreate runtime state with the documented seed.'}
    with ZipFile(path,'w',ZIP_DEFLATED,compresslevel=6) as z:
        for name in names:z.write(ROOT/name,'job-agent-v3/'+name)
        z.writestr('job-agent-v3/DELIVERY_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with ZipFile(path) as z:
        if z.testzip() is not None:raise RuntimeError('archive CRC failed')
        for name,expected in hashes.items():
            if sha256(z.read('job-agent-v3/'+name)).hexdigest()!=expected:raise RuntimeError('archive source mismatch: '+name)
    digest=sha256(path.read_bytes()).hexdigest();path.with_suffix(path.suffix+'.sha256').write_text(digest+'  '+path.name+'\n',encoding='ascii')
    return {'archive':path.name,'files':len(names),'bytes':path.stat().st_size,'sha256':digest}


def main():
    names=selected()
    font='src/job_agent/resume_workspace/assets/NotoSansSC.ttf'
    if sha256((ROOT/font).read_bytes()).hexdigest()!='a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da':raise RuntimeError('font checksum changed')
    frozen=ROOT/'tests/fixtures/v3_frozen/code_queries.json'
    if sha256(frozen.read_bytes()).hexdigest()!='b1e59321b5d6631f3860e3a6fc461b70eed363d0ecf0ef493292ab0f6686edec':raise RuntimeError('frozen labels changed')
    reports=[n for n in names if n.startswith('docs/') or n in ('AGENTS.md','FINAL_HANDOVER.md','FEATURE_MATRIX.md')]
    results=[package(names,DEST/'Job_Agent_V3_LOCALLY_VERIFIED_Source.zip','public source + build + reports + licensed fixtures'),
        package(reports,DEST/'Job_Agent_V3_Learning_Reports.zip','authored technical records + evidence + learning and demo materials')]
    (WORK/'v3-delivery-packages.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
