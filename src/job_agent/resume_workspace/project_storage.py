"""Repository contracts for the project/index/task transaction domain."""
from dataclasses import dataclass
from typing import Any,Protocol


class ProjectRepository(Protocol):
    def create_project(self,owner,request)->dict:...
    def get_project(self,owner,key)->dict:...
    def list_projects(self,owner)->list:...
    def publish_files(self,owner,key,files,*,origin,commit_sha=None,metadata=None)->dict:...
    def files(self,owner,key,snapshot)->dict:...
    def read_file(self,owner,key,snapshot,path,*,db=None)->tuple:...
    def delete_project(self,owner,key)->None:...


class CodeIndexRepository(Protocol):
    backend:str
    def publish(self,owner,project_id,snapshot,report,symbols,chunks,edges,vector_artifact,*,publish_guard=None,task_claim=None):...
    def report(self,owner,project_id,snapshot)->dict|None:...
    def load(self,owner,project_id,snapshot)->dict:...
    def vector(self,owner,project_id,snapshot,identity)->dict|None:...
    def put_vector(self,owner,project_id,snapshot,identity,dimension,payload)->None:...


class IndexTaskRepository(Protocol):
    lease_seconds:float
    atomic_publication:bool
    def submit(self,owner,project_id,request)->str:...
    def get(self,owner,task_id)->dict:...
    def claim(self)->dict|None:...
    def heartbeat(self,claim)->None:...
    def history(self,owner,project_id)->list:...


@dataclass
class ProjectPersistence:
    projects:ProjectRepository
    indexes:CodeIndexRepository
    tasks:IndexTaskRepository
    backend:str
    database:Any=None

    def close(self):
        if self.database is not None:self.database.close()


def sqlite_persistence(workspace):
    from job_agent.resume_workspace.long_term import LongTermRepository
    from job_agent.resume_workspace.sqlite_code_indexes import SqliteCodeIndexRepository
    from job_agent.resume_workspace.tasks import TaskRepository
    projects=LongTermRepository(workspace)
    return ProjectPersistence(projects,SqliteCodeIndexRepository(workspace,projects),TaskRepository(workspace,projects=projects),'sqlite')


def persistence_from_env(workspace,env=None,*,lease_seconds=30):
    import os
    env=os.environ if env is None else env
    selected=env.get('JOB_AGENT_PROJECT_BACKEND','sqlite')
    dispatch_mode=env.get('JOB_AGENT_INDEX_DISPATCH','polling')
    if dispatch_mode not in ('polling','redis'):raise ValueError('index_dispatch_mode_invalid')
    if selected=='sqlite':
        if dispatch_mode!='polling':raise ValueError('redis_dispatch_requires_postgresql')
        bundle=sqlite_persistence(workspace);bundle.tasks.lease_seconds=lease_seconds
        return bundle
    if selected!='postgresql':raise ValueError('project_backend_invalid')
    dsn=env.get('JOB_AGENT_PROJECT_DSN','')
    if not dsn.strip():raise ValueError('project_postgres_dsn_required')
    from job_agent.resume_workspace.postgres_projects import postgres_persistence
    return postgres_persistence(dsn,schema=env.get('JOB_AGENT_PROJECT_SCHEMA','job_agent_v3'),lease_seconds=lease_seconds,dispatch_mode=dispatch_mode)
