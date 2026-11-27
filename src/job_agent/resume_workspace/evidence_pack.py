"""Bounded source collection, not an automatic semantic truth judge."""
from __future__ import annotations
from time import monotonic
from typing import Any,Callable,Literal
from uuid import uuid4
import re
from pydantic import Field,model_validator
from job_agent.schemas import StrictModel
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.repository import WorkspaceConflict
from job_agent.resume_workspace.project_evidence import TopicStatus,requested_boundary_flags,version_scope_flags


class EvidenceBudget(StrictModel):
    search_rounds:int=Field(default=2,ge=1,le=2)
    tools:int=Field(default=5,ge=1,le=5)
    quote_chars:int=Field(default=8000,ge=128,le=8000)
    model_input_tokens_upper_bound:int=Field(default=32768,ge=0,le=32768)
    elapsed_ms:int=Field(default=20000,ge=1,le=20000)


class RetrievalScope(StrictModel):
    kind:Literal['private_project','public_docs','public_questions']
    owner_id:str|None=None
    project_id:str|None=None
    snapshot_id:str|None=None
    corpus_identity:str
    public_versions:dict[str,str]=Field(default_factory=dict)
    known_limitations:list[str]=Field(default_factory=list)

    @model_validator(mode='after')
    def trusted_shape(self):
        if self.kind=='private_project':
            if not all((self.owner_id,self.project_id,self.snapshot_id)):raise ValueError('private_scope_required')
            if self.public_versions:raise ValueError('mixed_scope_not_allowed')
        elif any((self.owner_id,self.project_id,self.snapshot_id)):raise ValueError('unexpected_private_scope')
        return self


class RetrievalPlan(StrictModel):
    plan_id:str
    query:str
    kind:Literal['exact_symbol','semantic','cross_file','runtime_evidence','read_followup']
    scope:RetrievalScope
    allowed_tools:list[str]
    budget:EvidenceBudget
    required_paths:int=1
    needs_imports:bool=False
    needs_full_definition:bool=False


class PackItem(StrictModel):
    reference:EvidenceReference
    symbol:dict[str,Any]|None=None
    entry:dict[str,Any]|None=None
    score:float|None=None
    location_valid:Literal[True]=True
    relevance:Literal['candidate_needs_semantic_review']='candidate_needs_semantic_review'


class ClaimAssessment(StrictModel):
    claim_id:str
    statement:str
    target_kind:Literal['requested_answer','supplied_claim']
    status:Literal['needs_judgment','insufficient_evidence','supported','partial','conflict']
    evidence_ids:list[str]
    reason:str
    assessed_by:Literal['deterministic_boundary','pending_semantic_review']


class EvidenceRound(StrictModel):
    index:int
    query:str
    tool:str
    returned_evidence_ids:list[str]
    retained_evidence_ids:list[str]
    added_items:int
    distinct_paths_after:int
    elapsed_ms:int
    warnings:list[str]=Field(default_factory=list)
    retrieval_trace:dict[str,Any]=Field(default_factory=dict)


class EvidenceUsage(StrictModel):
    tool_calls:int=0
    search_rounds:int=0
    read_calls:int=0
    reserved_embedding_query_calls:int=0
    reserved_rerank_calls:int=0
    reserved_model_input_tokens_upper_bound:int=0
    quote_chars:int=0
    elapsed_ms:int=0
    budget_exhausted:bool=False
    stop_reason:str='completed_bounded_collection'


class EvidencePack(StrictModel):
    pack_id:str
    plan:RetrievalPlan
    config_identity:str
    trace_id:str
    items:list[PackItem]
    rounds:list[EvidenceRound]
    reads:list[dict[str,Any]]
    claim_assessments:list[ClaimAssessment]
    missing:list[str]
    warnings:list[str]
    answer_policy:Literal['limited_source_only','needs_input']
    corpus_answerability:Literal['unknown','no_material_in_scope']='unknown'
    evidence_status:TopicStatus='legacy_unclassified'
    usage:EvidenceUsage
    visible_roles:list[str]=Field(default_factory=lambda:['interviewer','evaluator','coach'])
    source_data_is_untrusted:Literal[True]=True
    independent_truth:Literal['not_verified']='not_verified'

    def role_summary(self):
        return {'pack_id':self.pack_id,'plan_id':self.plan.plan_id,'scope':self.plan.scope.kind,
            'answer_policy':self.answer_policy,'missing':self.missing,
            'evidence_status':self.evidence_status,
            'claim_statuses':[{'claim_id':c.claim_id,'status':c.status} for c in self.claim_assessments],
            'evidence_ids':[i.reference.evidence_id for i in self.items],
            'source_data_is_untrusted':True,'independent_truth':'not_verified'}


