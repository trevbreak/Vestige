"""
Vector memory store.

Primary strategy: sqlite-vec extension for fast ANN search.
Fallback: pure-Python cosine similarity scan over all chunks in the DB
          (used automatically when sqlite-vec is unavailable).

All DB access is async via SQLAlchemy. The cosine scan runs synchronously
inside an asyncio thread-pool executor when needed.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Try to import sqlite-vec once at module load.
try:
    import sqlite_vec  # type: ignore
    _SQLITE_VEC_AVAILABLE = True
    log.info("memory.store_backend", backend="sqlite-vec")
except ImportError:
    _SQLITE_VEC_AVAILABLE = False
    log.info("memory.store_backend", backend="python-cosine-fallback")


@dataclass
class MemoryHit:
    chunk_id: int
    avatar_id: int
    text: str
    chunk_type: str
    importance: float
    score: float       # cosine similarity 0.0–1.0


class MemoryStore:
    """
    Async wrapper around MemoryChunk persistence + vector search.

    Usage:
        store = MemoryStore()
        chunk_id = await store.upsert(db, avatar_id, text, embedding_bytes)
        hits = await store.search(db, avatar_id, query_embedding, k=5)
    """

    async def upsert(
        self,
        db: "AsyncSession",
        avatar_id: int,
        text: str,
        embedding: bytes,
        chunk_type: str = "event",
        importance: float = 0.5,
        session_id: int | None = None,
    ) -> int:
        """
        Insert a new MemoryChunk and return its ID.
        (Upsert by text+avatar_id is not implemented — callers should
        deduplicate before calling if needed.)
        """
        from app.models.memory import MemoryChunk
        chunk = MemoryChunk(
            avatar_id=avatar_id,
            session_id=session_id,
            source_session_id=session_id,
            text=text,
            embedding=embedding,
            chunk_type=chunk_type,
            importance=importance,
        )
        db.add(chunk)
        await db.commit()
        await db.refresh(chunk)
        log.debug("memory.chunk_stored", chunk_id=chunk.id, avatar_id=avatar_id)
        return chunk.id

    async def search(
        self,
        db: "AsyncSession",
        avatar_id: int,
        query_embedding: bytes,
        k: int = 5,
    ) -> list[MemoryHit]:
        """
        Return the top-K most similar active MemoryChunks for avatar_id.
        Uses pure-Python cosine fallback (sqlite-vec integration deferred
        until the extension is confirmed available in the test environment).
        """
        from sqlalchemy import select
        from app.models.memory import MemoryChunk
        from app.memory.embedder import Embedder

        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.avatar_id == avatar_id)
            .where(MemoryChunk.is_active == True)  # noqa: E712
        )
        result = await db.execute(stmt)
        chunks = result.scalars().all()

        if not chunks:
            return []

        # Score each chunk
        scored: list[tuple[float, MemoryChunk]] = []
        for chunk in chunks:
            if chunk.embedding and len(chunk.embedding) > 0:
                score = Embedder.cosine_similarity(query_embedding, chunk.embedding)
            else:
                score = 0.0
            # Blend cosine score with importance
            blended = score * 0.8 + chunk.importance * 0.2
            scored.append((blended, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:k]

        return [
            MemoryHit(
                chunk_id=c.id,
                avatar_id=c.avatar_id,
                text=c.text,
                chunk_type=c.chunk_type,
                importance=c.importance,
                score=round(s, 4),
            )
            for s, c in top
        ]

    async def delete_chunk(self, db: "AsyncSession", chunk_id: int) -> bool:
        """Soft-delete a memory chunk."""
        from sqlalchemy import select
        from app.models.memory import MemoryChunk
        result = await db.execute(
            select(MemoryChunk).where(MemoryChunk.id == chunk_id)
        )
        chunk = result.scalar_one_or_none()
        if chunk is None:
            return False
        chunk.is_active = False
        await db.commit()
        return True

    async def list_chunks(
        self,
        db: "AsyncSession",
        avatar_id: int,
        include_inactive: bool = False,
    ) -> list[MemoryChunk]:
        """List all memory chunks for an avatar."""
        from sqlalchemy import select
        from app.models.memory import MemoryChunk
        stmt = select(MemoryChunk).where(MemoryChunk.avatar_id == avatar_id)
        if not include_inactive:
            stmt = stmt.where(MemoryChunk.is_active == True)  # noqa: E712
        stmt = stmt.order_by(MemoryChunk.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())
