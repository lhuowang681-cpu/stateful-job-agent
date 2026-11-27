from __future__ import annotations

from pathlib import Path
from typing import Sequence

class QwenEmbeddingBackend:
    def __init__(
        self,
        model_path: str | Path,
        device: str = "cuda",
        *, local_files_only: bool = False,
        max_seq_length: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        # Import only at real model construction, so deterministic tests and
        # skipif-gated model tests do not require the optional GPU dependency.
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as exc:
            raise ImportError(
                "Real Qwen embedding requires the optional embedding dependencies; "
                "install the project with .[embedding] and compatible torch."
            ) from exc
        options = {'device': device}
        if local_files_only:
            options['local_files_only'] = True
        self.model = SentenceTransformer(str(model_path), **options)
        if max_seq_length is not None:
            if max_seq_length < 1:
                raise ValueError('embedding_input_budget_invalid')
            self.model.max_seq_length = min(self.model.max_seq_length, max_seq_length)
        self.batch_size = batch_size

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        options = {'normalize_embeddings': True}
        if self.batch_size is not None:
            if self.batch_size < 1:
                raise ValueError('embedding_batch_size_invalid')
            options.update(batch_size=self.batch_size, show_progress_bar=False)
        embeddings = self.model.encode(
            list(texts),
            **options,
        )

        return embeddings.tolist()

    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        embedding = self.model.encode(
            text,
            prompt_name="query",
            normalize_embeddings=True,
        )

        return embedding.tolist()
