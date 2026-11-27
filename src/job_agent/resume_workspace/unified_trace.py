"""Read-only projection of existing checkpoints, tool traces and task events.

No provider/tool invocation, replay action, source text or authentication material.
Cross-stream order is an export order, never a fabricated global clock order.
"""
from __future__ import annotations
from datetime import datetime,timezone
import json,math
from typing import Literal
from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.execution_state import SharedRunState,state_hash


def opaque(value):return 'id-'+state_hash(str(value)) if value is not None else None
def integer(value):return value if type(value) is int and value>=0 else None
def number(value):return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
def timestamp(value):
    if value is None:return None
    if type(value) in (int,float):
        try:return datetime.fromtimestamp(value,timezone.utc).isoformat()
        except (ValueError,OverflowError,OSError):return None
    if isinstance(value,datetime):return value.isoformat() if value.tzinfo else None
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.isoformat() if parsed.tzinfo else None
        except ValueError:return None
    return None


class UnifiedTraceEvent(StrictModel):
    schema_version:Literal['job-agent-trace-1']='job-agent-trace-1'
    trace_id:str
    run_id:str
    span_id:str
    parent_span_id:str|None=None
    seq:int=Field(ge=0)
    source_stream:Literal['run_state','role_events','tools','retrieval_rounds','task_events','task_snapshot']
    source_seq:int=Field(ge=0)
    kind:Literal['run','role','tool','retrieval','task']
    phase:str
    status:str
    attempt:int|None=Field(default=None,ge=0)
    revision:int|None=Field(default=None,ge=0)
    role_id:str|None=None
    tool_id:str|None=None
    recorded_at_utc:str|None=None
    started_at_utc:str|None=None
    ended_at_utc:str|None=None
    duration_ms:float|None=Field(default=None,ge=0)
    time_quality:Literal['recorded','duration_only','unknown']='unknown'
    model_identity_hash:str|None=None
    material_hash:str|None=None
    input_hash:str|None=None
    output_hash:str|None=None
    evidence_ids:list[str]=Field(default_factory=list,max_length=40)
    config_identity:str|None=None
    index_identity:str|None=None
    input_tokens:int|None=Field(default=None,ge=0)
    output_tokens:int|None=Field(default=None,ge=0)
    cost:float|None=Field(default=None,ge=0)
    usage_scope:Literal['run_aggregate','call','not_applicable','unknown']='unknown'
    usage_missing_reason:str|None=None
    provider_calls:int|None=Field(default=None,ge=0)
    error_code_id:str|None=None
    fallback_used:bool|None=None
    approval_status:Literal['recorded','absent']='absent'
    approval_hash:str|None=None
    correlation_id:str|None=None


def _model_hash(metrics,default):
    identity={k:metrics[k] for k in ('provider','model','skill_id','skill_version','prompt_version') if metrics.get(k) is not None}
    return state_hash(identity or default) if identity or default else None


