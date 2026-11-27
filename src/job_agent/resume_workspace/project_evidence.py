"""Explicit project-practice scope; source geometry is not semantic truth."""
import re
from typing import Literal
from pydantic import Field
from job_agent.schemas import StrictModel

TopicStatus=Literal['legacy_unclassified','not_located','topic_only','partial','located_unjudged','conflict']


class ProjectEvidenceBoundary(StrictModel):
    version:Literal['project-evidence-1']='project-evidence-1'
    pack_id:str
    trace_id:str
    snapshot_id:str
    reference_ids:list[str]=Field(min_length=1,max_length=6)
    requested_topic_status:TopicStatus
    question_source_status:Literal['source_sufficient','partial']
    answer_policy:Literal['limited_source_only','needs_input']
    reason_codes:list[str]=Field(default_factory=list,max_length=24)
    scope_note:str=Field(min_length=1,max_length=300)
    assessment_scope:Literal['quoted_source_only']='quoted_source_only'
    sufficiency_basis:Literal['source_geometry_only']='source_geometry_only'
    semantic_support:Literal['not_verified']='not_verified'


_NEGATIVE=re.compile(r'不能|无法|未(?:做|测|运行|提供|核|确认|部署|完成)|没有|不证明|不代表|不等于|不清楚|不知道|不确定|尚无|仍需|待核|假设|如果|假如|例如|假定')
_REPORTED=re.compile(r'(?:报告|文档|材料|引用|文本|源码|设计)(?:中|里)?(?:写|称|说|记录|提到|显示|声称|包含)')
_METRICS=r'录用率|录取率|转化率|吞吐|QPS|准确率|成功率|覆盖率|性能提升|每秒|测试通过率|用户数|真实用户|用户规模|用户量|DAU|MAU|P99|P95|并发租户|生产延迟|线上延迟|端到端延迟|零丢失'
_OPERATIONS=r'已(?:经)?(?:在生产环境)?(?:成功)?(?:部署|上线)|已将.{0,8}(?:部署|上线)|完成(?:了)?(?:生产)?部署|成功(?:地)?(?:部署|上线)|已经.{0,8}(?:部署|上线|全部迁移|私有仓库扫描)'


def clauses(text):return [p for p in re.split(r'[。！？；;，,\n]|但是|不过|然而|但|而且',text) if p.strip()]


def requested_boundary_flags(query,claims):
    flags=[]
    for part in clauses(' '.join([query,*claims])):
        if _NEGATIVE.search(part) or _REPORTED.search(part):continue
        if re.search(r'本人|我(?:独立|负责|主导|实现|参与)|用户(?:独立|负责|主导)|候选人(?:独立|负责|主导)|个人贡献',part):
            flags.append('personal_contribution_unverified')
        if re.search(_METRICS,part,re.I) and (claims or re.search(r'多少|具体|是多少|达到|提升|显著|生产|线上|全部|\d',part)):
            flags.append('runtime_measurements_unverified')
        if re.search(_OPERATIONS,part):
            flags.append('operational_outcome_unverified')
    return list(dict.fromkeys(flags))


def version_scope_flags(query,items):
    paths=[i.reference.path.casefold() for i in items]
    historical=any('history' in p or 'historical' in p or '历史' in p for p in paths)
    current=(any(p.endswith('/current_spec.md') or p=='current_spec.md' for p in paths)
             or any(i.reference.evidence_kind in ('code','test_code') for i in items))
    if historical and re.search(r'当前(?!事务|线程|请求|任务|轮次|输入|参数|函数|片段)|现在|最新|已经|已完成',query):
        return ['version_applicability_unresolved']+(['mixed_current_historical_sources'] if current else [])
    return []


