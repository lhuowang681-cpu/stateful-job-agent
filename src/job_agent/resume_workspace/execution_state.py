"""Shared, bounded execution state carried by both existing business graphs."""
from __future__ import annotations
from hashlib import sha256
from datetime import datetime,UTC
import json
from typing import Any,Literal
from pydantic import Field
from job_agent.schemas import StrictModel


def state_hash(value):
    if hasattr(value,'model_dump'):value=value.model_dump(mode='json')
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def completed_role_failure(exc):
    from job_agent.llm.harness import LLMInvocationError
    return isinstance(exc,LLMInvocationError) and exc.error_code in (
        'invalid_json','schema_error','provider_contract_error','contract_error','http_error','rate_limit','completion_truncated','input_token_budget','local_model_busy')


class RoleFeedback(StrictModel):
    sender:str
    revision:int
    outcome:str
    constraint:str=Field(max_length=1200)
    artifact_hash:str
    feedback_id:str=''
    details:dict[str,Any]=Field(default_factory=dict)

    def identified(self):
        self.feedback_id='feedback-'+state_hash(self.model_dump(exclude={'feedback_id'}))
        return self


class ExecutionEvent(StrictModel):
    seq:int
    role:str
    phase:Literal['started','completed','gate','route','decision','stopped']
    revision:int
    input_hash:str|None=None
    output_hash:str|None=None
    feedback_id:str|None=None
    code:str|None=None
    # Loading an older checkpoint must not invent an event time at deserialization.
    recorded_at:str|None=None
    metrics:dict[str,Any]=Field(default_factory=dict)


class SharedRunState(StrictModel):
    schema_version:Literal['shared-run-1']='shared-run-1'
    run_id:str
    trace_id:str
    owner_id:str
    task:Literal['rewrite','interview']
    source_identity:dict[str,str]
    model_identity:dict[str,str]
    node:str='coordinator'
    revision:int=0
    status:str='running'
    next_action:str=''
    latest_feedback:RoleFeedback|None=None
    artifact_hashes:list[str]=Field(default_factory=list,max_length=24)
    evidence_pack_ids:list[str]=Field(default_factory=list,max_length=10)
    limits:dict[str,int]=Field(default_factory=dict)
    usage:dict[str,Any]=Field(default_factory=dict)
    context_incomplete:bool=False
    recovery:Literal['none','uncertain_dispatch','expired_execution','context_incomplete']='none'
    attempt:int=1
    execution_token:str|None=None
    lease_until:float=0
    event_seq:int=0
    events:list[ExecutionEvent]=Field(default_factory=list,max_length=128)
    approval:dict[str,Any]|None=None
    independent_truth:Literal['not_verified']='not_verified'

    def record(self,role,phase,*,input_value=None,output_value=None,code=None,metrics=None):
        if len(self.events)>=128:raise ValueError('execution_event_budget')
        self.event_seq+=1;self.node=role
        self.events.append(ExecutionEvent(seq=self.event_seq,role=role,phase=phase,revision=self.revision,
            recorded_at=datetime.now(UTC).isoformat(),
            input_hash=state_hash(input_value) if input_value is not None else None,
            output_hash=state_hash(output_value) if output_value is not None else None,
            feedback_id=self.latest_feedback.feedback_id if self.latest_feedback else None,code=code,metrics=metrics or {}))

    def validate_binding(self,owner,run_id,source_identity):
        if self.owner_id!=owner or self.run_id!=run_id or self.source_identity!=source_identity:
            raise ValueError('execution_identity_changed')
        if self.event_seq!=len(self.events) or [e.seq for e in self.events]!=list(range(1,self.event_seq+1)):
            raise ValueError('execution_event_integrity_failed')
        if self.latest_feedback and self.latest_feedback.model_copy(deep=True).identified()!=self.latest_feedback:
            raise ValueError('execution_feedback_integrity_failed')

    def role_context(self):
        # No owner, lease token, raw history, resume contact fields or rubric.
        return {'run_id':self.run_id,'schema_version':self.schema_version,'revision':self.revision,
            'source_identity':self.source_identity,'evidence_pack_ids':self.evidence_pack_ids,
            'latest_feedback':self.latest_feedback.model_dump() if self.latest_feedback else None,
            'context_incomplete':self.context_incomplete,'independent_truth':'not_verified'}


def interview_identity(s):
    identity={'resume_id':s.resume_id,'version_id':s.version_id,'version_hash':s.version_hash,
        'jd_hash':state_hash(s.jd_text),'project_id':s.project_id or '', 'snapshot_id':s.snapshot_id or ''}
    if s.learning_observation_id:identity.update(learning_observation_id=s.learning_observation_id,learning_condition_hash=s.learning_condition_hash or '')
    return identity


def sync_interview(s,owner=None):
    if s.execution is None:
        if owner is None:raise ValueError('execution_owner_required')
        s.execution=SharedRunState(run_id=s.session_id,trace_id='trace-'+s.session_id,owner_id=owner,task='interview',
            source_identity=interview_identity(s),model_identity={'provider':s.provider,'model':s.model,
                'prompt':'rag-project-source-2' if s.current and s.current.evidence_boundary else 's4-interview-1'},
            limits={'role_calls':s.max_turns*2,'tools':18,'input_chars':30000,'active_ms':s.max_turns*60000})
    s.execution.revision=s.revision;s.execution.status=s.status;s.execution.next_action=s.next_node
    s.execution.usage={**s.usage.model_dump(),'tool_calls':s.tool_calls}
    s.execution.evidence_pack_ids=[p.pack_id for p in s.evidence_packs]
    return s.execution
