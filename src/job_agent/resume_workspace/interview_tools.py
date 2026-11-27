"""Real read-only tools with server-bound tenant/snapshot and existing runtime policy."""
from hashlib import sha256
import json
from typing import Any
from types import SimpleNamespace
from uuid import uuid4
from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.agent_runtime.tool_executor import ToolExecutor
from job_agent.agent_runtime.policy import PolicyEngine,PolicyContext
from job_agent.agent_runtime.contracts import AgentAction,ToolContext
from job_agent.resume_workspace.code_rag import CodeQuery
from job_agent.resume_workspace.repository import WorkspaceConflict
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.evidence_pack import (
    BoundedEvidenceRetriever,EvidenceBudget,EvidenceBudgetExceeded,RetrievalScope,
)
from job_agent.knowledge.index_manifest import fingerprint


class SearchInput(StrictModel):
    query:str=Field(min_length=1,max_length=600)


class SymbolInput(StrictModel):
    name:str=Field(min_length=1,max_length=200)


class ReferencesInput(StrictModel):
    symbol_id:str=Field(min_length=1,max_length=100)
    tests_only:bool=False


class RangeInput(StrictModel):
    path:str=Field(min_length=1,max_length=240)
    start:int=Field(ge=1)
    end:int=Field(ge=1)


class ReadResult(StrictModel):
    result:dict[str,Any]


ROLE_TOOLS={
    'interviewer':('question_search','knowledge_search','code_search','get_symbol','find_references','read_code_range'),
    'evaluator':('knowledge_search','get_symbol','find_references','read_code_range'),
    'coach':('knowledge_search',),
}
MAX_TOOLS=18


def new_retrieval_state(kind='standalone'):
    return SimpleNamespace(session_id=kind+'-'+uuid4().hex,revision=0,tool_calls=0,
        tool_trace=[],tool_fingerprints=[],evidence_packs=[])


