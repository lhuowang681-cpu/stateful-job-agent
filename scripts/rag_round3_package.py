"""New round3 packages from committed files; never sweep untracked work."""
import argparse,json,math,re,sqlite3,subprocess,sys
from hashlib import sha256
from pathlib import Path,PurePosixPath
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.review_package import source_files,package,write_new
from job_agent.knowledge.research_contract import inspect_bundle

REQUIRED=['AGENTS.md','docs/CONTINUE_DEVELOPMENT.md','docs/devlog/INDEX.md',
    'docs/devlog/_PHASE_TEMPLATE.md','docs/tech-specs/INCREMENT_SPEC_TEMPLATE.md',
    'docs/tech-specs/CURRENT_SPEC.md','docs/learning/RAG_ROUND3_ROUTE.md','docs/demo/RAG_ROUND3_RUNBOOK.md']
REQUIRED += ['docs/devlog/RAG-F'+str(i)+'.md' for i in range(6)]
REQUIRED += ['docs/tech-specs/expansion/RAG-F'+str(i)+'.md' for i in range(6)]

def audit_links(files):
    missing=[p for p in REQUIRED if p not in files];assert not missing,missing
    rows=[]
    for name in REQUIRED:
        text=files[name].decode('utf-8')
        for raw in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):
            target=unquote(raw.strip('<>').split('#')[0])
            if not target or re.match(r'^[a-zA-Z]+://|^mailto:',target):continue
            target=target.split('::')[0]
            path=PurePosixPath(name).parent/PurePosixPath(target)
            parts=[]
            for part in path.parts:
                if part=='..':
                    if parts:parts.pop()
                    else:raise ValueError('required_doc_link_escape')
                elif part!='.':parts.append(part)
            resolved='/'.join(parts);exists=resolved in files
            rows.append({'from':name,'target':resolved,'exists_in_source':exists})
            if not exists and (resolved in REQUIRED or name not in ('AGENTS.md','docs/CONTINUE_DEVELOPMENT.md','docs/devlog/INDEX.md')):
                raise ValueError('current_required_doc_link_missing:'+resolved)
    # Historical narrative references are not silently manufactured or passed.
    historical=[]
    for name in ('AGENTS.md','docs/CONTINUE_DEVELOPMENT.md','docs/devlog/INDEX.md'):
        for path in re.findall(r'docs/[A-Za-z0-9_./-]+\.md',files[name].decode('utf-8')):
            if path not in files:historical.append({'from':name,'missing_historical_reference':path})
    return {'required_files':REQUIRED,'markdown_links':rows,'historical_missing_narrative':historical,
        'policy':'Only current required graph is blocking; URLs, anchors and ::symbol are not filenames. Historical gaps remain explicit.'}

def audit_joint(directory,sources):
    m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'));path=directory/'source-only.sqlite'
    assert sha256(path.read_bytes()).hexdigest()==m['database_sha256']
    current={p:sha256(b).hexdigest() for p,b in sources.items() if p.startswith('src/') and p.endswith('.py')}
    assert current==m['source_identity']['files'],'joint_source_code_drift'
    allowed={'v3_projects','v3_project_snapshots','v3_project_files','v3_code_indexes','v3_code_symbols','v3_code_chunks','v3_code_edges','v3_code_vectors'}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            assert name.replace('_','').isalnum()
            assert name in allowed or db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]==0
        scope_rows=set(db.execute('SELECT project_id,owner_id,current_snapshot FROM v3_projects'))
        assert scope_rows=={(s['project_id'],'synthetic-local-project-study',s['snapshot_id']) for s in m['scopes'].values()}
        assert db.execute('SELECT COUNT(*) FROM v3_project_snapshots').fetchone()[0]==len(m['scopes'])
        for payload,expected,dimension in db.execute('SELECT payload,payload_hash,dimension FROM v3_code_vectors'):
            assert sha256(payload.encode()).hexdigest()==expected
            vectors=json.loads(payload);assert vectors
            assert all(len(v)==dimension and all(type(x) in (int,float) and math.isfinite(x) for x in v) for v in vectors.values())
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.long_term import LongTermRepository
    from job_agent.resume_workspace.code_rag import CodeRAGService
    ws=SqliteResumeRepository(path);projects=LongTermRepository(ws)
    for scope in m['scopes'].values():
        files=projects.files('synthetic-local-project-study',scope['project_id'],scope['snapshot_id'])
        assert {p:sha256(t.encode()).hexdigest() for p,t in files.items()}==scope['file_hashes']
        CodeRAGService(ws)._load('synthetic-local-project-study',scope['project_id'],scope['snapshot_id'])
    return m

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--joint-bundle',type=Path,required=True);a=p.parse_args()
    output=a.output.resolve();assert output.is_relative_to(ROOT/'output/rag-round3-20261023');output.mkdir(parents=True,exist_ok=False)
    sources=source_files();dependencies=audit_links(sources);write_new(output/'document-dependencies.json',dependencies)
    research={};index=ROOT/'output/rag-round3-20261023/f2-new16-index-v1'
    inspect_bundle(ROOT,index,strict_algorithm=True)
    expected={'manifest.json','dataset.json','dev.sqlite','test.sqlite','dev-public-vectors.json','test-public-vectors.json','round3-formal-reservation-v1.json'}
    assert {p.name for p in index.iterdir()}==expected
    for path in index.iterdir():research['research/f2-new16-index-v1/'+path.name]=path.read_bytes()
    joint=a.joint_bundle.resolve();audit_joint(joint,sources)
    assert {p.name for p in joint.iterdir()}=={'manifest.json','source-only.sqlite'}
    for path in joint.iterdir():research['research/'+joint.name+'/'+path.name]=path.read_bytes()
    for name,value in sources.items():
        if name.startswith(('docs/devlog/evidence/rag-round3-20261023/','docs/evaluation/expansion/rag-round3-','docs/devlog/RAG-F','docs/tech-specs/expansion/RAG-F')):
            research[name]=value
    learning={p:b for p,b in sources.items() if p.startswith(('docs/','src/')) or p in ('AGENTS.md','FEATURE_MATRIX.md','README.md','pyproject.toml')}
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    common={'git_revision':revision,'internal_project_source_included':True,'source_kind':'owner_project_source',
        'permission':'Owner authorized local/internal evaluation; no public redistribution license asserted',
        'human_reviewed_count':0,'business_workspace_databases_included':False,'model_weights_included':False,
        'source_file_policy':'Reviewed committed snapshot; concurrent teaching working changes excluded'}
    packages=[package(output,'job-agent-round3-source',sources,common),package(output,'job-agent-round3-learning',learning,common),
        package(output,'job-agent-round3-research',research,common)]
    write_new(output/'delivery.json',{'source_git_revision':revision,'packages':packages,
        'status':'hash_crc_all_files_and_unpack_passed_runtime_checks_separate','document_dependencies':'document-dependencies.json'})
    print(json.dumps({'source_git_revision':revision,'packages':packages},ensure_ascii=False))
if __name__=='__main__':main()
