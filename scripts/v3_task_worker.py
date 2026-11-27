"""Standalone local index worker; no model requests or source execution."""
from pathlib import Path
from threading import Event
import argparse,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.code_rag import CodeRAGService
from job_agent.resume_workspace.tasks import TaskRepository,IndexTaskWorker


class InjectedWorkerExit(BaseException):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,default=ROOT/'output/demo-v3/workspace.sqlite')
    p.add_argument('--once',action='store_true');p.add_argument('--crash-after-index',action='store_true')
    p.add_argument('--lease-seconds',type=float,default=30);args=p.parse_args()
    if not .3<=args.lease_seconds<=120:p.error('lease must be .3..120 seconds')
    if args.crash_after_index and not args.once:p.error('fault injection requires --once')
    from job_agent.resume_workspace.project_storage import persistence_from_env
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    ws=SqliteResumeRepository(args.database);persistence=persistence_from_env(ws,lease_seconds=args.lease_seconds)
    store=persistence.tasks;runtime=RetrievalRuntime.from_env()
    code=CodeRAGService(ws,projects=persistence.projects,indexes=persistence.indexes,
        embedding_backend=runtime.backend,embedding_identity=runtime.identity or 'disabled',
        retrieval_settings=runtime.settings,reranker=runtime.reranker)
    if hasattr(store,'config_identity'):store.config_identity=code.indexing_config_identity
    def fault(stage):raise InjectedWorkerExit()
    worker=IndexTaskWorker(store,code,failpoint=fault if args.crash_after_index else None)
    try:
        if args.once:worker.process_once()
        else:
            worker.start()
            try:Event().wait()
            except KeyboardInterrupt:pass
            finally:worker.stop()
    except InjectedWorkerExit:
        print('INJECTED_EXIT_AFTER_INDEX_COMMIT; atomic PG tasks already committed, SQLite tasks recover by lease',flush=True)
        return 70
    finally:persistence.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
