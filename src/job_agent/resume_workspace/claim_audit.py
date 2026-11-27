"""Relative C1 assertion audit. Neither a truth detector nor a semantic oracle."""
from __future__ import annotations
import re
from typing import Literal
from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.execution_state import state_hash


class ReviewedClaim(StrictModel):
    text:str=Field(min_length=1,max_length=5000)
    source_quote:str=Field(default='',max_length=5000)
    status:Literal['supported','unsupported','contradicted','uncertain']
    reason:str=Field(min_length=1,max_length=300)


class AuditedClaim(StrictModel):
    claim_id:str
    text:str
    start:int
    end:int
    kinds:list[str]
    change:Literal['unchanged_or_controlled_paraphrase','new_or_semantic_change']
    status:Literal['supported','unsupported','contradicted','uncertain']
    assessed_by:Literal['deterministic_alignment','deterministic_gate','model_semantic_unverified','not_assessed']
    source_id:str|None=None
    source_quote:str|None=None
    reason:str


class ClaimAudit(StrictModel):
    source_hash:str
    draft_hash:str
    claims:list[AuditedClaim]
    hard_issues:list[str]
    unresolved_ids:list[str]
    acceptable:bool
    semantic_truth:Literal['not_independently_verified']='not_independently_verified'


OUTCOMES={
    'success_rate':r'求职成功率|成功率|录用率|面试通过率|获得录用|获得offer',
    'throughput':r'吞吐|\bQPS\b|每秒处理',
    'latency':r'延迟|时延|响应时间|响应速度|耗时|等待时间',
    'accuracy':r'准确率|正确率|精确率|召回率',
    'coverage':r'测试覆盖率|覆盖率',
    'cost':r'成本|费用',
    'users':r'用户量|活跃用户|留存率',
    'duplicate_reads':r'重复读取|重复读|重复查询',
    'duplicate_writes':r'重复写入|重复写|重复提交|重复执行',
    'tests_passed':r'测试.{0,6}(?:已|均|全部|成功)?通过|通过了(?:全部|所有|全量)?测试',
    'award':r'获奖|一等奖|二等奖|三等奖|冠军|国家级|全国',
    'production_result':r'线上稳定|稳定运行|零故障|零错误|线上可用',
}
EFFECT=r'提高|提升|降低|减少|缩短|增加|改善|优化|避免|消除|加快|显著|大幅|达到|促成|带来'
NEG=r'尚未|没有|从未|未使用|未部署|未上线|未运行|尚无|不负责|\bnot\b|\bnever\b|\bwithout\b'


def parts(text):
    return [(m.start()+len(m.group())-len(m.group().lstrip()),m.start()+len(m.group().rstrip()),m.group().strip())
        for m in re.finditer(r'[^，,。；;\n]+[，,。；;]?',text) if m.group().strip()]


def controlled(text):
    text=re.sub(r'^我参与了','参与',text);text=re.sub(r'^我使用','使用',text)
    text=text.replace('基于','使用').replace('实现','开发')
    return re.sub(r'[\s，,。；;]','',text)


def outcome_types(text):
    return {k for k,p in OUTCOMES.items() if re.search(p,text,re.I)}


def entities(text):
    return {w.rstrip('.-').casefold() for w in re.findall(r'[A-Za-z][A-Za-z0-9_+#.\-]*',text)}


def additional_hard_issues(original,proposed):
    issues=[]
    new_outcomes=outcome_types(proposed)-outcome_types(original)
    if re.search(EFFECT,proposed) or new_outcomes & {'tests_passed','award','production_result'}:
        for kind in sorted(new_outcomes):
            issues.append('新增无原文依据成果：'+kind)
    for degree in ('显著','大幅','彻底','完全消除','百分之百'):
        if degree in proposed and degree not in original:issues.append('新增成果强度：'+degree)
    if re.search(r'因此|从而|使得|促成|带来',proposed) and not re.search(r'因此|从而|使得|促成|带来',original):
        issues.append('新增因果归因，需要原始依据')
    negative=set();positive=set()
    for _,_,text in parts(original):
        target=negative if re.search(NEG,text,re.I) else positive
        target.update(entities(text))
    for _,_,text in parts(proposed):
        if re.search(NEG,text,re.I):continue
        positive_entities=entities(text)
        if positive_entities & (negative-positive):issues.append('与原文否定实体冲突：'+','.join(sorted(positive_entities & (negative-positive))))
    return list(dict.fromkeys(issues))


