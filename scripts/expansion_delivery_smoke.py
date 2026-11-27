"""Fresh extracted source, actual HTTP startup/static files and default owner gate."""
import argparse,json,re,sys
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def main():
    import httpx
    import job_agent.resume_workspace.api as api
    import job_agent.nodes.fit_verdict as legacy_fit
    from scripts.demo_resume_workbench import build_demo_app,DEMO_CODE
    from scripts.expansion_baseline import running
    from scripts.inspect_unified_trace import inspect
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert Path(api.__file__).resolve().is_relative_to(ROOT/'src')
    import fit_verdict_engine.prompt_contract as fit_contract
    assert Path(fit_contract.__file__).resolve().is_relative_to(ROOT/'fit_verdict_engine')
    with TemporaryDirectory(prefix='delivery-smoke-') as folder:
        app=build_demo_app(Path(folder)/'synthetic.sqlite')
        with running(app) as url,httpx.Client(base_url=url,timeout=20) as c:
            health=c.get('/health/live');assert health.status_code==200
            page=c.get('/');assert page.status_code==200 and '<html' in page.text
            scripts=re.findall(r'<script[^>]+src="([^"]+)"',page.text);assert scripts
            for script in scripts:assert c.get(script).status_code==200
            assert c.get('/api/v2/resumes').status_code==401
            resumes=c.get('/api/v2/resumes',headers={'Authorization':'Bearer '+DEMO_CODE});assert resumes.status_code==200 and resumes.json()==[]
            paths={r.path for r in app.routes}
            assert {'/api/v2/interviews/{session_id}/trace','/api/v2/tasks/{task_id}/trace','/api/v2/rewrites/{run_id}/trace'}<=paths
    traces=[inspect(path) for path in (ROOT/'docs/evaluation/expansion/trace-examples').glob('*.jsonl')]
    assert len(traces)==7 and all(t['executed_actions']==0 for t in traces)
    result={'status':'passed','fresh_directory':str(ROOT),'imported_current_extracted_source':True,
        'real_loopback_http':True,'checks':['health_200','frontend_html_200','bundled_javascript_200','anonymous_401','synthetic_owner_empty_resumes_200','three_trace_routes_registered'],
        'trace_examples_checked':len(traces),'model_calls':0,'private_data_used':False,'fresh_dependency_install':False,
        'dependency_condition':'existing dedicated Python 3.12 runtime; observed versions delivered separately'}
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'status':'passed','checks':len(result['checks'])}))


if __name__=='__main__':main()
