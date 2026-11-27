"""Local source/evidence hashes and honest no-Git diff against transferred baseline."""
from datetime import datetime,timezone
import difflib
from hashlib import sha256
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    evidence=ROOT/'docs/devlog/evidence/expansion';evidence.mkdir(parents=True,exist_ok=True)
    archive=ROOT/'output/expansion/source-baseline.tar.gz'
    if not archive.is_file():
        remote_name=ROOT.parent/'job-agent-v3-source-baseline-20261022.tar.gz'
        archive=remote_name if remote_name.is_file() else archive
    current={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
        for base in ('src','tests','scripts') for p in (ROOT/base).rglob('*.py') if '__pycache__' not in p.parts}
    frontend={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'frontend/src').rglob('*') if p.is_file() and p.suffix in ('.js','.jsx','.css')}
    delta=[];changed=[]
    with tarfile.open(archive,'r:gz') as baseline:
        members={m.name:m for m in baseline.getmembers() if m.isfile()}
        candidates=[p for base in ('src','tests','scripts','docs') for p in (ROOT/base).rglob('*')
                    if p.is_file() and p.suffix in ('.py','.md','.json') and not any(
                        x in p.parts for x in ('__pycache__','evidence','handbook'))
                    and not p.relative_to(ROOT).as_posix().startswith('docs/learning/')
                    and p.name!='HANDBOOK-2026-10-22.md']
        candidates += [ROOT/'FEATURE_MATRIX.md',ROOT/'workbench.env.example',ROOT/'README.md',
                       ROOT/'.github/workflows/expansion.yml',ROOT/'docs/learning/EXPANSION_30_MINUTE_ROUTE.md']
        candidates=[p for p in candidates if p.is_file()]
        candidates += [ROOT/p for p in frontend]
        for p in sorted(candidates):
            name=p.relative_to(ROOT).as_posix();new_bytes=p.read_bytes()
            old_bytes=baseline.extractfile(members[name]).read() if name in members else b''
            if new_bytes==old_bytes:continue
            old=old_bytes.decode('utf-8').replace('\r\n','\n');new=new_bytes.decode('utf-8').replace('\r\n','\n')
            changed.append({'path':name,'before':sha256(old_bytes).hexdigest() if name in members else None,
                            'after':sha256(new_bytes).hexdigest(),'line_endings_only':old==new})
            delta.extend(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),
                                            fromfile='baseline/'+name,tofile='current/'+name))
    (evidence/'workspace-diff.patch').write_text(''.join(delta),encoding='utf-8')
    outputs={p.name:sha256(p.read_bytes()).hexdigest() for p in evidence.iterdir()
             if p.is_file() and p.name!='checkpoint.json'}
    result={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'git_present':(ROOT/'.git').exists(),
            'git_history_created':False,'source_archive_sha256':sha256(archive.read_bytes()).hexdigest(),
            'source_identity':sha256(json.dumps(current,sort_keys=True).encode()).hexdigest(),
            'python_file_hashes':current,'changed_files_against_source_archive':changed,'evidence_hashes':outputs,
            'frontend_file_hashes':frontend,
            'derived_research_artifact_hashes':{p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
                for p in (ROOT/'tests/fixtures/expansion_research/index-v1').glob('*') if p.is_file()},
            'source_identity_scope':'Python src/tests/scripts; frontend and synthetic derived research artifact hashes separately recorded',
            'excluded_concurrent_work':'docs/learning/handbook and docs/devlog/HANDBOOK-2026-10-22.md; shared INDEX retains its concurrent navigation entry'}
    (evidence/'checkpoint.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'changed_files':len(changed),'source_identity':result['source_identity'],'git_present':result['git_present']}))


if __name__=='__main__':main()
