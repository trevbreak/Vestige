"""
Memory Retriever.

High-level interface used by the dispatcher to fetch relevant memories
and inject them into AvatarContext.memory_chunks before a prompt build.

Flow:
  1. Embed the current query text (last N transcript lines joined)
  2. Search MemoryStore for top-K hits for this avatar
  3. Return plain strings ready for AvatarContext.memory_chunks

Graceful degradation:
  - If embedder is unavailable: returns [] (no memory injected)
  - If DB is unreachable: logs warning, returns []
"""

from __future__ import annotations

import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Maximum memory chunks injected per prompt
MAX_CHUNKS = 5

# Minimum similarity score to include a hit
MIN_SCORE = 0.3


class MemoryRetriever:
    """
    Async retriever that embeds a query and returns memory chunk texts.
    """

    def __init__(self, k: int = MAX_CHUNKS, min_score: float = MIN_SCORE):
        self._k = k
        self._min_score = min_score

    async def retrieve(
        self,
        db: "AsyncSession",
        avatar_id: int,
        query_text: str,
    ) -> list[str]:
        """
        Embed query_text and return top-K relevant memory texts for avatar_id.
        Returns [] if embedder or DB is unavailable.
        """
        if not query_text.strip():
            return []

        from app.memory.embedder import embedder
        from app.memory.store import MemoryStore

        # Embed the query
        query_embedding = embedder.embed(query_text)

        # Check if embedding is the zero-stub
        if query_embedding == bytes(len(query_embedding)):
            # Embedder is in stub mode — return empty (no false matches)
            log.debug("memory.retriever_stub", avatar_id=avatar_id)
            return []

        store = MemoryStore()
        try:
            hits = await store.search(db, avatar_id, query_embedding, k=self._k)
        except Exception as e:
            log.warning("memory.retriever_search_failed", error=str(e))
            return []

        # Filter by minimum score
        relevant = [h for h in hits if h.score >= self._min_score]

        log.debug(
            "memory.retrieved",
            avatar_id=avatar_id,
            total_hits=len(hits),
            relevant=len(relevant),
        )
        return [h.text for h in relevant]

    async def retrieve_from_transcript(
        self,
        db: "AsyncSession",
        avatar_id: int,
        transcript_lines: list[str],
        n_lines: int = 10,
    ) -> list[str]:
        """
        Convenience wrapper: join the last n_lines of transcript as the query.
        """
        query = " ".join(transcript_lines[-n_lines:])
        return await self.retrieve(db, avatar_id, query)


# Module-level singleton
memory_retriever = MemoryRetriever()