def from_execution(execution,*,tool_trace=(),packs=()):
    if execution is None:
        from job_agent.resume_workspace.repository import WorkspaceConflict
        raise WorkspaceConflict('trace_legacy_execution_unavailable')
    state=execution if isinstance(execution,SharedRunState) else SharedRunState.model_validate(execution)
    state.validate_binding(state.owner_id,state.run_id,state.source_identity)
    rid=opaque(state.run_id);tid=opaque(state.trace_id);root=rid+'-root';rows=[]
    material=state_hash(state.source_identity);model=state_hash(state.model_identity)
    def emit(**kw):
        row=UnifiedTraceEvent(trace_id=tid,run_id=rid,seq=len(rows),material_hash=material,
            model_identity_hash=model,**kw);rows.append(row.model_dump(mode='json'))
    usage=state.usage;calls=integer(usage.get('provider_calls'));rule_only=calls==0
    emit(span_id=root,source_stream='run_state',source_seq=0,kind='run',phase='snapshot',
        status=state.status if state.status in ('active','running','complete','failed','unknown','accepted','rejected','awaiting_approval','needs_input','paused','pending') else 'other',
        attempt=state.attempt,revision=state.revision,input_hash=material,
        input_tokens=0 if rule_only else integer(usage.get('input_tokens')),
        output_tokens=0 if rule_only else integer(usage.get('output_tokens')),cost=number(usage.get('cost')),
        usage_scope='run_aggregate',provider_calls=calls,
        usage_missing_reason='no_provider_calls' if rule_only else 'cost_unavailable_or_provider_usage_missing',
        approval_status='recorded' if state.approval else 'absent',approval_hash=state_hash(state.approval) if state.approval else None)
    active={}
    for event in state.events:
        key=(event.role,event.revision)
        if event.phase=='started':active[key]=rid+'-role-'+str(event.seq)
        span=active.get(key,rid+'-event-'+str(event.seq));metrics=event.metrics
        time=timestamp(event.recorded_at);scope='call' if event.phase=='completed' and metrics else 'not_applicable' if rule_only else 'unknown'
        emit(span_id=span,parent_span_id=root,source_stream='role_events',source_seq=event.seq,kind='role',
            phase=event.phase,status='failed' if event.phase=='stopped' else 'recorded',attempt=state.attempt,
            revision=event.revision,role_id=opaque(event.role),recorded_at_utc=time,
            started_at_utc=time if event.phase=='started' else None,
            ended_at_utc=time if event.phase in ('completed','stopped') else None,
            duration_ms=number(metrics.get('latency_ms')),time_quality='recorded' if time else 'duration_only' if number(metrics.get('latency_ms')) is not None else 'unknown',
            input_hash=event.input_hash,output_hash=event.output_hash,
            input_tokens=integer(metrics.get('input_tokens')) if scope=='call' else None,
            output_tokens=integer(metrics.get('output_tokens')) if scope=='call' else None,
            usage_scope=scope,usage_missing_reason=None if scope=='call' and metrics.get('input_tokens') is not None and metrics.get('output_tokens') is not None else 'no_per_call_usage_recorded',
            error_code_id=opaque(event.code or metrics.get('error_code')),
            fallback_used=metrics.get('fallback_used') if type(metrics.get('fallback_used')) is bool else None,
            correlation_id=opaque(event.feedback_id))
        # The root stores full identity; this row describes the actual provider call.
        rows[-1]['model_identity_hash']=_model_hash(metrics,state.model_identity)
        if event.phase in ('completed','stopped'):active.pop(key,None)
    for i,tool in enumerate(tool_trace,1):
        duration=number(tool.get('duration_ms'))
        emit(span_id=rid+'-tool-'+str(i),parent_span_id=root,source_stream='tools',source_seq=integer(tool.get('index')) or i,
            kind='tool',phase='observation',status='failed' if tool.get('error_code') else 'recorded',attempt=state.attempt,
            revision=integer(tool.get('turn')),role_id=opaque(tool.get('role')),tool_id=opaque(tool.get('tool')),
            duration_ms=duration,time_quality='duration_only' if duration is not None else 'unknown',
            usage_scope='not_applicable',usage_missing_reason='tool_event_has_no_provider_usage',error_code_id=opaque(tool.get('error_code')))
    for pack_index,pack in enumerate(packs,1):
        raw=pack.model_dump(mode='json') if hasattr(pack,'model_dump') else pack
        for round_index,round_ in enumerate(raw.get('rounds',()),1):
            trace=round_.get('retrieval_trace',{});duration=number(round_.get('elapsed_ms'))
            emit(span_id=rid+f'-pack-{pack_index}-round-{round_index}',parent_span_id=root,
                source_stream='retrieval_rounds',source_seq=round_index,kind='retrieval',phase='observation',
                status=raw.get('evidence_status') if raw.get('evidence_status') not in (None,'legacy_unclassified') else 'recorded',
                attempt=state.attempt,tool_id=opaque(round_.get('tool')),duration_ms=duration,
                time_quality='duration_only' if duration is not None else 'unknown',
                evidence_ids=[opaque(x) for x in round_.get('retained_evidence_ids',())[:40]],
                config_identity=opaque(trace.get('config_identity')),index_identity=opaque(trace.get('index_identity')),
                input_hash=state_hash(round_.get('query','')),usage_scope='not_applicable',
                output_hash=state_hash({'evidence_status':raw.get('evidence_status'),'answer_policy':raw.get('answer_policy'),'reason_codes':raw.get('missing',[])}),
                usage_missing_reason='retrieval_not_a_generation_call',correlation_id=opaque(raw.get('pack_id')))
    if len(rows)>512:raise ValueError('trace_export_budget')
    return envelope(rows,task=state.task)


