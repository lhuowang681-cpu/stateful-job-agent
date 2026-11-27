"""Offline project-domain migration. Never changes/deletes the source database."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def main():
    from job_agent.resume_workspace.project_migration import sqlite_snapshot,import_to_empty_postgres
    from job_agent.resume_workspace.postgres_projects import postgres_persistence
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group(required=True);modes.add_argument('--dry-run',action='store_true');modes.add_argument('--apply',action='store_true')
    parser.add_argument('--source-quiesced',action='store_true',help='Source writers are stopped and remain stopped during cutover')
    args=parser.parse_args()
    if args.report.exists():parser.error('report already exists')
    if args.apply and not args.source_quiesced:parser.error('--apply requires --source-quiesced')
    if args.apply and not os.environ.get('JOB_AGENT_PROJECT_DSN','').strip():parser.error('JOB_AGENT_PROJECT_DSN required')
    data,report=sqlite_snapshot(args.source,args.backup)
    report.update(mode='apply' if args.apply else 'dry_run',production_migration_verified=False,
        source_preserved=True,source_writers_quiesced_asserted=args.source_quiesced)
    if args.apply:
        bundle=postgres_persistence(os.environ['JOB_AGENT_PROJECT_DSN'],schema=os.environ.get('JOB_AGENT_PROJECT_SCHEMA','job_agent_v3'))
        try:report['import']=import_to_empty_postgres(bundle,data)
        finally:bundle.close()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
    print(json.dumps({'mode':report['mode'],'counts':report['counts'],'source_preserved':True}))


if __name__=='__main__':main()
