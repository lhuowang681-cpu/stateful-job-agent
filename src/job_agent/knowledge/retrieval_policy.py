"""One versioned budget for both product knowledge paths."""
from dataclasses import asdict,dataclass
from job_agent.knowledge.index_manifest import fingerprint


@dataclass(frozen=True)
class RetrievalSettings:
    sparse_candidates: int = 20
    dense_candidates: int = 20
    fusion_candidates: int = 30
    rerank_candidates: int = 30
    max_output: int = 20
    relation_candidates: int = 8
    context_char_budget: int = 24000
    rerank_input_chars: int = 6000
    rrf_k: int = 60
    dense_rrf_weight: int = 1
    relation_priority: str = 'preserve_direct'
    version: str = 'retrieval-policy-2'

    def __post_init__(self):
        for name,upper in (('sparse_candidates',60),('dense_candidates',60),('fusion_candidates',60),
                           ('rerank_candidates',60),('max_output',20),('context_char_budget',48000),
                           ('rerank_input_chars',12000),('rrf_k',1000)):
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=upper:raise ValueError('retrieval_budget_invalid:'+name)
        if type(self.relation_candidates) is not int or not 0<=self.relation_candidates<=8:
            raise ValueError('retrieval_relation_budget_invalid')
        if self.rerank_candidates>self.fusion_candidates:raise ValueError('rerank_exceeds_fusion_budget')
        if type(self.dense_rrf_weight) is not int or not 1<=self.dense_rrf_weight<=4:
            raise ValueError('retrieval_dense_rrf_weight_invalid')
        if self.relation_priority not in ('legacy_first','preserve_direct'):
            raise ValueError('retrieval_relation_priority_invalid')

    @property
    def key(self):return 'policy-'+fingerprint(asdict(self))


def output_budget(candidates,*,limit,settings):
    """Omit whole source spans; never fabricate a truncated quote citation."""
    selected=[];seen=set();skipped=[];used=0
    for hit in candidates:
        if hit.chunk.chunk_id in seen:continue
        seen.add(hit.chunk.chunk_id)
        if len(selected)>=min(limit,settings.max_output):break
        if used+len(hit.chunk.text)>settings.context_char_budget:
            skipped.append(hit.chunk.chunk_id);continue
        selected.append(hit);used+=len(hit.chunk.text)
    return selected,{'context_chars':used,'context_char_budget':settings.context_char_budget,'budget_omitted_ids':skipped}