class EvidenceBudgetExceeded(RuntimeError):pass


def risk_flags(query,claims):
    return requested_boundary_flags(query,claims)


def make_plan(query,scope,budget,allowed_tools,*,claims=(),read_followup=False):
    query=query.strip()
    if not query or len(query)>600:raise WorkspaceConflict('evidence_query_invalid')
    cross=scope.kind=='private_project' and any(t in query.casefold() for t in ('跨文件','调用','callers','references','测试','tests'))
    exact=bool(re.search(r'`[A-Za-z_][\w.]*`|\b[A-Za-z_]\w*[_\.][A-Za-z_]\w*',query))
    kind='read_followup' if read_followup else 'runtime_evidence' if 'runtime_measurements_unverified' in risk_flags(query,claims) else 'cross_file' if cross else 'exact_symbol' if exact else 'semantic'
    content={'query':query,'scope':scope.model_dump(),'budget':budget.model_dump(),'kind':kind,'allowed_tools':allowed_tools}
    return RetrievalPlan(plan_id='plan-'+fingerprint(content),query=query,scope=scope,kind=kind,allowed_tools=list(allowed_tools),
        budget=budget,required_paths=2 if cross else 1,needs_imports=scope.kind=='private_project' and any(t in query.casefold() for t in ('import','导入')),
        needs_full_definition=scope.kind=='private_project' and any(t in query.casefold() for t in ('完整','whole definition','full definition')))


