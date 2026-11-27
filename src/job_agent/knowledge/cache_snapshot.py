"""Portable public derived vectors for trusted offline research replay, not a write API."""
import math
from typing import Literal
from pydantic import Field,field_validator,model_validator
from job_agent.schemas import StrictModel
from job_agent.knowledge.index_manifest import fingerprint


class PublicCacheShard(StrictModel):
    kind:Literal['doc','question']
    manifest_key:str=Field(pattern=r'^index-[a-f0-9]{64}$')
    chunk_ids:list[str]=Field(min_length=1,max_length=500)
    vectors:list[list[float]]=Field(min_length=1,max_length=500)
    vectors_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')

    @field_validator('vectors',mode='before')
    @classmethod
    def numeric_budget(cls,value):
        if not isinstance(value,list) or not 1<=len(value)<=500:raise ValueError('public_cache_shape')
        for row in value:
            if not isinstance(row,list) or not 1<=len(row)<=8192 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in row):
                raise ValueError('public_cache_values')
        return value

    @model_validator(mode='after')
    def integrity(self):
        if len(self.chunk_ids)!=len(set(self.chunk_ids)) or len(self.chunk_ids)!=len(self.vectors):raise ValueError('public_cache_shape')
        if fingerprint(self.vectors)!=self.vectors_sha256:raise ValueError('public_cache_vector_hash')
        return self


class PublicCacheSnapshot(StrictModel):
    schema_version:Literal['public-dense-snapshot-1']='public-dense-snapshot-1'
    embedding:dict[str,str|int|None]
    shards:list[PublicCacheShard]=Field(min_length=1,max_length=2)

    @model_validator(mode='after')
    def unique_kind(self):
        if len({s.kind for s in self.shards})!=len(self.shards):raise ValueError('public_cache_duplicate_kind')
        return self
