"""
Embedding pipeline for memory chunks.

Uses sentence-transformers (all-MiniLM-L6-v2) to produce 384-dim float32 vectors.
Degrades gracefully when sentence-transformers is not installed — returns zero vectors.

Model loads lazily on first call so test imports never trigger GPU init.
"""

from __future__ import annotations

import struct
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

EMBEDDING_DIM = 384
STUB_EMBEDDING = bytes(EMBEDDING_DIM * 4)  # all-zeros float32 vector


def _pack(vector: list[float]) -> bytes:
    """Pack a list of float32 values into raw bytes."""
    return struct.pack(f"{len(vector)}f", *vector)


def _unpack(raw: bytes) -> list[float]:
    """Unpack raw bytes into a list of float32 values."""
    n = len(raw) // 4
    return list(struct.unpack(f"{n}f", raw))


class Embedder:
    """
    Wraps sentence-transformers SentenceTransformer.
    Falls back to zero-vector stubs if the library is unavailable.
    """

    _model = None
    _available: bool | None = None

    # Model name used by default
    MODEL_NAME = "all-MiniLM-L6-v2"

    def _load(self) -> bool:
        """Load the model once. Returns True if real model loaded."""
        if self._available is not None:
            return self._available
        try:
            import torch
            from sentence_transformers import SentenceTransformer  # type: ignore
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = SentenceTransformer(self.MODEL_NAME, device=device)
            self._available = True
            log.info("memory.embedder_ready", model=self.MODEL_NAME, device=device)
        except Exception as e:
            log.warning("memory.embedder_unavailable", error=str(e))
            self._available = False
        return self._available

    def embed(self, text: str) -> bytes:
        """
        Embed a single string. Returns raw float32 bytes (384 dims).
        Returns a zero-vector stub if sentence-transformers is unavailable.
        """
        if not self._load() or self._model is None:
            return STUB_EMBEDDING
        try:
            vec = self._model.encode(text, normalize_embeddings=True)
            return _pack(vec.tolist())
        except Exception as e:
            log.warning("memory.embed_failed", error=str(e))
            return STUB_EMBEDDING

    def embed_batch(self, texts: list[str]) -> list[bytes]:
        """Embed a list of strings. Returns one bytes blob per text."""
        if not self._load() or self._model is None:
            return [STUB_EMBEDDING] * len(texts)
        try:
            vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
            return [_pack(v.tolist()) for v in vecs]
        except Exception as e:
            log.warning("memory.embed_batch_failed", error=str(e))
            return [STUB_EMBEDDING] * len(texts)

    @staticmethod
    def cosine_similarity(a: bytes, b: bytes) -> float:
        """
        Cosine similarity between two packed float32 vectors.
        Used as fallback when sqlite-vec is unavailable.
        """
        import numpy as np
        n = len(a) // 4
        if len(a) != len(b) or n == 0:
            return 0.0
        va = np.frombuffer(a, dtype=np.float32)
        vb = np.frombuffer(b, dtype=np.float32)
        mag_a = np.linalg.norm(va)
        mag_b = np.linalg.norm(vb)
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return float(np.dot(va, vb) / (mag_a * mag_b))

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    @property
    def is_available(self) -> bool:
        return self._load()


# Module-level singleton
embedder = Embedder()
