"""Authenticated evidence collection with the same real registry/policy/executor."""
from typing import Literal
from fastapi import Depends
from pydantic import Field,model_validator
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.evidence_pack import EvidenceBudget,EvidencePack
from job_agent.resume_workspace.interview_tools import InterviewTools,new_retrieval_state


class EvidenceRetrieveRequest(StrictModel):
    query:str=Field(min_length=1,max_length=600)
    scope:Literal['private_project','public_docs','public_questions']='public_docs'
    project_id:str|None=Field(default=None,max_length=100)
    snapshot_id:str|None=Field(default=None,max_length=100)
    claims:list[str]=Field(default_factory=list,max_length=3)
    budget:EvidenceBudget=Field(default_factory=EvidenceBudget)

    @model_validator(mode='after')
    def scope_shape(self):
        if self.scope=='private_project' and not (self.project_id and self.snapshot_id):raise ValueError('private_scope_required')
        if self.scope!='private_project' and (self.project_id or self.snapshot_id):raise ValueError('unexpected_private_scope')
        if any(not c.strip() or len(c)>600 for c in self.claims):raise ValueError('claim_input_invalid')
        return self


def install_evidence_routes(app,workspace,owner,knowledge,code):
    @app.post('/api/v2/evidence/retrieve',response_model=EvidencePack)
    def retrieve(request:EvidenceRetrieveRequest,user:str=Depends(owner)):
        tools=InterviewTools(workspace,knowledge,code,user,request.project_id,request.snapshot_id)
        return tools.retrieve_pack(new_retrieval_state(),'interviewer',request.query,
            scope_kind=request.scope,claims=request.claims,budget=request.budget)
