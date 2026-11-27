"""Stable offline lane; dedicated PG/Redis and real models remain explicit separate lanes."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.research_contract import evaluate,check_gate,write_new


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--gate-only',action='store_true');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    from scripts.review_materialize_fixture import materialize
    bundle=materialize(a.output/'portable-index-v2');gate=bundle/'portable-gate.json'
    run=evaluate(ROOT,bundle,a.output/'retrieval',variants=['A_bm25'],repeats=1,strict_algorithm=False)
    checked=check_gate(run,gate);write_new(a.output/'gate.json',checked)
    if checked['status']!='passed':raise SystemExit(1)
    if not a.gate_only:
        # No accidental DB credentials/model paths inherited from a developer shell.
        env={k:v for k,v in os.environ.items() if not k.startswith(('JOB_AGENT_TEST_','JOB_AGENT_WORKSPACE_EMBEDDING','JOB_AGENT_WORKSPACE_RERANK'))}
        patterns=('test_review_*.py','test_rag_*.py','test_resume_*.py','test_workbench*.py','test_v3_*.py','test_agent_budgets.py',
                  'test_agent_checkpoint.py','test_agent_loop.py','test_agent_policy.py','test_agent_tool_registry.py',
                  'test_backend_service.py','test_reliability_fault_injection.py','test_source_audit_regressions.py')
        tests=sorted({str(p.relative_to(ROOT)) for pattern in patterns for p in (ROOT/'tests').glob(pattern)})
        code=subprocess.call([sys.executable,'-m','pytest','-q',*tests,'--junitxml='+str(a.output/'contracts.xml')],cwd=ROOT,env=env)
        if code:raise SystemExit(code)
    print(json.dumps({'status':'passed','offline_retrieval_gate':'passed','generative_calls':0,'real_models_loaded':False,'real_services_lane':'not_this_command'}))


if __name__=='__main__':main()
