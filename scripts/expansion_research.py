"""Prepare once, score explicit splits, restore fixed indices, or run the CPU offline gate."""
import argparse,json,os,sys
from pathlib import Path
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.research_contract import prepare,evaluate,replay,freeze_gate,check_gate,read_json,write_new
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','evaluate','replay','freeze-gate','gate'))
    p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-path');p.add_argument('--rerank-path');p.add_argument('--device',default='cuda:0')
    p.add_argument('--split',choices=('dev','test'),default='dev');p.add_argument('--score-heldout',action='store_true')
    p.add_argument('--bm25-only',action='store_true');p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--reference',type=Path);p.add_argument('--gate-file',type=Path)
    p.add_argument('--dataset',type=Path,default=ROOT/'docs/evaluation/expansion/candidates-v3.json')
    p.add_argument('--source-kind',choices=('synthetic','owner_project_source'),default='synthetic')
    a=p.parse_args();runtime=None;start=perf_counter()
    if a.command in ('prepare','replay') or (a.command=='evaluate' and not a.bm25_only):
        if not a.model_path or not a.rerank_path:p.error('explicit local model and rerank directories required')
        runtime=RetrievalRuntime.from_env({'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen',
            'JOB_AGENT_WORKSPACE_EMBEDDING_PATH':a.model_path,'JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE':a.device,
            'JOB_AGENT_WORKSPACE_RERANK_PATH':a.rerank_path,'JOB_AGENT_WORKSPACE_RERANK_DEVICE':a.device})
    loaded=round((perf_counter()-start)*1000,3)
    if a.command=='prepare':
        result=prepare(ROOT,a.bundle,a.dataset,runtime,repeats=a.repeats,source_kind=a.source_kind)
        write_new(a.output,{'status':'prepared','pid':os.getpid(),'model_load_and_hash_ms':loaded,'manifest':result})
    elif a.command=='evaluate':
        result=evaluate(ROOT,a.bundle,a.output,split=a.split,runtime=runtime,score_heldout=a.score_heldout,
                        variants=['A_bm25'] if a.bm25_only else None,repeats=1 if a.bm25_only else None)
    elif a.command=='replay':
        if not a.reference:p.error('--reference required')
        result=replay(ROOT,a.bundle,a.reference,a.output,split=a.split,runtime=runtime)
    elif a.command=='freeze-gate':
        if not a.reference:p.error('--reference required')
        result=freeze_gate(read_json(a.reference/'run.json'),a.output)
    else:
        if not a.gate_file:p.error('--gate-file required')
        run=evaluate(ROOT,a.bundle,a.output,variants=['A_bm25'],repeats=1,strict_algorithm=False)
        result=check_gate(run,a.gate_file);write_new(a.output/'gate.json',result)
    print(json.dumps({'command':a.command,'status':result.get('status','recorded'),'pid':os.getpid(),
        'model_load_and_hash_ms':loaded,'output':str(a.output)},ensure_ascii=False),flush=True)
    if result.get('status')=='failed':raise SystemExit(1)


if __name__=='__main__':main()
