"""Real model + two fresh processes prove persistent vector reuse, not fake vectors."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json,math,os
from pathlib import Path
import subprocess,sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))


def child(args):
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
    from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery
    from scripts.expansion_baseline import FILES
    runtime=RetrievalRuntime.from_env({'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen',
        'JOB_AGENT_WORKSPACE_EMBEDDING_PATH':args.model_path,'JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE':args.device})
    work=args.work;ws=SqliteResumeRepository(work/'ws.sqlite');service=CodeRAGService(ws,embedding_backend=runtime.backend)
    if args.stage=='build':
        repo=LongTermRepository(ws);p=repo.create_project('synthetic',ProjectCreate(name='CC0 restart proof'))
        p=repo.publish_files('synthetic',p['project_id'],FILES,origin='zip')
        built=service.build('synthetic',p['project_id'],p['current_snapshot'])
        with ws._connection() as db:
            row=db.execute('SELECT dimension,payload FROM v3_code_vectors WHERE snapshot_id=?',(p['current_snapshot'],)).fetchone()
        vectors=list(json.loads(row['payload']).values());norms=[math.sqrt(sum(x*x for x in v)) for v in vectors]
        assert row['dimension']==runtime.identity.dimension and all(abs(n-1)<1e-4 for n in norms)
        result={'pid':os.getpid(),'project_id':p['project_id'],'snapshot_id':p['current_snapshot'],
            'index_identity':built['vector_index_identity'],'embedding_identity':asdict(runtime.identity),
            'dimension':row['dimension'],'vector_count':len(vectors),'norm_min':min(norms),'norm_max':max(norms)}
    else:
        built=json.loads((work/'build.json').read_text())
        def forbidden(texts):raise AssertionError('document_vectors_reencoded_after_restart')
        runtime.backend.embed_documents=forbidden
        vector=runtime.backend.embed_query('save_receipt')
        norm=math.sqrt(sum(x*x for x in vector));assert abs(norm-1)<1e-4
        found=service.search('synthetic',built['project_id'],CodeQuery(snapshot_id=built['snapshot_id'],query='save_receipt',method='dense'))
        assert found['hits'] and found['retrieval_trace']['index_identity']==built['index_identity']
        assert asdict(runtime.identity)==built['embedding_identity']
        result={'pid':os.getpid(),'index_identity':found['retrieval_trace']['index_identity'],'query_norm':norm,
            'document_reencoding_allowed':False,'hits':len(found['hits']),'trace':found['retrieval_trace']}
    (work/(args.stage+'.json')).write_text(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model-path',required=True);parser.add_argument('--device',default='cuda:0')
    parser.add_argument('--stage',choices=('build','search'));parser.add_argument('--work',type=Path)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.stage:return child(args)
    if args.output is None:parser.error('--output required')
    base=(ROOT/'output/expansion').resolve();base.mkdir(parents=True,exist_ok=True)
    if not base.is_relative_to(ROOT.resolve()):raise RuntimeError('unsafe_restart_temp_root')
    started=perf_counter()
    with TemporaryDirectory(prefix='dense-restart-',dir=base) as directory:
        work=Path(directory)
        for stage in ('build','search'):
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--stage',stage,'--work',str(work),
                '--model-path',args.model_path,'--device',args.device],check=True,timeout=120)
        built=json.loads((work/'build.json').read_text());searched=json.loads((work/'search.json').read_text())
        assert built['pid']!=searched['pid']
        result={'transport':'two_fresh_python_processes','build':built,'search':searched,
                'elapsed_ms':round((perf_counter()-started)*1000,3),'private_material':False}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({'output':str(args.output),'distinct_processes':True,'manifest_preserved':True}),flush=True)


if __name__=='__main__':main()
