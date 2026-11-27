"""Independent Outbox publisher/index worker and explicit maintenance commands."""
import argparse,json,os,sys
from pathlib import Path
from time import monotonic,sleep
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def main():
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.repository import WorkspaceConflict
    from job_agent.resume_workspace.project_storage import persistence_from_env
    from job_agent.resume_workspace.index_dispatch import IndexOutboxPublisher,RedisIndexWorker
    from job_agent.resume_workspace.index_streams import IndexStreamQueue
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=['publish','work','reconcile','inspect','switch-mode'])
    parser.add_argument('--once',action='store_true');parser.add_argument('--consumer',default='index-'+str(os.getpid()))
    parser.add_argument('--database',type=Path,default=ROOT/'output/resume-workspace/workspace.sqlite')
    parser.add_argument('--lease-seconds',type=float,default=30);parser.add_argument('--min-idle-ms',type=int,default=1500)
    parser.add_argument('--reconcile-age',type=float,default=30);parser.add_argument('--switch-to',choices=['polling','redis'])
    parser.add_argument('--fault',choices=['after_xadd_before_outbox_mark','after_claim','after_commit_before_ack','after_derived_before_pointer'])
    parser.add_argument('--hold-after-claim',type=float,default=0,help='Bounded real-process contention probe; requires --once')
    args=parser.parse_args()
    if args.fault and not args.once:parser.error('--fault requires --once')
    if not 0<=args.hold_after_claim<=2 or (args.hold_after_claim and not args.once):parser.error('hold requires --once and 0..2 seconds')
    if not .3<=args.lease_seconds<=120 or not 0<=args.min_idle_ms<=120000:parser.error('invalid lease/reclaim bound')
    if not .1<=args.reconcile_age<=3600:parser.error('invalid reconcile age')
    if args.role in ('publish','work') and not os.environ.get('JOB_AGENT_INDEX_REDIS_URL'):parser.error('JOB_AGENT_INDEX_REDIS_URL required')
    ws=SqliteResumeRepository(args.database);bundle=persistence_from_env(ws,lease_seconds=args.lease_seconds);queue=None
    try:
        if bundle.backend!='postgresql':parser.error('PostgreSQL project authority required')
        dispatch=bundle.tasks.dispatch
        if args.role=='switch-mode':
            if not args.switch_to:parser.error('--switch-to required')
            dispatch.change_mode(args.switch_to);print(json.dumps({'mode_changed':args.switch_to,'old_processes_must_reopen':True}));return
        if args.role=='reconcile':print(json.dumps({'reconciled':dispatch.reconcile(age_seconds=args.reconcile_age)}));return
        if args.role=='inspect':
            result=dispatch.monitoring()
            if os.environ.get('JOB_AGENT_INDEX_REDIS_URL'):
                queue=IndexStreamQueue(os.environ['JOB_AGENT_INDEX_REDIS_URL'],dispatch.authority);queue.ensure_group();result['stream']=queue.monitoring()
            print(json.dumps(result));return
        if dispatch.mode!='redis':parser.error('redis dispatch mode required')
        queue=IndexStreamQueue(os.environ['JOB_AGENT_INDEX_REDIS_URL'],dispatch.authority);queue.ensure_group()
        def fault(stage,*_):
            if stage=='after_claim' and args.hold_after_claim:
                print(json.dumps({'holding_claim_seconds':args.hold_after_claim}),flush=True);sleep(args.hold_after_claim)
            if stage==args.fault:
                print(json.dumps({'injected_process_exit':stage}),flush=True);os._exit(71)
        if args.role=='publish':actor=IndexOutboxPublisher(dispatch,queue,failpoint=fault)
        else:
            from job_agent.resume_workspace.code_rag import CodeRAGService
            from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
            runtime=RetrievalRuntime.from_env()
            code=CodeRAGService(ws,projects=bundle.projects,indexes=bundle.indexes,embedding_backend=runtime.backend,
                embedding_identity=runtime.identity or 'disabled',reranker=runtime.reranker,retrieval_settings=runtime.settings)
            bundle.tasks.config_identity=code.indexing_config_identity;bundle.indexes.failpoint=fault
            actor=RedisIndexWorker(bundle.tasks,code,queue,consumer=args.consumer,min_idle_ms=args.min_idle_ms,failpoint=fault)
        # A loss/trim of Redis messages is recovered by a visible PG reconciliation.
        next_reconcile=0
        while True:
            try:
                if args.role=='publish':
                    if monotonic()>=next_reconcile:
                        dispatch.reconcile(age_seconds=args.reconcile_age);next_reconcile=monotonic()+max(1,args.reconcile_age/2)
                    outcome=actor.publish_once()
                else:outcome=actor.process_once()
                if args.once:print(json.dumps({'role':args.role,'outcome':outcome}),flush=True);return
            except KeyboardInterrupt:return
            except WorkspaceConflict as exc:
                if str(exc) in ('index_dispatch_mode_changed','index_dispatch_mode_conflict'):raise
                if args.once:raise
            except Exception:
                # No ACK on transport/DB uncertainty. CLI once must signal failure.
                if args.once:raise
            sleep(.2)
    finally:
        if queue:queue.close()
        bundle.close()


if __name__=='__main__':main()
