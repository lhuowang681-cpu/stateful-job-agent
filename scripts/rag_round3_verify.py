"""Post-package checks; fresh Linux environment and actual installed HTTP."""
import argparse,json,os,platform,shutil,subprocess,sys,time,zipfile
from hashlib import sha256
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--delivery',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--installer',choices=['pip','uv'],default='pip');a=p.parse_args()
    base=a.delivery.resolve().parent;out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    delivery=json.loads(a.delivery.read_text());source=out/'source';research=out/'research';learning=out/'learning'
    report={'source_git_revision':delivery['source_git_revision'],'platform':platform.platform(),'python':sys.version,
        'archives':[],'steps':[],'model_calls':0,'paid_calls':0,'human_reviewed':0,'status':'running'}
    env={k:v for k,v in os.environ.items() if not k.startswith(('JOB_AGENT_','QWEN_','PIP_','UV_'))}
    env.update(UV_HTTP_TIMEOUT='25',UV_HTTP_RETRIES='1',UV_CONCURRENT_DOWNLOADS='8')
    report['installer']=a.installer
    try:
        for item in delivery['packages']:
            path=base/item['file'];assert sha256(path.read_bytes()).hexdigest()==item['sha256']
            dest=source if item['file'].endswith('-source.zip') else learning if item['file'].endswith('-learning.zip') else research
            dest.mkdir(exist_ok=False)
            with zipfile.ZipFile(path) as archive:
                infos=archive.infolist();names=[i.filename for i in infos]
                assert len(names)==len(set(names)) and sum(i.file_size for i in infos)<256*1024*1024
                manifests=[n for n in names if n.endswith('_MANIFEST.json') and '/' not in n];assert len(manifests)==1
                manifest=json.loads(archive.read(manifests[0]));assert set(manifest['files'])|set(manifests)==set(names)
                assert archive.testzip() is None
                for entry in infos:
                    n=entry.filename;target=(dest/n).resolve()
                    assert '\\' not in n and ':' not in n and target.is_relative_to(dest) and '..' not in Path(n).parts
                    assert (entry.external_attr>>16)&0o170000!=0o120000
                    data=archive.read(entry)
                    if n not in manifests:assert sha256(data).hexdigest()==manifest['files'][n]
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as f:f.write(data)
                assert all(sha256((dest/n).read_bytes()).hexdigest()==h for n,h in manifest['files'].items())
            report['archives'].append({'file':path.name,'sha256':item['sha256'],'files_verified':len(manifest['files']),'crc_and_safe_extract':'passed'})
        for dest in (source,learning):
            for n in ('docs/devlog/_PHASE_TEMPLATE.md','docs/tech-specs/INCREMENT_SPEC_TEMPLATE.md'):assert (dest/n).is_file()
        joint=research/'research/f4-fixed-source-v2';m=json.loads((joint/'manifest.json').read_text())
        assert all(sha256((source/n).read_bytes()).hexdigest()==h for n,h in m['source_identity']['files'].items())
        report['joint_product_source_identity']=m['source_identity']['hash']
        def step(name,command,cwd=source,timeout=180):
            started=time.monotonic();log=out/(name+'.log')
            with log.open('w',encoding='utf-8') as f:
                r=subprocess.run([str(x) for x in command],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
            report['steps'].append({'name':name,'exit_code':r.returncode,'seconds':round(time.monotonic()-started,2),'log':log.name})
            (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps({'step':name,'exit_code':r.returncode}),flush=True)
            assert r.returncode==0,name
        venv=out/'venv';step('create-empty-env',[sys.executable,'-m','venv',venv])
        py=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        constraint=source/'docs/evaluation/expansion/requirements-ci-review-linux-20261023.txt'
        assert os.name!='nt','This fresh install lane uses the observed Linux constraint; Windows is separately recorded.'
        command=([py,'-m','pip','install','--index-url','https://pypi.org/simple','--timeout','25','--retries','1'] if a.installer=='pip'
            else [shutil.which('uv') or '/root/.local/bin/uv','pip','install','--python',py,'--index-url','https://pypi.org/simple'])
        step('fresh-install',command+['-c',constraint,'.[dev,workbench]'],timeout=360)
        step('pip-check',[py,'-m','pip','check'])
        step('dependency-freeze',[py,'-m','pip','freeze'])
        step('installed-main-http',[py,'-I',source/'scripts/review_installed_http_smoke.py',out/'installed-main-http.json','--launcher'])
        step('installed-cli',[py,'-I','-m','job_agent.cli','--help'])
        step('extracted-http-trace',[py,source/'scripts/expansion_delivery_smoke.py','--output',out/'extracted-http-trace.json'])
        step('stable-offline-gate',[py,source/'scripts/expansion_ci.py','--output',out/'offline-ci'],timeout=240)
        code="import sys,pathlib;sys.path[:0]=[str(pathlib.Path.cwd()/'src'),str(pathlib.Path.cwd())];from scripts.rag_round3_package import audit_joint;root=pathlib.Path.cwd();sources={p.relative_to(root).as_posix():p.read_bytes() for p in (root/'src').rglob('*.py')};audit_joint(pathlib.Path(sys.argv[1]).resolve(),sources);print('source-only audit passed')"
        step('joint-pure-source-audit',[py,'-c',code,joint])
        report['status']='passed';report['fresh_dependency_install']=True
    except Exception as e:report.update(status='failed',error_type=type(e).__name__,detail=str(e)[:500])
    finally:
        (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'status':report['status'],'steps':len(report['steps'])}),flush=True)
    if report['status']!='passed':raise SystemExit(1)
if __name__=='__main__':main()
