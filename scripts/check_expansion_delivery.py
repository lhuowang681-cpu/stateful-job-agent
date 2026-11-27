"""Verify all package bytes, extract to a new bounded folder, run CPU gate + real HTTP."""
import argparse,json,os,stat,subprocess,sys,zipfile
from hashlib import sha256
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]


def digest(data):return sha256(data).hexdigest()
def verify(path,expected):
    if digest(path.read_bytes())!=expected:raise ValueError('delivery_zip_hash_changed')
    with zipfile.ZipFile(path) as archive:
        info=archive.infolist();names=[i.filename for i in info]
        if len(names)!=len(set(names)) or sum(i.file_size for i in info)>256*1024*1024:raise ValueError('delivery_archive_budget')
        for i in info:
            p=PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename or ':' in i.filename or stat.S_ISLNK(i.external_attr>>16):raise ValueError('delivery_archive_path')
        manifests=[name for name in names if name.endswith('_MANIFEST.json') and '/' not in name]
        if len(manifests)!=1:raise ValueError('delivery_archive_manifest')
        manifest=json.loads(archive.read(manifests[0]));files=manifest['files']
        if set(files)|set(manifests)!=set(names):raise ValueError('delivery_archive_coverage')
        for name,expected_hash in files.items():
            if digest(archive.read(name))!=expected_hash:raise ValueError('delivery_member_hash_changed')
        if archive.testzip() is not None:raise ValueError('delivery_archive_crc')
        return len(files)


def extract(path,dest):
    # Only called after verify; still check resolved writes and refuse overwrite.
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            target=(dest/item.filename).resolve()
            if not target.is_relative_to(dest.resolve()):raise ValueError('delivery_extract_escape')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(archive.read(item))


def main():
    p=argparse.ArgumentParser();p.add_argument('--delivery',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    dest=a.output.resolve();allowed=(ROOT/'output/expansion').resolve()
    if not dest.is_relative_to(allowed):p.error('new output must stay inside this project output/expansion')
    dest.mkdir(parents=True,exist_ok=False);delivery=json.loads(a.delivery.read_text(encoding='utf-8'))
    expected={'job-agent-expansion-source.zip','job-agent-expansion-learning.zip','job-agent-expansion-research.zip'}
    if {p['file'] for p in delivery['packages']}!=expected:raise ValueError('delivery_package_set')
    verified=[];base=a.delivery.parent.resolve()
    for item in delivery['packages']:
        path=base/item['file'];n=verify(path,item['sha256']);verified.append({'file':item['file'],'sha256':item['sha256'],'verified_files':n})
    source=dest/'source';source.mkdir();learning=dest/'learning';learning.mkdir()
    extract(base/'job-agent-expansion-source.zip',source);extract(base/'job-agent-expansion-research.zip',source);extract(base/'job-agent-expansion-learning.zip',learning)
    env={k:v for k,v in os.environ.items() if not k.startswith(('JOB_AGENT_','QWEN_'))}
    checks=[]
    commands=[('offline_gate',[sys.executable,str(source/'scripts/expansion_ci.py'),'--output',str(dest/'offline-ci'),'--gate-only']),
              ('http_startup',[sys.executable,str(source/'scripts/expansion_delivery_smoke.py'),'--output',str(dest/'http-smoke.json')])]
    for name,command in commands:
        r=subprocess.run(command,cwd=source,env=env,capture_output=True,text=True,timeout=120)
        checks.append({'name':name,'returncode':r.returncode,'stdout':r.stdout[-2000:],'stderr':r.stderr[-2000:]})
        if r.returncode:break
    result={'status':'passed' if len(checks)==2 and all(x['returncode']==0 for x in checks) else 'failed',
        'archives':verified,'fresh_directory':str(dest),'fresh_dependency_install':False,'checks':checks,
        'dependency_condition':'existing dedicated runtime; versions in delivered requirements-ci-observed.txt',
        'source_and_research_manifest_hashes_verified':True,'executed_user_actions':0}
    (dest/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if result['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