class BoundedEvidenceRetriever:
    def __init__(self,*,scope:RetrievalScope,invoke:Callable,validate:Callable,tool_count:Callable,
                 model_cost:Callable,config_identity:str,material_count:int,session_tool_limit=18,clock=monotonic):
        self.scope=scope;self.invoke=invoke;self.validate=validate;self.tool_count=tool_count
        self.model_cost=model_cost;self.config_identity=config_identity;self.material_count=material_count
        self.session_tool_limit=session_tool_limit;self.clock=clock

    def retrieve(self,query,*,claims=(),budget=None,read_actions=None):
        budget=budget or EvidenceBudget()
        first_tool='code_search' if self.scope.kind=='private_project' else 'question_search' if self.scope.kind=='public_questions' else 'knowledge_search'
        allowed=[first_tool]+(['get_symbol','find_references','read_code_range'] if self.scope.kind=='private_project' else [])
        plan=make_plan(query,self.scope,budget,allowed,claims=claims,read_followup=read_actions is not None)
        started=self.clock();deadline=started+budget.elapsed_ms/1000;initial=self.tool_count()
        usage=EvidenceUsage();items=[];rounds=[];reads=[];missing=[];warnings=[];seen=set()

        def paths():return {i.reference.path for i in items}
        def needs_more():
            if not items or len(paths())<plan.required_paths:return True
            if plan.needs_imports and not any(i.reference.start_line==1 and 'import ' in i.reference.quote for i in items):return True
            if plan.needs_full_definition and not any(i.symbol and i.reference.start_line<=i.symbol['start_line']
                and i.reference.end_line>=i.symbol['end_line'] for i in items):return True
            return plan.kind=='runtime_evidence'

        def call(name,arguments):
            if name not in allowed:raise WorkspaceConflict('evidence_tool_out_of_scope')
            if self.clock()>=deadline:raise EvidenceBudgetExceeded('plan_deadline')
            if self.tool_count()>=self.session_tool_limit:raise EvidenceBudgetExceeded('session_tool_budget')
            if self.tool_count()-initial>=budget.tools:raise EvidenceBudgetExceeded('pack_tool_budget')
            cost=self.model_cost(name)
            if usage.reserved_model_input_tokens_upper_bound+cost['tokens']>budget.model_input_tokens_upper_bound:
                raise EvidenceBudgetExceeded('model_input_budget')
            usage.reserved_model_input_tokens_upper_bound+=cost['tokens']
            usage.reserved_embedding_query_calls+=cost['embedding'];usage.reserved_rerank_calls+=cost['rerank']
            result=self.invoke(name,arguments,deadline)
            if self.clock()>=deadline:raise EvidenceBudgetExceeded('plan_deadline_late_result_rejected')
            if result.get('skipped'):warnings.append('duplicate_read_skipped')
            return result

        def retain(result):
            raw=list(result.get('hits',[]))+list(result.get('items',[]))
            if result.get('reference'):raw.append({'reference':result['reference'],'symbol':result.get('symbol')})
            returned=[];retained=[]
            for hit in raw:
                ref=EvidenceReference.model_validate(hit['reference'])
                ref=self.validate(ref) # Invalid citations abort; never hide them with a retry.
                returned.append(ref.evidence_id)
                if ref.evidence_id in seen:continue
                if usage.quote_chars+len(ref.quote)>budget.quote_chars:
                    warnings.append('pack_quote_budget_omitted_whole_span');continue
                seen.add(ref.evidence_id);usage.quote_chars+=len(ref.quote);retained.append(ref.evidence_id)
                items.append(PackItem(reference=ref,symbol=hit.get('symbol'),entry=hit.get('entry'),score=hit.get('score')))
            for warning in [*result.get('warnings',[]),*result.get('tool_projection_warnings',[])]:warnings.append(warning)
            return returned,retained

        def search(text):
            if len(rounds)>=budget.search_rounds:raise EvidenceBudgetExceeded('search_round_budget')
            before=len(items);when=self.clock();calls_before=self.tool_count()
            try:found=call(first_tool,{'query':text})
            except EvidenceBudgetExceeded as exc:
                if self.tool_count()>calls_before:
                    rounds.append(EvidenceRound(index=len(rounds)+1,query=text,tool=first_tool,returned_evidence_ids=[],
                        retained_evidence_ids=[],added_items=0,distinct_paths_after=len(paths()),
                        elapsed_ms=int((self.clock()-when)*1000),warnings=[str(exc)]))
                raise
            returned,retained=retain(found)
            self._last_omitted=found.get('tool_projection',{}).get('omitted_locations',[])
            rounds.append(EvidenceRound(index=len(rounds)+1,query=text,tool=first_tool,returned_evidence_ids=returned,
                retained_evidence_ids=retained,added_items=len(items)-before,distinct_paths_after=len(paths()),
                elapsed_ms=int((self.clock()-when)*1000),warnings=found.get('warnings',[]),retrieval_trace=found.get('retrieval_trace',{})))

        def read(name,arguments):
            if name not in ('get_symbol','find_references','read_code_range'):raise WorkspaceConflict('evidence_read_tool_invalid')
            when=self.clock();calls_before=self.tool_count()
            try:found=call(name,arguments)
            except EvidenceBudgetExceeded as exc:
                if self.tool_count()>calls_before:reads.append({'tool':name,'returned_evidence_ids':[],
                    'retained_evidence_ids':[],'elapsed_ms':int((self.clock()-when)*1000),'error':str(exc)})
                raise
            returned,retained=retain(found)
            reads.append({'tool':name,'returned_evidence_ids':returned,'retained_evidence_ids':retained,
                          'elapsed_ms':int((self.clock()-when)*1000)})

        try:
            if read_actions is not None:
                for name,args in read_actions:read(name,args)
            else:
                search(plan.query)
                if not items and self.scope.kind=='private_project':
                    # Large code quotes were omitted by the tool projection. A new
                    # counted read may fetch complete bounded lines, never a fake quote.
                    omitted=next((loc for loc in getattr(self,'_last_omitted',[]) if loc.get('bounded_end_line')),None)
                    if omitted:read('read_code_range',{'path':omitted['path'],'start':omitted['start_line'],'end':omitted['bounded_end_line']})
                seed=next((i for i in items if i.symbol),None)
                if needs_more() and seed and plan.kind=='cross_file':
                    read('find_references',{'symbol_id':seed.symbol['symbol_id'],'tests_only':'测试' in query or 'tests' in query.casefold()})
                if plan.needs_imports and needs_more() and seed:
                    read('read_code_range',{'path':seed.reference.path,'start':1,'end':min(seed.symbol['end_line'],80)})
                if plan.needs_full_definition and needs_more() and seed:read('get_symbol',{'name':seed.symbol['symbol_id']})
                if needs_more() and self.material_count>0 and len(rounds)<budget.search_rounds:
                    suffix=' runtime benchmark measurements report' if plan.kind=='runtime_evidence' else ' 调用 定义 测试 caller references' if plan.kind=='cross_file' else ' 机制 定义 implementation reference'
                    modified=plan.query[:600-len(suffix)]+suffix
                    search(modified)
        except EvidenceBudgetExceeded as exc:
            usage.budget_exhausted=True;usage.stop_reason=str(exc);missing.append('budget_exhausted')
        usage.tool_calls=self.tool_count()-initial;usage.search_rounds=len(rounds);usage.read_calls=len(reads)
        usage.elapsed_ms=int((self.clock()-started)*1000)
        if not items:missing.append('no_material_in_scope' if self.material_count==0 else 'retrieval_empty_answerability_unknown')
        if plan.required_paths>1 and len(paths())<plan.required_paths:missing.append('cross_file_coverage_incomplete')
        if plan.needs_imports and not any(i.reference.start_line==1 and 'import ' in i.reference.quote for i in items):missing.append('import_context_not_located')
        if plan.needs_full_definition and not any(i.symbol and i.reference.start_line<=i.symbol['start_line']
            and i.reference.end_line>=i.symbol['end_line'] for i in items):missing.append('full_definition_not_located')
        risks=risk_flags(plan.query,claims)+version_scope_flags(plan.query,items);missing.extend(risks)
        if self.material_count==0:missing.append('no_material_in_scope')
        ids=[i.reference.evidence_id for i in items];assessments=[]
        required_missing=any(x in missing for x in ('cross_file_coverage_incomplete','import_context_not_located','full_definition_not_located'))
        warnings.extend(self.scope.known_limitations)
        if (not items or required_missing) and any('quote_budget_omitted_whole_span' in w for w in warnings) and not usage.budget_exhausted:
            usage.budget_exhausted=True;usage.stop_reason='quote_budget'
        for index,statement in enumerate(claims or [plan.query]):
            statement_risks=risk_flags(statement,[statement] if claims else ())+version_scope_flags(statement,items)
            insufficient=not items or required_missing or bool(statement_risks)
            conflict='mixed_current_historical_sources' in statement_risks
            assessments.append(ClaimAssessment(claim_id=f'claim-{index}',statement=statement,
                target_kind='supplied_claim' if claims else 'requested_answer',status='conflict' if conflict else 'insufficient_evidence' if insufficient else 'needs_judgment',
                evidence_ids=ids,reason='当前与历史资料的适用性未决；这不等于已证明内容逻辑矛盾。' if conflict else '所需来源/范围不足，不能据此核实个人贡献、运行成果或完整断言。' if insufficient else '原文定位有效；相关性和断言支持仍需语义判断。',
                assessed_by='deterministic_boundary' if insufficient else 'pending_semantic_review'))
        status=('not_located' if not items else 'conflict' if 'mixed_current_historical_sources' in risks
                else 'topic_only' if risks else 'partial' if required_missing or usage.budget_exhausted else 'located_unjudged')
        return EvidencePack(pack_id='pack-'+uuid4().hex,trace_id='retrieval-'+uuid4().hex,plan=plan,
            config_identity=self.config_identity,items=items,rounds=rounds,reads=reads,claim_assessments=assessments,
            missing=list(dict.fromkeys(missing)),warnings=list(dict.fromkeys(warnings)),
            answer_policy='needs_input' if not items or risks or required_missing else 'limited_source_only',usage=usage,
            evidence_status=status,
            corpus_answerability='no_material_in_scope' if self.material_count==0 else 'unknown')