def from_task(task):
    rid=opaque(task['task_id']);tid=opaque('trace-'+task['task_id']);root=rid+'-root';rows=[]
    material=state_hash({k:task.get(k) for k in ('project_id','snapshot_id','generation','config_identity')})
    def emit(**kw):
        row=UnifiedTraceEvent(trace_id=tid,run_id=rid,seq=len(rows),material_hash=material,
            usage_scope='not_applicable',usage_missing_reason='index_task_has_no_generation_usage',**kw)
        rows.append(row.model_dump(mode='json'))
    created=timestamp(task.get('created_at'));updated=timestamp(task.get('updated_at'))
    emit(span_id=root,source_stream='task_snapshot',source_seq=0,kind='run',phase='snapshot',
        status=task['status'] if task['status'] in ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED') else 'other',
        attempt=integer(task.get('attempts')),started_at_utc=created,ended_at_utc=updated if task['status'] in ('SUCCEEDED','FAILED','CANCELLED') else None,
        time_quality='recorded' if created else 'unknown',error_code_id=opaque(task.get('error_code')),
        config_identity=opaque(task.get('config_identity')))
    for event in task.get('events',()):
        time=timestamp(event.get('recorded_at'))
        emit(span_id=rid+'-task-'+str(event['seq']),parent_span_id=root,source_stream='task_events',source_seq=event['seq'],
            kind='task',phase='event',status='recorded',attempt=integer(event.get('attempt')),recorded_at_utc=time,
            time_quality='recorded' if time else 'unknown',correlation_id=opaque(event.get('kind')))
    if len(rows)>512:raise ValueError('trace_export_budget')
    return envelope(rows,task='index',limitations=['snapshot_only_no_event_history'] if not task.get('events') else [])


def envelope(rows,*,task,limitations=()):
    # Aggregate usage is authoritative when present. Child call usage is audit detail,
    # and is deliberately excluded from the total to avoid counting it twice.
    root=rows[0];calls=[r for r in rows if r['usage_scope']=='call']
    return {'schema_version':'job-agent-trace-export-1','task':task,'events':rows,
        'usage':{'basis':'run_aggregate_only_children_excluded','input_tokens':root['input_tokens'],
            'output_tokens':root['output_tokens'],'cost':root['cost'],'provider_calls':root['provider_calls'],
            'recorded_call_spans':len(calls),'child_input_tokens_observed':sum(r['input_tokens'] for r in calls if r['input_tokens'] is not None),
            'child_output_tokens_observed':sum(r['output_tokens'] for r in calls if r['output_tokens'] is not None),
            'child_usage_complete':bool(calls) and all(r['input_tokens'] is not None and r['output_tokens'] is not None for r in calls)},
        'privacy':'IDs and hashes only; source text, answers, rubrics, prompts, credentials excluded',
        'ordering':'seq is export order; source_stream/source_seq preserve local order; cross-stream wall-clock order unknown',
        'replay_policy':'read_only_inspection; no tools, provider calls, approvals or worker actions',
        'limitations':list(limitations)}


def render(export,format):
    from fastapi.responses import JSONResponse,Response
    headers={'Cache-Control':'no-store'}
    if format=='json':return JSONResponse(export,headers=headers)
    headers['Content-Disposition']='attachment; filename="job-agent-trace.jsonl"'
    return Response(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in export['events']),
                    media_type='application/x-ndjson',headers=headers)


def install_trace_routes(app,workspace,owner,rewrite_service):
    from fastapi import Depends,Query
    @app.get('/api/v2/rewrites/{run_id}/trace')
    def rewrite_trace(run_id:str,format:Literal['json','jsonl']=Query('json'),user:str=Depends(owner)):
        state=rewrite_service.get(user,run_id,recover_expired=False)
        return render(from_execution(state.get('execution')),format)
    @app.get('/api/v2/interviews/{session_id}/trace')
    def interview_trace(session_id:str,format:Literal['json','jsonl']=Query('json'),user:str=Depends(owner)):
        store=app.state.interview_store
        with workspace._connection() as db:_,state,_=store._load(db,user,session_id)
        return render(from_execution(state.execution,tool_trace=state.tool_trace,packs=state.evidence_packs),format)
    @app.get('/api/v2/tasks/{task_id}/trace')
    def task_trace(task_id:str,format:Literal['json','jsonl']=Query('json'),user:str=Depends(owner)):
        return render(from_task(app.state.task_store.get(user,task_id)),format)
