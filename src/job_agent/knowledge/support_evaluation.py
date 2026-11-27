"""Versioned source-location/support-span metrics, separate from semantic truth.

Legacy single-citation whole-gold scores remain unchanged. New union coverage
uses only validated, bounded citations from one authenticated retrieval snapshot.
"""
from __future__ import annotations
from pydantic import Field,model_validator
from job_agent.schemas import StrictModel
from job_agent.knowledge.evaluation_contract import CorpusSnapshot,EvalCase,GoldSpan,valid_span,evaluate_case


class SupportLabel(StrictModel):
    version:str='support-label-1'
    case_id:str
    corpus_snapshot:str
    answerable:bool
    minimal_spans:list[GoldSpan]
    symbol_ranges:list[GoldSpan]=Field(default_factory=list)
    requirement:str='all'
    annotation_status:str='ai_candidate'
    rationale:str=Field(min_length=1)

    @model_validator(mode='after')
    def shape(self):
        if self.version!='support-label-1' or self.annotation_status!='ai_candidate':raise ValueError('unsupported_support_label')
        if self.requirement not in ('all','any'):raise ValueError('support_requirement_invalid')
        if self.answerable!=bool(self.minimal_spans):raise ValueError('support_answerability_mismatch')
        if len({(g.document_id,g.start_line,g.end_line) for g in self.minimal_spans})!=len(self.minimal_spans):
            raise ValueError('support_duplicate_span')
        return self


class LocatedSpan(StrictModel):
    span:GoldSpan
    corpus_snapshot:str
    source_version:str
    snapshot_id:str


def merged_intervals(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return merged


def evaluate_support(case:EvalCase,corpus:CorpusSnapshot,label:SupportLabel,retrieved:list[LocatedSpan],*,
                     snapshot_id:str,limit=5,context_char_budget=24000,max_span_chars=12000,max_span_lines=80):
    if limit<1 or min(context_char_budget,max_span_chars,max_span_lines)<1:raise ValueError('support_budget_invalid')
    if label.case_id!=case.case_id or label.corpus_snapshot!=corpus.snapshot_id or case.source_snapshot!=corpus.snapshot_id:
        raise ValueError('support_case_identity_mismatch')
    if label.answerable!=case.answerable:raise ValueError('support_case_answerability_mismatch')
    documents={d.document_id:d for d in corpus.documents}
    if any(not valid_span(g,documents) for g in label.minimal_spans+label.symbol_ranges):raise ValueError('support_label_span_invalid')
    if any(documents[g.document_id].split!=case.split for g in label.minimal_spans+label.symbol_ranges):
        raise ValueError('support_label_source_split_mismatch')
    hits=retrieved[:limit];accepted=[];rejected=[];used=0
    for rank,hit in enumerate(hits,1):
        span=hit.span;doc=documents.get(span.document_id);reason=None;used+=len(span.quote)
        if hit.corpus_snapshot!=corpus.snapshot_id or hit.snapshot_id!=snapshot_id:reason='snapshot_mismatch'
        elif doc is None or hit.source_version!=doc.source_version:reason='source_version_mismatch'
        elif not valid_span(span,documents):reason='invalid_source_span'
        elif len(span.quote)>max_span_chars or span.end_line-span.start_line+1>max_span_lines or used>context_char_budget:
            reason='context_budget_exceeded'
        if reason:rejected.append({'rank':rank,'reason':reason})
        else:accepted.append((rank,span))
    def same(a,b):return a.document_id==b.document_id and a.content_hash==b.content_hash
    matched=[];single=[];covered_lines=0;total_lines=0
    for gold in label.minimal_spans:
        intervals=merged_intervals([(s.start_line,s.end_line) for _,s in accepted if same(s,gold)])
        single.append(any(same(s,gold) and s.start_line<=gold.start_line and s.end_line>=gold.end_line for _,s in accepted))
        covered=sum(max(0,min(end,gold.end_line)-max(start,gold.start_line)+1) for start,end in intervals)
        count=gold.end_line-gold.start_line+1
        covered_lines+=covered;total_lines+=count;matched.append(covered==count)
    files={g.document_id for g in label.minimal_spans}
    located={s.document_id for _,s in accepted}&files
    symbols=[any(same(s,g) and s.start_line<=g.end_line and s.end_line>=g.start_line for _,s in accepted) for g in label.symbol_ranges]
    enough=lambda values:(all(values) if label.requirement=='all' else any(values)) if values else None
    original_matched=[];original_lines=0;original_total=0
    for gold in case.gold:
        intervals=merged_intervals([(s.start_line,s.end_line) for _,s in accepted if same(s,gold)])
        covered=sum(max(0,min(end,gold.end_line)-max(start,gold.start_line)+1) for start,end in intervals)
        count=gold.end_line-gold.start_line+1
        original_matched.append(covered==count);original_lines+=covered;original_total+=count
    first=next((rank for rank,s in accepted if any(same(s,g) and s.start_line<=g.start_line and s.end_line>=g.end_line
                                                for g in label.minimal_spans)),None)
    return {'version':'support-eval-1.1','case_id':case.case_id,'annotation_status':'ai_candidate',
            'file_location_recall':len(located)/len(files) if files else None,
            'symbol_range_location_recall':sum(symbols)/len(symbols) if symbols else None,
            'minimal_single_span_recall':sum(single)/len(single) if single else None,
            'minimal_single_sufficient':enough(single),'minimal_union_span_recall':sum(matched)/len(matched) if matched else None,
            'minimal_union_sufficient':enough(matched),'minimal_line_coverage':covered_lines/total_lines if total_lines else None,
            'minimal_reciprocal_rank':1/first if first else (0. if label.answerable else None),
            'validated_bounded_citations':len(accepted),'rejected_citations':rejected,'context_chars':used,
            'context_char_budget':context_char_budget,'unanswerable_has_context':bool(hits) if not label.answerable else None,
            'original_gold_union_sufficient':((all(original_matched) if case.gold_requirement=='all' else any(original_matched)) if original_matched else None),
            'original_gold_union_span_recall':sum(original_matched)/len(original_matched) if original_matched else None,
            'original_gold_union_line_coverage':original_lines/original_total if original_total else None,
            'legacy_strict_single_citation':evaluate_case(case,corpus,[h.span for h in hits],limit=limit),
            'generated_claim_support':None,'correct_refusal':None,'question_answerability':None,'human_reviewed':0}