class InterviewTools:
    def __init__(self,workspace,knowledge,code,owner,project_id=None,snapshot_id=None):
        self.registry=ToolRegistry();self.owner=owner
        self.knowledge=knowledge;self.code=code;self.project_id=project_id;self.snapshot_id=snapshot_id
        def register(name,model,fn):
            def handle(request,context):
                context.ensure_active();result=self._project_result(fn(request));context.ensure_active()
                if len(json.dumps(result,ensure_ascii=False))>32000:raise WorkspaceConflict('tool_result_too_large')
                return ReadResult(result=result)
            self.registry.register(name=name,description='Read bounded untrusted reference data; never execute source or establish personal contribution.',
                input_model=model,output_model=ReadResult,handler=handle,timeout_s=12)
        register('question_search',SearchInput,lambda r:knowledge.search(r.query,kind='question',limit=3))
        register('knowledge_search',SearchInput,lambda r:knowledge.search(r.query,kind='doc',limit=2))
        if project_id and snapshot_id:
            # No owner/project/snapshot parameters are accepted from model arguments.
            register('code_search',SearchInput,lambda r:code.search(owner,project_id,CodeQuery(snapshot_id=snapshot_id,query=r.query,limit=3)))
            register('get_symbol',SymbolInput,lambda r:code.get_symbol(owner,project_id,snapshot_id,r.name))
            register('find_references',ReferencesInput,lambda r:{'items':code.find_references(owner,project_id,snapshot_id,r.symbol_id,tests_only=r.tests_only,limit=2)})
            register('read_code_range',RangeInput,lambda r:{'reference':code.read_code_range(owner,project_id,snapshot_id,r.path,r.start,r.end).model_dump(mode='json')})
        self.executor=ToolExecutor(self.registry);self.policy=PolicyEngine();self.root=str(workspace.path.parent)

    def validate_reference(self,ref):
        if ref.scope=='private_project':
            if ref.owner_id!=self.owner or ref.project_id!=self.project_id or ref.snapshot_id!=self.snapshot_id:
                raise WorkspaceConflict('evidence_reference_scope_mismatch')
            return self.code.validate_reference(self.owner,ref)
        if ref.scope!='public_knowledge':raise WorkspaceConflict('evidence_reference_scope_mismatch')
        return self.knowledge.repository.validate_reference(ref)

    def _project_result(self,result):
        """Keep complete verified quotes, avoiding duplicate entry.body in tools."""
        result=dict(result);remaining=8000;omitted=[]
        def item(hit):
            nonlocal remaining
            ref=self.validate_reference(EvidenceReference.model_validate(hit['reference']))
            if len(ref.quote)>remaining:
                size=0;end=None
                for offset,line in enumerate(ref.quote.splitlines(keepends=True)):
                    if offset>=20 or size+len(line)>8000:break
                    size+=len(line);end=ref.start_line+offset
                omitted.append({'evidence_id':ref.evidence_id,'path':ref.path,'start_line':ref.start_line,
                    'end_line':ref.end_line,'bounded_end_line':end})
                return None
            remaining-=len(ref.quote);safe=dict(hit);safe['reference']=ref.model_dump(mode='json')
            if safe.get('entry'):
                safe['entry']={k:v for k,v in safe['entry'].items() if k not in ('body','answer_points','aliases','followups')}
            return safe
        for field in ('hits','items'):
            if field in result:result[field]=[safe for hit in result[field] if (safe:=item(hit)) is not None]
        if result.get('reference'):
            safe=item({'reference':result['reference']})
            if safe is None:result.pop('reference',None)
            else:result['reference']=safe['reference']
        result['tool_projection']={'quote_chars':8000-remaining,'quote_budget':8000,'omitted_locations':omitted}
        if omitted:result['tool_projection_warnings']=['tool_quote_budget_omitted_whole_span']
        return result

    def _scope(self,kind):
        if kind=='private_project':
            if not self.project_id or not self.snapshot_id:raise WorkspaceConflict('evidence_private_scope_required')
            status=self.code.status(self.owner,self.project_id,self.snapshot_id)
            identity=fingerprint([self.snapshot_id,status.get('file_manifest_hash'),status.get('index_version')])
            limitations=[]
            if status.get('oversized_lines_omitted'):limitations.append('index_oversized_lines_omitted')
            if status.get('unresolved_references'):limitations.append('index_static_references_unresolved')
            if status.get('warnings'):limitations.append('index_parser_warnings_present')
            return RetrievalScope(kind=kind,owner_id=self.owner,project_id=self.project_id,snapshot_id=self.snapshot_id,
                corpus_identity='code-'+identity,known_limitations=limitations),int(status.get('files',1))
        expected='question' if kind=='public_questions' else 'doc'
        entries=[(e,v) for e,v in self.knowledge.repository.entries() if e.kind==expected]
        versions={e.entry_id:v for e,v in entries}
        return RetrievalScope(kind=kind,corpus_identity='public-'+fingerprint(versions),public_versions=versions),len(entries)

    def _model_cost(self,name):
        if name not in ('code_search','question_search','knowledge_search'):return {'embedding':0,'rerank':0,'tokens':0}
        service=self.code if name=='code_search' else self.knowledge
        method='code_aware' if name=='code_search' else service.default_method
        embedding=int(service.embedding_backend is not None and method in ('hybrid','code_aware','dense'))
        rerank=int(service.reranker is not None and method in ('hybrid','code_aware'))
        tokens=embedding*getattr(getattr(service.embedding_backend,'identity',None),'max_input_tokens',1024)
        tokens+=rerank*service.settings.rerank_candidates*service.reranker.identity.max_pair_tokens if rerank else 0
        return {'embedding':embedding,'rerank':rerank,'tokens':tokens}

    def retrieve_pack(self,state,role,query,*,scope_kind,claims=(),budget=None,read_actions=None,save=lambda:None):
        if not hasattr(state,'evidence_packs'):state.evidence_packs=[]
        if len(state.evidence_packs)>=10:raise WorkspaceConflict('evidence_pack_history_limit')
        scope,count=self._scope(scope_kind)
        def validate(ref):
            actual=self.validate_reference(ref)
            if scope.kind=='private_project':
                if actual.scope!='private_project':raise WorkspaceConflict('evidence_reference_scope_mismatch')
            else:
                if actual.scope!='public_knowledge' or scope.public_versions.get(actual.source_id)!=actual.snapshot_id:
                    raise WorkspaceConflict('evidence_public_corpus_changed')
                expected='question' if scope.kind=='public_questions' else 'documentation'
                if actual.evidence_kind!=expected:raise WorkspaceConflict('evidence_reference_kind_mismatch')
            return actual
        settings=self.code.settings if scope_kind=='private_project' else self.knowledge.settings
        collector=BoundedEvidenceRetriever(scope=scope,invoke=lambda name,args,deadline:self.run(state,role,name,args,save,deadline=deadline),
            validate=validate,tool_count=lambda:state.tool_calls,model_cost=self._model_cost,
            config_identity=settings.key,material_count=count)
        pack=collector.retrieve(query,claims=claims,budget=budget,read_actions=read_actions)
        state.evidence_packs.append(pack);save();return pack

    def run(self,state,role,name,arguments,save=lambda:None,*,deadline=None):
        if role not in ROLE_TOOLS or name not in ROLE_TOOLS[role] or name not in self.registry.names():
            raise WorkspaceConflict('interview_tool_permission_denied')
        fingerprint=sha256(json.dumps([role,name,arguments],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if fingerprint in state.tool_fingerprints:return {'skipped':'duplicate_read','hits':[],'items':[]}
        if state.tool_calls>=MAX_TOOLS:raise WorkspaceConflict('interview_tool_budget_exceeded')
        state.tool_calls+=1;state.tool_fingerprints.append(fingerprint);save()
        action=AgentAction(action_id=f'{state.session_id}-tool-{state.tool_calls}',tool_name=name,tool_arguments=arguments,
            expected_observation='Scoped source references or an explicit empty/error result.',progress_claim='Read reference data for the next bounded decision.')
        allowed=ROLE_TOOLS[role]
        authorization=self.policy.authorize(action,self.registry.get(name).spec,PolicyContext(
            skill_allowed_tools=allowed,agent_allowed_tools=allowed,runtime_allowed_tools=self.registry.names()))
        observation=self.executor.execute(action,authorization,ToolContext(session_id=state.session_id,run_id=state.session_id,
            agent_id=role,workspace_root=self.root,deadline_monotonic=deadline))
        # Public trace never includes input text, rubric, model notes or raw tool errors.
        state.tool_trace.append({'index':state.tool_calls,'role':role,'tool':name,'status':observation.status.value,
            'duration_ms':observation.duration_ms,'turn':state.revision,'error_code':observation.error_code})
        save()
        if observation.error_code=='tool_timeout':raise EvidenceBudgetExceeded('tool_deadline_late_result_rejected')
        if observation.error_code:raise WorkspaceConflict('interview_reference_tool_failed')
        return observation.data['result']
