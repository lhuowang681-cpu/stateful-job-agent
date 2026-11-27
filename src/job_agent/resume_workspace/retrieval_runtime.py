"""Explicit offline model loading for the product; disabled unless configured."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version
import os
from pathlib import Path

from job_agent.knowledge.index_manifest import EmbeddingIdentity, fingerprint
from job_agent.knowledge.retrieval_policy import RetrievalSettings
from job_agent.knowledge.reranker import RerankerIdentity,LocalCrossEncoderReranker


def local_model_revision(path: Path) -> str:
    files = sorted(p for p in path.rglob('*') if p.is_file() and '.git' not in p.parts
                   and (p.suffix in ('.json', '.safetensors', '.bin', '.txt', '.model')
                        or p.name == 'merges.txt'))
    if not (path / 'config.json').is_file() or not any(p.suffix in ('.safetensors', '.bin') for p in files):
        raise ValueError('local_embedding_model_incomplete')
    hashes = []
    for item in files:
        digest = sha256()
        with item.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(block)
        hashes.append((item.relative_to(path).as_posix(), digest.hexdigest()))
    return fingerprint(hashes)


@dataclass(frozen=True)
class RetrievalRuntime:
    backend: object | None = None
    identity: EmbeddingIdentity | None = None
    reranker: object | None = None
    settings: RetrievalSettings = RetrievalSettings()

    def __post_init__(self):
        if (self.backend is None) != (self.identity is None):
            raise ValueError('retrieval_backend_and_identity_required_together')
        if self.backend is not None and getattr(self.backend, 'identity', None) != self.identity:
            raise ValueError('retrieval_backend_identity_mismatch')

    def capabilities(self):
        return {'dense_configured': self.backend is not None, 'dense_loaded': self.backend is not None,
                'embedding_identity': asdict(self.identity) if self.identity else None,
                'rerank_loaded': self.reranker is not None, 'quality_verified': False,
                'reranker_identity':asdict(self.reranker.identity) if self.reranker else None,
                'retrieval_settings':asdict(self.settings),'retrieval_config_identity':self.settings.key,
                'vector_build': 'code_index_transaction/public_startup' if self.backend else 'disabled',
                'default_code_method': 'code_aware', 'default_public_method': 'hybrid' if self.backend else 'bm25'}

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        selected = env.get('JOB_AGENT_WORKSPACE_EMBEDDING', 'disabled')
        if selected not in ('disabled','local_qwen'):
            raise ValueError('unknown_workspace_embedding_backend')
        reranker=None
        rerank_path=env.get('JOB_AGENT_WORKSPACE_RERANK_PATH','')
        if rerank_path:
            rp=Path(rerank_path).expanduser().resolve()
            if not rp.is_dir():raise ValueError('local_reranker_directory_required')
            rerank_identity=RerankerIdentity(rp.name,local_model_revision(rp),
                '/'.join(version(package) for package in ('sentence-transformers','transformers','torch')))
            rerank_device=env.get('JOB_AGENT_WORKSPACE_RERANK_DEVICE','cpu')
            if rerank_device not in ('cpu','cuda','cuda:0','cuda:1'):raise ValueError('reranker_device_invalid')
            reranker=LocalCrossEncoderReranker(rp,rerank_identity,device=rerank_device)
        if selected=='disabled':return cls(reranker=reranker)
        path = Path(env.get('JOB_AGENT_WORKSPACE_EMBEDDING_PATH', '')).expanduser()
        if not str(env.get('JOB_AGENT_WORKSPACE_EMBEDDING_PATH', '')).strip() or not path.is_dir():
            raise ValueError('local_embedding_directory_required')
        device = env.get('JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE', 'cpu')
        if device not in ('cpu', 'cuda', 'cuda:0', 'cuda:1'):
            raise ValueError('embedding_device_invalid')
        revision = local_model_revision(path.resolve())
        from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend
        backend = QwenEmbeddingBackend(path.resolve(), device=device, local_files_only=True,
                                       max_seq_length=1024,batch_size=8)
        dimension = (backend.model.get_embedding_dimension() if hasattr(backend.model,'get_embedding_dimension')
                     else backend.model.get_sentence_embedding_dimension())
        prompt = backend.model.prompts.get('query', '')
        identity = EmbeddingIdentity('sentence_transformers_local', path.name, revision,
                                     dimension, 'l2', prompt + '{query}', backend.model.max_seq_length,
                                     '/'.join(version(package) for package in ('sentence-transformers','transformers','torch')))
        backend.identity = identity
        backend.require_prebuilt = True
        return cls(backend, identity,reranker)
