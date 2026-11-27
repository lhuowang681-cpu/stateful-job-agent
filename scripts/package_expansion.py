"""Public source, learning and synthetic research packages with byte-level manifests."""
import argparse,json,sys,zipfile
from hashlib import sha256
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]


def sha(data):return sha256(data).hexdigest()
def eligible(path):
    relative=path.relative_to(ROOT).as_posix()
    if any(x in path.parts for x in ('__pycache__','node_modules','.git','.pytest_cache','handbook')):return False
    if path.name=='HANDBOOK-2026-10-22.md' or path.name=='.env' or path.suffix in ('.pyc','.log'):return False
    if path.suffix=='.sqlite':return relative.startswith('tests/fixtures/expansion_research/index-v1/')
    return path.suffix in ('.py','.json','.jsonl','.md','.txt','.toml','.sql','.ttf','.png','.svg','.css','.js','.jsx','.html','.yaml','.yml','.xml','.patch') or path.name in ('.gitignore','LICENSE')


def zip_pack(output,name,files):
    # Input file mapping is curated here; no environment, live DBs or weight directories.
    data={key:(value.read_bytes() if isinstance(value,Path) else value) for key,value in sorted(files.items())}
    manifest={'schema_version':'expansion-package-1','name':name,'files':{k:sha(v) for k,v in data.items()},
        'git_history_included':False,'private_material_included':False,
        'note':'Only research fixture SQLite is synthetic and explicitly included; no user database, credentials, runtime or model weights.'}
    path=output/(name+'.zip')
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as out:
        for key,value in data.items():out.writestr(key,value)
        out.writestr(name.upper().replace('-','_')+'_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(path) as check:
        assert check.testzip() is None
        assert all(sha(check.read(k))==digest for k,digest in manifest['files'].items())
    digest=sha(path.read_bytes());(output/(name+'.sha256')).write_text(digest+'  '+path.name+'\n',encoding='utf-8')
    return {'file':path.name,'sha256':digest,'files':len(data),'bytes':path.stat().st_size}


def source_files():
    files={}
    for folder in ('src','fit_verdict_engine','tests','scripts','frontend/src','frontend/dist','frontend/public','docs/roadmap','docs/tech-specs/expansion',
                   'docs/evaluation/expansion','docs/devlog/evidence/expansion'):
        base=ROOT/folder
        if not base.exists():continue
        for p in base.rglob('*'):
            if p.is_file() and eligible(p):files[p.relative_to(ROOT).as_posix()]=p
    for p in (ROOT/'frontend').iterdir():
        if p.is_file() and eligible(p):files[p.relative_to(ROOT).as_posix()]=p
    names=['pyproject.toml','README.md','LICENSE','AGENTS.md','.gitignore','.dockerignore','workbench.env.example','FEATURE_MATRIX.md',
        'Dockerfile.backend','Dockerfile.workbench','Dockerfile.workbench.dockerignore','compose.backend.yml','compose.backend.load.yml','compose.workbench.yml','requirements.backend.txt',
        'docs/CONTINUE_DEVELOPMENT.md','docs/tech-specs/CURRENT_SPEC.md','docs/tech-specs/SPEC_CHANGELOG.md',
        'docs/devlog/INDEX.md','docs/devlog/ARCHITECTURE_MAP.md','docs/devlog/DECISIONS.md',
        'docs/demo/EXPANSION_RUNBOOK.md','docs/learning/EXPANSION_30_MINUTE_ROUTE.md']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'docs/devlog').glob('EXPAND-S*.md')]
    for name in names:
        p=ROOT/name
        if not p.is_file():raise ValueError('package_required_file_missing:'+name)
        files[name]=p
    workflow=ROOT/'.github/workflows/expansion.yml'
    if workflow.is_file():files[workflow.relative_to(ROOT).as_posix()]=workflow
    return files


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);sources=source_files();learning={k:v for k,v in sources.items() if
        (k.startswith(('docs/tech-specs/','docs/evaluation/expansion/')) and not k.endswith('.jsonl')) or
        k.startswith('docs/devlog/EXPAND-S') or k in ('FEATURE_MATRIX.md','docs/demo/EXPANSION_RUNBOOK.md','docs/learning/EXPANSION_30_MINUTE_ROUTE.md',
        'docs/devlog/ARCHITECTURE_MAP.md','docs/devlog/DECISIONS.md','docs/CONTINUE_DEVELOPMENT.md') or
        (k.startswith('docs/devlog/evidence/expansion/') and (k.endswith('-summary.json') or k.endswith('s8-requirement-audit.json')))}
    research={}
    for p in (ROOT/'tests/fixtures/expansion_research/index-v1').iterdir():
        if p.is_file():research['research/index-v1/'+p.name]=p
    for split in ('dev','test'):
        for name in ('run.json','queries.jsonl'):
            research[f'research/evaluations/{split}-v1/{name}']=ROOT/f'docs/devlog/evidence/expansion/s8-eval-{split}-v1/{name}'
    for name in ('run.json','queries.jsonl'):
        research['research/evaluations/offline-baseline-v1/'+name]=ROOT/('docs/devlog/evidence/expansion/s8-offline-baseline-v1/'+name)
    for name in ('retrieval-gate-v1.json','TRACE_CONSUMER.md','unified-trace-schema-v1.json','RESEARCH_README.md','requirements-ci-observed.txt'):
        research['research/'+name]=ROOT/'docs/evaluation/expansion'/name
    for p in (ROOT/'docs/evaluation/expansion/trace-examples').glob('*'):
        if p.is_file():research['research/trace-examples/'+p.name]=p
    for name in ('s8-research-prepare-v1.json','s8-replay-dev-v1.json','s8-replay-test-v1.json','s8-offline-gate-v1.json','s8-summary.json'):
        research['research/evidence/'+name]=ROOT/'docs/devlog/evidence/expansion'/name
    for key,path in research.items():
        if not path.is_file():raise ValueError('research_required_file_missing:'+key)
    results=[zip_pack(a.output,'job-agent-expansion-source',sources),zip_pack(a.output,'job-agent-expansion-learning',learning),
             zip_pack(a.output,'job-agent-expansion-research',research)]
    report={'schema_version':'expansion-delivery-1','packages':results,'scope':'S0-S8 engineering; human semantic review explicitly deferred',
        'excluded':'credentials/private databases/model weights/runtimes/Git history/concurrent handbook',
        'validation':'ZIP CRC and every manifest byte hash verified; unpack/start checks recorded separately'}
    (a.output/'delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
