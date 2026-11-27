"""Frozen source/gold contracts. Retrieval metrics never imply claim support."""
from __future__ import annotations
from hashlib import sha256
from typing import Literal
from pydantic import Field, model_validator
from job_agent.schemas import StrictModel
from job_agent.knowledge.index_manifest import fingerprint


class CorpusDocument(StrictModel):
    document_id: str = Field(min_length=1)
    kind: Literal['code','project_documentation','public_knowledge']
    split: Literal['dev','test']
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    origin: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    license: str = Field(min_length=1)

    @model_validator(mode='after')
    def exact_content(self):
        if sha256(self.text.encode()).hexdigest()!=self.content_hash:raise ValueError('corpus_content_hash_mismatch')
        return self


class CorpusSnapshot(StrictModel):
    snapshot_id: str = Field(min_length=1)
    documents: list[CorpusDocument] = Field(min_length=1)

    @model_validator(mode='after')
    def fixed_identity(self):
        if len({d.document_id for d in self.documents})!=len(self.documents):raise ValueError('duplicate_document_id')
        actual='corpus-'+fingerprint([d.model_dump() for d in sorted(self.documents,key=lambda d:d.document_id)])
        if self.snapshot_id!=actual:raise ValueError('corpus_snapshot_mismatch')
        return self


class GoldSpan(StrictModel):
    document_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1)


class EvalCase(StrictModel):
    case_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    source_snapshot: str = Field(min_length=1)
    query: str = Field(min_length=1,max_length=600)
    category: Literal['exact_symbol','natural_language','multi_evidence','documentation','unanswerable']
    answerable: bool
    gold: list[GoldSpan]
    gold_requirement: Literal['all','any'] = 'all'
    split: Literal['dev','test']
    annotation_status: Literal['ai_candidate','human_reviewed'] = 'ai_candidate'
    annotation_note: str = Field(min_length=1)
    unanswerable_reason: str | None = None
    retrieval_scope: Literal['project','public'] | None = None

    @model_validator(mode='after')
    def answer_contract(self):
        if self.answerable!=bool(self.gold):raise ValueError('answerable_gold_mismatch')
        if not self.answerable and not self.unanswerable_reason:raise ValueError('unanswerable_reason_required')
        if len({(g.document_id,g.start_line,g.end_line) for g in self.gold})!=len(self.gold):
            raise ValueError('duplicate_gold_span')
        return self


def valid_span(span: GoldSpan, documents: dict[str,CorpusDocument]) -> bool:
    doc=documents.get(span.document_id)
    if doc is None or span.content_hash!=doc.content_hash:return False
    lines=doc.text.splitlines(keepends=True)
    return (1<=span.start_line<=span.end_line<=len(lines)
            and span.quote==''.join(lines[span.start_line-1:span.end_line]))


class EvaluationDataset(StrictModel):
    dataset_version: str = Field(min_length=1)
    corpus: CorpusSnapshot
    cases: list[EvalCase] = Field(min_length=1)
    policy: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_dataset(self):
        documents={d.document_id:d for d in self.corpus.documents}
        families={};queries=set();ids=set()
        for case in self.cases:
            if case.case_id in ids:raise ValueError('duplicate_case_id')
            ids.add(case.case_id)
            if case.source_snapshot!=self.corpus.snapshot_id:raise ValueError('case_snapshot_mismatch')
            if families.setdefault(case.family,case.split)!=case.split:raise ValueError('family_split_leakage')
            normalized=''.join(c for c in case.query.casefold() if c.isalnum())
            if normalized in queries:raise ValueError('duplicate_normalized_query')
            queries.add(normalized)
            for gold in case.gold:
                if not valid_span(gold,documents):raise ValueError('gold_span_invalid')
                if documents[gold.document_id].split!=case.split:raise ValueError('gold_source_split_leakage')
                if case.retrieval_scope is not None and (documents[gold.document_id].kind=='public_knowledge')!=(case.retrieval_scope=='public'):
                    raise ValueError('gold_retrieval_scope_mismatch')
        return self


def evaluate_case(case: EvalCase, corpus: CorpusSnapshot, retrieved: list[GoldSpan], *, limit=5):
    """Any-gold Hit/MRR and all-gold coverage have separate denominators.

    Inputs are canonical source citations, not arbitrary model support labels.
    The caller maps service references to the frozen document IDs.
    """
    if limit<1:raise ValueError('evaluation_limit_invalid')
    if case.source_snapshot!=corpus.snapshot_id:raise ValueError('case_snapshot_mismatch')
    documents={d.document_id:d for d in corpus.documents}
    if any(not valid_span(g,documents) for g in case.gold):raise ValueError('gold_span_invalid')
    hits=retrieved[:limit];valid=[valid_span(h,documents) for h in hits]
    # Ranks of invalid citations still consume the top-k budget.
    matched=[any(ok and h.document_id==g.document_id and h.content_hash==g.content_hash
                 and h.start_line<=g.start_line and h.end_line>=g.end_line for h,ok in zip(hits,valid)) for g in case.gold]
    first=next((rank for rank,(h,ok) in enumerate(zip(hits,valid),1) if ok and any(
        h.document_id==g.document_id and h.content_hash==g.content_hash and h.start_line<=g.start_line
        and h.end_line>=g.end_line for g in case.gold)),None)
    return {'case_id':case.case_id,'annotation_status':case.annotation_status,
        'hit_any_gold':bool(any(matched)) if case.answerable else None,
        'gold_span_recall':sum(matched)/len(matched) if matched else None,
        'sufficient_gold_retrieved':(all(matched) if case.gold_requirement=='all' else any(matched)) if matched else None,
        'reciprocal_rank':(1/first if first else 0.) if case.answerable else None,
        'citation_valid_rate':sum(valid)/len(valid) if valid else None,
        'retrieved_context_on_unanswerable':bool(hits) if not case.answerable else None,
        'claim_support':None,'final_business_quality':None}