def deterministic_hard_issues(original,proposed):
    issues=[]
    if set(re.findall(r'\d+(?:\.\d+)?%?',proposed))-set(re.findall(r'\d+(?:\.\d+)?%?',original)):
        issues.append('新增或改变数字/年限')
    if entities(proposed)-entities(original):
        issues.append('新增英文技术/实体')
    for word in ('未独立','尚未','没有','尚无','未使用','未部署','不负责','非生产','参与','协助','原型','课程','本地','实验','模拟'):
        if word in original and word not in proposed:issues.append('删除否定或范围限定：'+word)
    for word in ('not','never','without','prototype','assisted','coursework','local'):
        if re.search(r'\b'+word+r'\b',original,re.I) and not re.search(r'\b'+word+r'\b',proposed,re.I):
            issues.append('删除英文否定或范围限定：'+word)
    for word in ('独立负责','主导','精通','专家','生产环境','生产级','大规模','端到端负责','领导'):
        if word in proposed and word not in original:issues.append('扩大职责/能力：'+word)
    return [*issues,*additional_hard_issues(original,proposed)]


def audit_claims(original,proposed,*,reviews=(),context=None,source_id='source_fact',hard_issues=()):
    hard=list(dict.fromkeys([*hard_issues,*deterministic_hard_issues(original,proposed)]))
    source_parts=[(text,source_id) for _,_,text in parts(original)]
    context=context or {}
    source_parts += [(str(text),'entry_context.'+key) for key,text in context.items() if key in ('name','organization','role','period')]
    reviewed={r.text:r for r in [ReviewedClaim.model_validate(r) for r in reviews]}
    claims=[]
    for start,end,text in parts(proposed):
        kinds=[]
        for kind,pattern in [('responsibility',r'负责|参与|主导|协助|领导'),('technology',r'[A-Za-z][A-Za-z0-9_+#.\-]*'),
            ('quantity',r'\d'),('time',r'年|月|期间'),('outcome',EFFECT),('causality',r'因此|从而|使得|促成|带来'),('scope',r'本地|原型|生产|实验|课程|尚未|没有')]:
            if re.search(pattern,text):kinds.append(kind)
        aligned=next(((q,key) for q,key in source_parts if controlled(q)==controlled(text)),None)
        item=AuditedClaim(claim_id='claim-'+state_hash([start,end,text])[:24],text=text,start=start,end=end,kinds=kinds or ['statement'],
            change='unchanged_or_controlled_paraphrase' if aligned else 'new_or_semantic_change',
            status='supported' if aligned else 'uncertain',assessed_by='deterministic_alignment' if aligned else 'not_assessed',
            source_id=aligned[1] if aligned else None,source_quote=aligned[0] if aligned else None,
            reason='与C1分句相等或受限措辞转换；未独立核实。' if aligned else '尚无逐断言语义审查或来源映射。')
        review=reviewed.get(text)
        if not aligned and review:
            anchors=[(original,source_id),*[(str(v),'entry_context.'+k) for k,v in context.items() if k in ('name','organization','role','period')]]
            anchor=next(((q,k) for q,k in anchors if review.source_quote and review.source_quote in q),None)
            item.status=review.status if anchor or review.status!='supported' else 'uncertain'
            item.assessed_by='model_semantic_unverified';item.source_quote=review.source_quote or None
            item.source_id=anchor[1] if anchor else None;item.reason=review.reason if anchor else '模型未提供有效C1原文摘录，不能认定支持。'
        clause_issues=additional_hard_issues(original,text)
        if clause_issues:
            item.status='contradicted' if any('否定实体冲突' in issue for issue in clause_issues) else 'unsupported'
            item.assessed_by='deterministic_gate';item.reason='程序门禁：'+'；'.join(clause_issues)
        claims.append(item)
    unresolved=[c.claim_id for c in claims if c.status!='supported']
    return ClaimAudit(source_hash=state_hash(original),draft_hash=state_hash(proposed),claims=claims,hard_issues=hard,
        unresolved_ids=unresolved,acceptable=bool(claims) and not hard and not unresolved)
