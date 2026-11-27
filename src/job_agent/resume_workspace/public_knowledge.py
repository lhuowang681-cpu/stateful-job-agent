"""Small versioned public corpus; question answers are never in public search DTOs."""
from __future__ import annotations
from contextlib import nullcontext
from dataclasses import asdict
from hashlib import sha256
import json,math
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit
from fastapi import Depends,Query
from pydantic import Field,model_validator
from job_agent.schemas import StrictModel
from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.bm25_index import BM25Index
from job_agent.knowledge.vector_index import InMemoryVectorIndex
from job_agent.knowledge.rrf import reciprocal_rank_fusion
from job_agent.knowledge.index_manifest import declared_identity, manifest_for, valid_vector
from job_agent.knowledge.retrieval_policy import RetrievalSettings,output_budget
from job_agent.knowledge.reranker import apply_rerank
from job_agent.resume_workspace.long_term import encoded,digest
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.evidence_reference import EvidenceReference


class KnowledgeEntry(StrictModel):
    entry_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    kind:Literal['doc','question']
    title:str=Field(min_length=1,max_length=200)
    body:str=Field(min_length=1,max_length=12000)
    tags:list[str]=Field(max_length=12)
    source_url:str=Field(min_length=1,max_length=1000)
    source_version:str=Field(min_length=1,max_length=300)
    license:str=Field(min_length=1,max_length=120)
    content_basis:Literal['project_authored_summary_not_official_quote','licensed_source_excerpt']
    updated_at:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    applicable_role:str=Field(min_length=1,max_length=150)
    difficulty:Literal['beginner','intermediate','advanced']='intermediate'
    technical_doc_id:str|None=None
    answer_points:list[str]=Field(default_factory=list,max_length=6)
    aliases:list[list[str]]=Field(default_factory=list,max_length=6)
    followups:list[str]=Field(default_factory=list,max_length=6)

    @model_validator(mode='after')
    def safe_entry(self):
        url=urlsplit(self.source_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('https_reference_url_required')
        if any(not t.strip() or len(t)>80 for t in self.tags):raise ValueError('invalid_tag')
        if self.kind=='question' and not (1<=len(self.answer_points)==len(self.aliases)==len(self.followups)<=6):raise ValueError('question_rubric_shape')
        if self.kind=='question' and (any(not x.strip() for x in [*self.answer_points,*self.followups]) or any(not group or any(not a.strip() for a in group) for group in self.aliases)):raise ValueError('question_rubric_empty')
        if any(len(p)>1000 for p in [*self.answer_points,*self.followups]) or any(len(a)>200 or len(group)>12 for group in self.aliases for a in group):raise ValueError('rubric_limit')
        return self


class KnowledgeQuery(StrictModel):
    query:str=Field(min_length=1,max_length=600)
    kind:Literal['doc','question']='doc'
    method:Literal['tag','bm25','dense','hybrid']|None=None
    limit:int=Field(default=5,ge=1,le=20)
    rerank:bool|None=None


def entry_text(entry):return entry.title+'\n'+entry.body


class PublicKnowledgeRepository:
    def __init__(self,workspace,*,seed=True):
        self.workspace=workspace
        with workspace._connection(write=True) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS v3_public_entries (
                entry_id TEXT PRIMARY KEY,current_version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS v3_public_versions (
                version_id TEXT PRIMARY KEY,entry_id TEXT NOT NULL REFERENCES v3_public_entries(entry_id) ON DELETE CASCADE,
                payload TEXT NOT NULL,payload_hash TEXT NOT NULL,body_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS v3_public_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
            seeded=db.execute("SELECT 1 FROM v3_public_meta WHERE key='initialized'").fetchone() is not None
        if seed and not seeded:
            from job_agent.resume_workspace.public_seed import seed_entries
            entries=seed_entries();self.install(entries)
            with workspace._connection(write=True) as db:db.execute("INSERT OR IGNORE INTO v3_public_meta VALUES ('initialized',?)",(digest(entries),))

    def install(self,entries):
        """Server-side curator operation, never exposed to ordinary client tokens."""
        entries=[KnowledgeEntry.model_validate(x) for x in entries];added=0;duplicates=[]
        with self.workspace._connection(write=True) as db:
            existing_ids={r[0] for r in db.execute('SELECT entry_id FROM v3_public_entries')}
            if len(existing_ids|{e.entry_id for e in entries})>500:raise WorkspaceConflict('public_corpus_quota')
            for entry in entries:
                payload=encoded(entry.model_dump());version='knowledge-'+sha256(payload.encode()).hexdigest()
                body_hash=sha256(entry.body.strip().casefold().encode()).hexdigest()
                duplicate=db.execute('''SELECT e.entry_id FROM v3_public_entries e JOIN v3_public_versions v ON e.current_version=v.version_id
                    WHERE v.body_hash=? AND e.entry_id<>?''',(body_hash,entry.entry_id)).fetchone()
                if duplicate:duplicates.append(entry.entry_id);continue
                old=db.execute('SELECT 1 FROM v3_public_versions WHERE version_id=?',(version,)).fetchone()
                db.execute('INSERT INTO v3_public_entries VALUES (?,?) ON CONFLICT(entry_id) DO UPDATE SET current_version=excluded.current_version',(entry.entry_id,version))
                db.execute('INSERT OR IGNORE INTO v3_public_versions VALUES (?,?,?,?,?)',(version,entry.entry_id,payload,sha256(payload.encode()).hexdigest(),body_hash))
                added+=not bool(old)
        return {'new_versions':added,'duplicate_entries_skipped':duplicates}

    def get(self,entry_id,version=None,*,db=None):
        with (nullcontext(db) if db is not None else self.workspace._connection()) as db:
            entry=db.execute('SELECT * FROM v3_public_entries WHERE entry_id=?',(entry_id,)).fetchone()
            if entry is None:raise WorkspaceNotFound('knowledge_entry_not_found')
            row=db.execute('SELECT * FROM v3_public_versions WHERE entry_id=? AND version_id=?',(entry_id,version or entry['current_version'])).fetchone()
            if row is None:raise WorkspaceNotFound('knowledge_version_not_found')
            if sha256(row['payload'].encode()).hexdigest()!=row['payload_hash']:raise WorkspaceConflict('public_knowledge_integrity_failed')
            return KnowledgeEntry.model_validate_json(row['payload']),row['version_id']

    def entries(self):
        with self.workspace._connection() as db:ids=[r[0] for r in db.execute('SELECT entry_id FROM v3_public_entries ORDER BY entry_id')]
        return [self.get(key) for key in ids]

    def delete(self,entry_id):
        with self.workspace._connection(write=True) as db:db.execute('DELETE FROM v3_public_entries WHERE entry_id=?',(entry_id,))

    def reference(self,entry,version,method):
        text=entry_text(entry);h=sha256(text.encode()).hexdigest()
        return EvidenceReference(evidence_id='public-'+sha256((entry.entry_id+version+h).encode()).hexdigest()[:28],
            scope='public_knowledge',snapshot_id=version,source_id=entry.entry_id,content_hash=h,path='knowledge/'+entry.entry_id+'.md',
            start_line=1,end_line=len(text.splitlines()),retrieval_method=method,
            evidence_kind='question' if entry.kind=='question' else 'documentation',quote=text)

    def validate_reference(self,reference,*,db=None):
        if reference.scope!='public_knowledge' or reference.owner_id is not None:raise WorkspaceNotFound('public_reference_not_found')
        entry,version=self.get(reference.source_id,reference.snapshot_id,db=db)
        actual=self.reference(entry,version,reference.retrieval_method)
        for field in ('evidence_id','content_hash','path','start_line','end_line','quote','evidence_kind','owner_id','project_id','commit'):
            if getattr(reference,field)!=getattr(actual,field):raise WorkspaceConflict('public_reference_invalid')
        return actual


def public_entry(entry,version):
    # Deliberately no answer_points, aliases, followups or proposed next question.
    fields=('entry_id','kind','title','body','tags','source_url','source_version','license','content_basis','updated_at','applicable_role','difficulty')
    return {**{key:getattr(entry,key) for key in fields},'version_id':version}


class PublicKnowledgeService:
    def __init__(self,workspace,*,embedding_backend=None,seed=True,reranker=None,retrieval_settings=None,prewarm=True):
        self.repository=PublicKnowledgeRepository(workspace,seed=seed);self.embedding_backend=embedding_backend
        self._embedding_cache={};self._lock=RLock()
        self.reranker=reranker;self.settings=retrieval_settings or RetrievalSettings()
        self.default_method='hybrid' if embedding_backend is not None else 'bm25'
        if prewarm and embedding_backend is not None and getattr(embedding_backend,'require_prebuilt',False):self.prewarm()

    def prewarm(self):
        """Trusted startup/curator hook, not an ordinary user mutation route."""
        return [self.search('startup-prewarm',kind=kind,method='dense',limit=1,rerank=False,_prewarm=True)['retrieval_trace']['index_identity']
                for kind in ('doc','question')]

    def _pool(self,kind,tags=()):
        records=[(e,v) for e,v in self.repository.entries() if e.kind==kind and (not tags or set(tags)&set(e.tags))]
        chunks=[];lookup={}
        for entry,version in records:
            text=entry_text(entry)+'\n'+' '.join(entry.tags)
            chunk=KnowledgeChunk(chunk_id=version,document_id=entry.entry_id,document_version=1,
                document_content_hash=sha256(text.encode()).hexdigest(),text=text,chunk_index=len(chunks),start_offset=0,end_offset=len(text))
            chunks.append(chunk);lookup[version]=(entry,version)
        return records,chunks,lookup

    def _snapshot_manifest(self,kind):
        if self.embedding_backend is None:raise WorkspaceConflict('public_cache_declared_model_required')
        spec=declared_identity(self.embedding_backend)
        if spec.dimension is None:raise WorkspaceConflict('public_cache_declared_model_required')
        _,chunks,_=self._pool(kind)
        manifest=manifest_for(chunks,corpus_kind='public_knowledge',scope=('public',kind),
            parser_version='public-entry-1',splitter_version='entry-title-body-tags-1',embedding=spec)
        return spec,chunks,manifest

    def export_dense_snapshot(self):
        """Trusted curator/research hook; current complete pools only, no source body."""
        from job_agent.knowledge.cache_snapshot import PublicCacheSnapshot
        from job_agent.knowledge.index_manifest import fingerprint
        shards=[]
        for kind in ('doc','question'):
            spec,chunks,manifest=self._snapshot_manifest(kind)
            if not chunks:continue
            with self._lock:
                vectors=self._embedding_cache.get(manifest.key)
                if vectors is None:raise WorkspaceConflict('public_dense_index_needs_prewarm')
                if len(vectors)!=len(chunks) or any(not valid_vector(row,spec.dimension) for row in vectors):raise WorkspaceConflict('public_vector_dimensions_invalid')
                vectors=[[float(v) for v in row] for row in vectors]
            if len(vectors)!=len(chunks) or any(not valid_vector(row,spec.dimension) for row in vectors):raise WorkspaceConflict('public_vector_dimensions_invalid')
            shards.append({'kind':kind,'manifest_key':manifest.key,'chunk_ids':[c.chunk_id for c in chunks],
                'vectors':vectors,'vectors_sha256':fingerprint(vectors)})
        return PublicCacheSnapshot(embedding=asdict(spec),shards=shards).model_dump(mode='json')

    def restore_dense_snapshot(self,value):
        """Validate all shards against live curated sources/model before atomic replace."""
        from pydantic import ValidationError
        from job_agent.knowledge.cache_snapshot import PublicCacheSnapshot
        try:snapshot=PublicCacheSnapshot.model_validate(value)
        except (ValidationError,TypeError,ValueError) as exc:raise WorkspaceConflict('public_dense_snapshot_invalid') from exc
        restored={};expected=set()
        for kind in ('doc','question'):
            spec,chunks,manifest=self._snapshot_manifest(kind)
            if chunks:expected.add(kind)
        if {s.kind for s in snapshot.shards}!=expected:raise WorkspaceConflict('public_dense_snapshot_scope_changed')
        for shard in snapshot.shards:
            spec,chunks,manifest=self._snapshot_manifest(shard.kind)
            if snapshot.embedding!=asdict(spec) or shard.manifest_key!=manifest.key or shard.chunk_ids!=[c.chunk_id for c in chunks]:
                raise WorkspaceConflict('public_dense_snapshot_identity_changed')
            if any(not valid_vector(row,spec.dimension) for row in shard.vectors):raise WorkspaceConflict('public_dense_snapshot_dimensions_invalid')
            restored[manifest.key]=[list(row) for row in shard.vectors]
        with self._lock:self._embedding_cache=restored
        return {'restored_pools':len(restored),'manifest_keys':sorted(restored),'document_encodings':0}

    def search(self,query,*,kind='doc',method=None,limit=5,tags=(),rerank=None,_prewarm=False):
        method=self.default_method if method is None else method
        if not query.strip() or len(query)>600 or kind not in ('doc','question') or method not in ('tag','bm25','dense','hybrid') or not 1<=limit<=20:raise WorkspaceConflict('knowledge_query_invalid')
        # Search metadata remains separate from repository.reference's original quote.
        records,chunks,lookup=self._pool(kind,tags)
        index=BM25Index();index.add(chunks)
        sparse=[r for r in index.search(query=query,limit=self.settings.sparse_candidates) if r.score>0]
        used=method;warnings=[];dense_hits=[];manifest_key=None
        if method=='tag':
            from job_agent.knowledge.contracts import RetrievedChunk
            scores=[(c,sum(tag.casefold() in query.casefold() for tag in lookup[c.chunk_id][0].tags)) for c in chunks]
            ranked=[RetrievedChunk(chunk=c,score=float(score),rank=i+1,retrieval_method='tag') for i,(c,score) in enumerate(sorted(scores,key=lambda x:(-x[1],x[0].chunk_id))) if score>0]
        elif method in ('dense','hybrid') and self.embedding_backend is not None:
            try:q=list(self.embedding_backend.embed_query(query)) if chunks else []
            except Exception as exc:
                if method=='dense':raise WorkspaceConflict('public_embedding_backend_failed') from exc
                fallback=self.search(query,kind=kind,method='bm25',limit=limit,tags=tags,rerank=False)
                fallback.update(method_requested=method,method_used='bm25_fallback',warnings=['public_embedding_backend_failed'])
                fallback['retrieval_trace']['dense_error']='public_embedding_backend_failed'
                return fallback
            if chunks and not valid_vector(q):raise WorkspaceConflict('public_query_vector_invalid')
            try:spec=declared_identity(self.embedding_backend).with_dimension(len(q)) if chunks else None
            except ValueError as exc:raise WorkspaceConflict('public_query_vector_invalid') from exc
            manifest=manifest_for(chunks,corpus_kind='public_knowledge',scope=('public',kind),
                                  parser_version='public-entry-1',splitter_version='entry-title-body-tags-1',embedding=spec) if chunks else None
            corpus=manifest.key if manifest else None;manifest_key=corpus
            with self._lock:
                vectors=self._embedding_cache.get(corpus)
                if vectors is None:
                    if chunks and getattr(self.embedding_backend,'require_prebuilt',False) and not _prewarm:
                        if method=='hybrid':
                            fallback=self.search(query,kind=kind,method='bm25',limit=limit,tags=tags,rerank=False)
                            fallback.update(method_requested='hybrid',method_used='bm25_fallback',warnings=['public_dense_index_needs_prewarm'])
                            return fallback
                        raise WorkspaceConflict('public_dense_index_needs_prewarm')
                    try:vectors=self.embedding_backend.embed_documents([c.text for c in chunks]) if chunks else []
                    except Exception as exc:raise WorkspaceConflict('public_embedding_backend_failed') from exc
                    dimension=len(q)
                    if len(vectors)!=len(chunks) or any(not valid_vector(v,dimension) for v in vectors):
                        raise WorkspaceConflict('public_vector_dimensions_invalid')
                    # Never cache unvalidated vectors or an empty corpus.
                    if len(self._embedding_cache)>=4:self._embedding_cache.clear()
                    if chunks:self._embedding_cache[corpus]=vectors
            dimension=len(vectors[0]) if vectors else 0
            if chunks and (len(vectors)!=len(chunks) or dimension!=len(q) or any(not valid_vector(v,dimension) for v in vectors)):
                with self._lock:self._embedding_cache.clear()
                raise WorkspaceConflict('public_vector_dimensions_invalid')
            dense=InMemoryVectorIndex();dense.add(chunks=chunks,vectors=vectors)
            hits=[r for r in dense.search(query_vector=q,limit=self.settings.dense_candidates) if r.score>0]
            dense_hits=hits
            ranked=hits if method=='dense' else reciprocal_rank_fusion(dense_results=hits,bm25_results=sparse,
                limit=self.settings.fusion_candidates,k=self.settings.rrf_k)
        else:
            if method=='dense':raise WorkspaceConflict('local_embedding_not_configured')
            ranked=sparse
            if method=='hybrid':used='bm25_fallback';warnings.append('semantic_embedding_not_configured')
        ranked=ranked[:self.settings.fusion_candidates];fused_ids=[h.chunk.chunk_id for h in ranked]
        enabled=rerank if rerank is not None else (self.reranker is not None and method=='hybrid')
        ranked,rerank_trace=apply_rerank(query,ranked,reranker=self.reranker,settings=self.settings,enabled=enabled)
        if rerank_trace['rerank_error']:warnings.append(rerank_trace['rerank_error'])
        if rerank_trace['rerank_applied']:used+='_rerank'
        ranked,budget_trace=output_budget(ranked,limit=limit,settings=self.settings)
        if budget_trace['budget_omitted_ids']:warnings.append('context_budget_omitted_whole_spans')
        hits=[]
        for hit in ranked:
            entry,version=lookup[hit.chunk.chunk_id];reference=self.repository.reference(entry,version,used)
            hits.append({'entry':public_entry(entry,version),'reference':reference.model_dump(mode='json'),'score':hit.score,
                'supports_claim':'needs_judgment','source_note':'本项目整理摘要/原创练习，非官方原文镜像或个人经历证据。'})
        return {'hits':hits,'method_requested':method,'method_used':used,'warnings':warnings,
                'retrieval_trace':{'schema_version':'retrieval-trace-2','index_identity':manifest_key,
                    'config_identity':self.settings.key,**budget_trace,**rerank_trace,
                    'sparse_ids':[r.chunk.chunk_id for r in sparse], 'dense_ids':[r.chunk.chunk_id for r in dense_hits],
                    'fused_ids':fused_ids, 'candidate_depth':self.settings.sparse_candidates,
                    'final_evidence_ids':[h['reference']['evidence_id'] for h in hits]},
                'corpus_size':len(records),'provider_calls':0,'dense_available':self.embedding_backend is not None}

    def private_question(self,entry_id,version=None):
        """Internal evaluator/planner API only; public HTTP never returns rubrics."""
        entry,version=self.repository.get(entry_id,version)
        if entry.kind!='question':raise WorkspaceConflict('not_a_question')
        return entry,version


def install_knowledge_routes(app,workspace,owner,service=None):
    service=service or PublicKnowledgeService(workspace)
    @app.post('/api/v2/knowledge/search')
    def post_search(request:KnowledgeQuery,user:str=Depends(owner)):
        return service.search(request.query,kind=request.kind,method=request.method,limit=request.limit,rerank=request.rerank)
    @app.get('/api/v2/knowledge/search')
    def search(query:str=Query(min_length=1,max_length=600),kind:Literal['doc','question']='doc',
               method:Literal['tag','bm25','dense','hybrid']|None=None,limit:int=Query(default=5,ge=1,le=20),
               rerank:bool|None=None,user:str=Depends(owner)):
        return service.search(query,kind=kind,method=method,limit=limit,rerank=rerank)
    @app.get('/api/v2/knowledge/status')
    def status(user:str=Depends(owner)):
        entries=service.repository.entries()
        return {'documents':sum(e.kind=='doc' for e,_ in entries),'questions':sum(e.kind=='question' for e,_ in entries),
                'dense_available':service.embedding_backend is not None,'content_basis':'project_authored_summaries_and_questions',
                'private_question_rubrics_exposed':False}
    return service