def make_question_boundary(pack,references,symbol=None,prior=None):
    whole=bool(len(references)==1 and symbol and references[0].start_line<=symbol['start_line'] and references[0].end_line>=symbol['end_line'])
    status=pack.evidence_status;reasons=list(pack.missing)
    severity={'legacy_unclassified':0,'located_unjudged':1,'partial':2,'topic_only':3,'not_located':4,'conflict':5}
    if prior and severity[prior.requested_topic_status]>severity[status]:status=prior.requested_topic_status
    if prior:reasons=[*prior.reason_codes,*reasons]
    policy='needs_input' if status in ('not_located','topic_only','conflict') or pack.answer_policy=='needs_input' else 'limited_source_only'
    if status=='conflict':note='当前与历史资料的适用性尚未厘清；本题只讨论固定引用，不能据此确认当前部署或业务状态。'
    elif policy=='needs_input':note='未找到足以确认原主题事实的材料；本题改为只解释所引源码，运行成效与个人贡献仍需补充材料。'
    elif not whole:note='本题只讨论已引用的源码片段；未展示的部分请明确无法判断，不据此推断整个实现。'
    else:note='本题仅依据所选快照中的完整引用解释静态实现；不证明运行成效或个人贡献。'
    if len({r.path for r in references})>1:
        reasons.append('cross_file_candidates_not_full_chain');note+='不同文件的候选引用不等于完整调用链已获确认。'
    if any('semantic_embedding_not_configured' in warning for warning in pack.warnings):
        reasons.append('lexical_retrieval_only');note='当前采用词面检索。'+note
    return ProjectEvidenceBoundary(pack_id=pack.pack_id,trace_id=pack.trace_id,snapshot_id=references[0].snapshot_id,
        reference_ids=[r.evidence_id for r in references],requested_topic_status=status,
        question_source_status='source_sufficient' if whole else 'partial',answer_policy=policy,
        reason_codes=list(dict.fromkeys(reasons))[:24],scope_note=note)


def unsupported_source_claim(answer,references=()):
    """Narrow positive operational assertions; not a general semantic judge."""
    for part in clauses(answer):
        if _NEGATIVE.search(part):continue
        if _REPORTED.search(part):
            numbers=re.findall(r'\d+(?:\.\d+)?%?',part)
            terms=re.findall(_METRICS+r'|生产部署|上线|人工核对',part,re.I)
            if not terms:continue
            located=any(all(n in r.quote for n in numbers) and any(t.casefold() in r.quote.casefold() for t in terms)
                        for r in references)
            if located:continue
            return part[:300],'reported_measurement_not_located_in_reference'
        if re.search(_METRICS,part,re.I) and re.search(r'\d|百分之|全部|零丢失|恰好一次',re.sub(_METRICS,'',part,flags=re.I)):
            return part[:300],'source_does_not_verify_measurement'
        if re.search(_OPERATIONS,part):
            return part[:300],'source_does_not_verify_operation'
        if re.search(r'历史|旧(?:版|计划|文档|Spec)',part,re.I) and re.search(r'证明|所以|说明',part) and re.search(r'当前|现在|已经',part):
            return part[:300],'historical_plan_does_not_establish_current_state'
        if re.search(r'(?:本人|我)(?:独立|主导|负责).{0,18}(?:实现|开发|编写|部署|上线)',part):
            return part[:300],'source_does_not_verify_personal_contribution'
    return None


def guard_project_evaluation(state,evaluation):
    boundary=state.current.evidence_boundary
    if boundary is None:return evaluation
    evaluation.method_version='rag-project-source-1'
    unsupported=unsupported_source_claim(state.pending.answer,state.current.references)
    if unsupported:
        from job_agent.resume_workspace.interview_contracts import PointAssessment
        quote,reason=unsupported
        # This hook runs only after mandatory online completeness validation.
        # It cannot supply missing model assessments or manufacture correct ones.
        key='p2'
        if key not in state.plan[state.topic_index].points:return evaluation
        evaluation.point_assessments=[a for a in evaluation.point_assessments if a.point_id!=key]+[
            PointAssessment(point_id=key,status='uncertain',answer_quote=quote,
                reason='当前来源仅支持限定源码练习，不能独立确认该运行/当前状态断言：'+reason,
                assessed_by='deterministic_counterexample')]
        evaluation.covered_ids=[k for k in evaluation.covered_ids if k!=key]
        evaluation.missing_ids=list(dict.fromkeys([*evaluation.missing_ids,key]))
        evaluation.claim_needs_evidence=True;evaluation.recommended_action='follow_up'
        evaluation.assessment_mode='deterministic_counterexample'
        evaluation.note='引用定位不等于运行成果或当前状态已证实；需要补充对应材料。'
    return evaluation
