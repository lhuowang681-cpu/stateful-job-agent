"""Local query/passage scoring. Scores are logits, never claim probabilities."""
from dataclasses import asdict,dataclass
import math
from pathlib import Path
from time import perf_counter
from typing import Protocol,Sequence
from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.knowledge.retrieval_policy import RetrievalSettings


@dataclass(frozen=True)
class RerankerIdentity:
    model: str
    revision: str
    encoder_version: str
    max_pair_tokens: int = 512
    score_semantics: str = 'raw_logit'


@dataclass(frozen=True)
class RerankBatch:
    scores: Sequence[float]
    token_lengths: Sequence[int] = ()
    max_pair_tokens: int = 512


class Reranker(Protocol):
    identity: RerankerIdentity
    def score(self,query:str,passages:Sequence[str])->RerankBatch:...


class LocalCrossEncoderReranker:
    def __init__(self,path:Path,identity:RerankerIdentity,*,device='cpu'):
        from sentence_transformers import CrossEncoder
        import torch
        self.identity=identity
        self.model=CrossEncoder(str(path),device=device,local_files_only=True,
                                max_length=identity.max_pair_tokens,activation_fn=torch.nn.Identity())

    def score(self,query,passages):
        if not passages:return RerankBatch([])
        tokens=self.model.tokenizer([query]*len(passages),list(passages),padding=False,truncation=False,
                                    return_attention_mask=False,return_token_type_ids=False)
        lengths=[len(ids) for ids in tokens['input_ids']]
        scores=self.model.predict([(query,text) for text in passages],batch_size=8,
                                  show_progress_bar=False,convert_to_numpy=True).tolist()
        return RerankBatch(scores,lengths,self.identity.max_pair_tokens)


def apply_rerank(query:str,candidates:Sequence[RetrievedChunk],*,reranker:Reranker|None,
                 settings:RetrievalSettings,enabled:bool):
    original=list(candidates)
    trace={'rerank_requested':enabled,'rerank_applied':False,'rerank_input_ids':[],
           'reranked_ids':[h.chunk.chunk_id for h in original],'rerank_error':None,'rerank_elapsed_ms':0,
           'reranker_identity':asdict(reranker.identity) if reranker else None,
           'rerank_char_truncated_ids':[],'rerank_token_truncated_ids':[]}
    if not enabled or not original:return original,trace
    if reranker is None:
        trace['rerank_error']='rerank_not_configured';return original,trace
    bounded=original[:settings.rerank_candidates];trace['rerank_input_ids']=[h.chunk.chunk_id for h in bounded]
    texts=[h.chunk.text[:settings.rerank_input_chars] for h in bounded]
    trace['rerank_char_truncated_ids']=[h.chunk.chunk_id for h in bounded if len(h.chunk.text)>settings.rerank_input_chars]
    start=perf_counter()
    try:
        batch=reranker.score(query,texts)
        if not isinstance(batch,RerankBatch) or len(batch.scores)!=len(bounded):raise ValueError('rerank_output_invalid')
        if any(isinstance(s,bool) or not isinstance(s,(int,float)) or not math.isfinite(s) for s in batch.scores):
            raise ValueError('rerank_output_invalid')
        if batch.token_lengths and len(batch.token_lengths)!=len(bounded):raise ValueError('rerank_output_invalid')
        trace['rerank_token_truncated_ids']=[h.chunk.chunk_id for h,n in zip(bounded,batch.token_lengths) if n>batch.max_pair_tokens]
        order=sorted(range(len(bounded)),key=lambda i:(-batch.scores[i],bounded[i].chunk.chunk_id))
        ranked=[]
        for i in order:
            old=bounded[i]
            ranked.append(old.model_copy(update={'rank':len(ranked)+1,'score':float(batch.scores[i]),
                'retrieval_method':'rerank','retrieval_metadata':{**old.retrieval_metadata,
                    'base_method':old.retrieval_method,'base_score':old.score,'score_semantics':'raw_logit'}}))
        base_rank=len(ranked)
        ranked.extend(h.model_copy(update={'rank':base_rank+j+1}) for j,h in enumerate(original[len(bounded):]))
        trace.update(rerank_applied=True,reranked_ids=[h.chunk.chunk_id for h in ranked])
        return ranked,trace
    except ValueError:
        trace['rerank_error']='rerank_output_invalid';return original,trace
    except Exception:
        # No exception text: inference errors can include source passages.
        trace['rerank_error']='rerank_backend_failed';return original,trace
    finally:trace['rerank_elapsed_ms']=round((perf_counter()-start)*1000,3)
