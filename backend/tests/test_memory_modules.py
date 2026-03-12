"""
Unit and integration tests for Phase 5 — Memory System.

Tests are designed to run without:
  - sentence-transformers (embedder uses zero-stub)
  - Claude API key (summariser returns stub response)
  - sqlite-vec (vector search falls back to cosine Python scan)

All DB tests use the in-memory SQLite test DB from conftest.py.
"""

import pytest
import pytest_asyncio
import struct
import json


# ── Embedder ──────────────────────────────────────────────────────────────────

class TestEmbedder:
    def test_stub_returns_zero_bytes(self):
        """When sentence-transformers is unavailable, embed() returns zero bytes."""
        from app.memory.embedder import Embedder, EMBEDDING_DIM, STUB_EMBEDDING
        emb = Embedder()
        # Force stub mode (don't load model in test environment)
        emb._available = False
        result = emb.embed("Hello world")
        assert result == STUB_EMBEDDING
        assert len(result) == EMBEDDING_DIM * 4

    def test_stub_batch_returns_list_of_zeros(self):
        from app.memory.embedder import Embedder, STUB_EMBEDDING
        emb = Embedder()
        emb._available = False
        results = emb.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(r == STUB_EMBEDDING for r in results)

    def test_pack_unpack_roundtrip(self):
        from app.memory.embedder import _pack, _unpack
        values = [0.1, 0.2, 0.3, -0.5, 1.0]
        packed = _pack(values)
        unpacked = _unpack(packed)
        assert len(unpacked) == len(values)
        for a, b in zip(values, unpacked):
            assert abs(a - b) < 1e-6

    def test_cosine_similarity_identical(self):
        from app.memory.embedder import Embedder, _pack
        vec = [1.0, 0.0, 0.0, 0.0]
        packed = _pack(vec)
        score = Embedder.cosine_similarity(packed, packed)
        assert abs(score - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self):
        from app.memory.embedder import Embedder, _pack
        a = _pack([1.0, 0.0])
        b = _pack([0.0, 1.0])
        score = Embedder.cosine_similarity(a, b)
        assert abs(score) < 1e-6

    def test_cosine_similarity_zero_vector(self):
        from app.memory.embedder import Embedder, _pack
        a = _pack([0.0, 0.0])
        b = _pack([1.0, 0.0])
        score = Embedder.cosine_similarity(a, b)
        assert score == 0.0

    def test_cosine_similarity_length_mismatch(self):
        from app.memory.embedder import Embedder, _pack
        a = _pack([1.0, 0.0])
        b = _pack([1.0, 0.0, 0.0])
        score = Embedder.cosine_similarity(a, b)
        assert score == 0.0

    def test_is_available_false_when_stub(self):
        from app.memory.embedder import Embedder
        emb = Embedder()
        emb._available = False
        assert emb.is_available is False

    def test_dim_property(self):
        from app.memory.embedder import Embedder, EMBEDDING_DIM
        emb = Embedder()
        assert emb.dim == EMBEDDING_DIM


# ── MemoryStore ────────────────────────────────────────────────────────────────

class TestMemoryStore:
    def _make_embedding(self, value: float = 1.0) -> bytes:
        """Make a simple 4-dim float32 embedding."""
        from app.memory.embedder import _pack
        mag = (value ** 2 * 4) ** 0.5
        if mag == 0:
            return _pack([0.0, 0.0, 0.0, 0.0])
        v = value / mag
        return _pack([v, v, v, v])

    @pytest.mark.asyncio
    async def test_upsert_and_list(self, client):
        """Store a chunk and retrieve it via list_chunks."""
        from app.memory.store import MemoryStore
        from tests.conftest import TestSessionLocal

        # Create an avatar first via API
        r = await client.post("/api/avatars/", json={
            "name": "Kaela", "player_name": "Alice",
            "race": "Elf", "char_class": "Wizard",
        })
        assert r.status_code == 201
        avatar_id = r.json()["id"]

        async with TestSessionLocal() as db:
            store = MemoryStore()
            chunk_id = await store.upsert(
                db=db,
                avatar_id=avatar_id,
                text="Kaela found a mysterious tome in the dungeon.",
                embedding=self._make_embedding(0.9),
                chunk_type="item",
                importance=0.8,
            )
            assert chunk_id > 0

            chunks = await store.list_chunks(db, avatar_id)
            assert len(chunks) == 1
            assert chunks[0].text == "Kaela found a mysterious tome in the dungeon."
            assert chunks[0].chunk_type == "item"

    @pytest.mark.asyncio
    async def test_search_returns_best_match(self, client):
        """Store two chunks with different similarity and confirm retrieval order."""
        from app.memory.store import MemoryStore
        from app.memory.embedder import _pack
        from tests.conftest import TestSessionLocal

        r = await client.post("/api/avatars/", json={
            "name": "Ren", "player_name": "Bob",
            "race": "Human", "char_class": "Rogue",
        })
        assert r.status_code == 201
        avatar_id = r.json()["id"]

        # chunk A: [1,0,0,0], chunk B: [0,1,0,0]
        # query: [1,0,0,0] → chunk A should score 1.0, chunk B 0.0
        chunk_a = _pack([1.0, 0.0, 0.0, 0.0])
        chunk_b = _pack([0.0, 1.0, 0.0, 0.0])
        query = _pack([1.0, 0.0, 0.0, 0.0])

        async with TestSessionLocal() as db:
            store = MemoryStore()
            await store.upsert(db, avatar_id, "First chunk", chunk_a, importance=0.5)
            await store.upsert(db, avatar_id, "Second chunk", chunk_b, importance=0.5)

            hits = await store.search(db, avatar_id, query, k=2)
            assert len(hits) == 2
            assert hits[0].text == "First chunk"   # higher cosine similarity

    @pytest.mark.asyncio
    async def test_search_empty_returns_empty(self, client):
        from app.memory.store import MemoryStore
        from app.memory.embedder import STUB_EMBEDDING
        from tests.conftest import TestSessionLocal

        r = await client.post("/api/avatars/", json={
            "name": "Ghost", "player_name": "Nobody",
            "race": "Human", "char_class": "Fighter",
        })
        avatar_id = r.json()["id"]

        async with TestSessionLocal() as db:
            store = MemoryStore()
            hits = await store.search(db, avatar_id, STUB_EMBEDDING, k=5)
            assert hits == []

    @pytest.mark.asyncio
    async def test_delete_chunk(self, client):
        from app.memory.store import MemoryStore
        from app.memory.embedder import STUB_EMBEDDING
        from tests.conftest import TestSessionLocal

        r = await client.post("/api/avatars/", json={
            "name": "Temp", "player_name": "X",
            "race": "Human", "char_class": "Fighter",
        })
        avatar_id = r.json()["id"]

        async with TestSessionLocal() as db:
            store = MemoryStore()
            cid = await store.upsert(db, avatar_id, "To be deleted", STUB_EMBEDDING)
            deleted = await store.delete_chunk(db, cid)
            assert deleted is True
            chunks = await store.list_chunks(db, avatar_id)
            assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, client):
        from app.memory.store import MemoryStore
        from tests.conftest import TestSessionLocal

        async with TestSessionLocal() as db:
            store = MemoryStore()
            deleted = await store.delete_chunk(db, 99999)
            assert deleted is False


# ── Summariser ────────────────────────────────────────────────────────────────

class TestSessionSummariser:
    def _summariser(self):
        from app.memory.summariser import SessionSummariser
        s = SessionSummariser()
        s._api_key = ""   # force stub mode
        return s

    def test_empty_transcript_returns_stub(self):
        s = self._summariser()
        result = s.post_session([])
        assert result.error == "empty_transcript"
        assert result.summary_text != ""

    def test_no_api_key_returns_stub(self):
        s = self._summariser()
        result = s.post_session(["DM: The party enters the dungeon."])
        assert result.model == "stub"
        assert result.error == "no_response"

    def test_rolling_summary_no_api_key(self):
        s = self._summariser()
        result = s.rolling_summary(["DM: The party enters the dungeon."])
        assert result == "[Summary unavailable]"

    def test_rolling_summary_empty(self):
        s = self._summariser()
        result = s.rolling_summary([])
        assert result == ""

    def test_chunks_from_result_events(self):
        from app.memory.summariser import SummaryResult, SessionSummariser
        summariser = SessionSummariser()
        result = SummaryResult(
            events=["The party found the ancient sword."],
            summary_text="A brief session.",
        )
        chunks = summariser.chunks_from_result(result, avatar_id=1, session_id=1)
        texts = [t for t, _, _ in chunks]
        assert "The party found the ancient sword." in texts
        assert "A brief session." in texts

    def test_chunks_from_result_importance_order(self):
        from app.memory.summariser import SummaryResult, AvatarUpdate, SessionSummariser
        summariser = SessionSummariser()
        result = SummaryResult(
            events=["ev"],
            npcs=[{"name": "Bob", "notes": "innkeeper"}],
            items=[{"name": "Sword", "owner": "Kaela", "notes": "magic"}],
            relationship_deltas=[{"avatar": "Kaela", "target": "Bob", "note": "suspicious"}],
            avatar_updates=[AvatarUpdate(avatar_id=1, avatar_name="Kaela", notes="leveled up")],
            summary_text="Good session.",
        )
        chunks = summariser.chunks_from_result(result, avatar_id=1, session_id=1)
        # relationship_deltas should have importance 0.8
        rel_chunks = [(t, ct, imp) for t, ct, imp in chunks if ct == "relationship"]
        assert len(rel_chunks) == 1
        assert rel_chunks[0][2] == 0.8

    def test_json_parse_valid(self):
        from app.memory.summariser import SessionSummariser
        summariser = SessionSummariser()
        raw = json.dumps({
            "events": ["Goblins attacked"],
            "npcs": [{"name": "Grog", "notes": "enemy chief"}],
            "items": [],
            "relationship_deltas": [],
            "avatar_updates": [],
            "summary_text": "The party fought goblins.",
        })
        # Patch _call_claude to return this
        summariser._api_key = "test"
        summariser._call_claude = lambda s, u: (raw, 100.0)
        result = summariser.post_session(["DM: Goblins!"])
        assert result.events == ["Goblins attacked"]
        assert result.summary_text == "The party fought goblins."
        assert len(result.npcs) == 1

    def test_json_parse_with_surrounding_prose(self):
        from app.memory.summariser import SessionSummariser
        summariser = SessionSummariser()
        inner = json.dumps({
            "events": ["Event A"],
            "npcs": [],
            "items": [],
            "relationship_deltas": [],
            "avatar_updates": [],
            "summary_text": "Good session.",
        })
        raw = f"Here is your JSON:\n{inner}\nThat's all."
        summariser._api_key = "test"
        summariser._call_claude = lambda s, u: (raw, 50.0)
        result = summariser.post_session(["DM: something"])
        assert result.events == ["Event A"]


# ── MemoryRetriever ────────────────────────────────────────────────────────────

class TestMemoryRetriever:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, client):
        from app.memory.retriever import MemoryRetriever
        from tests.conftest import TestSessionLocal

        retriever = MemoryRetriever()
        async with TestSessionLocal() as db:
            result = await retriever.retrieve(db, avatar_id=1, query_text="")
        assert result == []

    @pytest.mark.asyncio
    async def test_stub_embedder_returns_empty(self, client):
        """When embedder produces zero-vector, retriever returns [] to avoid false matches."""
        from app.memory.retriever import MemoryRetriever
        from tests.conftest import TestSessionLocal

        retriever = MemoryRetriever()
        async with TestSessionLocal() as db:
            result = await retriever.retrieve(db, avatar_id=1, query_text="some real text")
        # Embedder in stub mode → zero vector → returns []
        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_from_transcript_joins_lines(self, client):
        """retrieve_from_transcript uses last N lines as query."""
        from app.memory.retriever import MemoryRetriever
        from tests.conftest import TestSessionLocal

        retriever = MemoryRetriever()
        lines = [f"Speaker: line {i}" for i in range(20)]
        async with TestSessionLocal() as db:
            # Just verify it doesn't crash and returns a list
            result = await retriever.retrieve_from_transcript(db, avatar_id=1, transcript_lines=lines)
        assert isinstance(result, list)


# ── Memory API endpoints ───────────────────────────────────────────────────────

class TestMemoryAPI:
    @pytest_asyncio.fixture
    async def session_with_avatar(self, client):
        """Create a session with one avatar for memory API tests."""
        r = await client.post("/api/avatars/", json={
            "name": "Vex", "player_name": "Player1",
            "race": "Tiefling", "char_class": "Warlock",
        })
        assert r.status_code == 201
        avatar = r.json()

        r2 = await client.post("/api/sessions/", json={
            "name": "Test Session",
            "avatar_ids": [avatar["id"]],
            "avatar_modes": {str(avatar["id"]): "active"},
        })
        assert r2.status_code == 201
        session = r2.json()
        return session, avatar

    @pytest.mark.asyncio
    async def test_summarise_session_no_transcript(self, client, session_with_avatar):
        """Summarise with no transcript → stub summary."""
        session, _ = session_with_avatar
        r = await client.post(f"/api/memory/sessions/{session['id']}/summarise", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == session["id"]
        assert "summary_id" in data
        # With no API key, error field will be set
        assert data["model"] in ("stub", "claude-haiku-4-5-20251001")

    @pytest.mark.asyncio
    async def test_get_summary_after_generate(self, client, session_with_avatar):
        session, _ = session_with_avatar
        await client.post(f"/api/memory/sessions/{session['id']}/summarise", json={})
        r = await client.get(f"/api/memory/sessions/{session['id']}/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == session["id"]
        assert data["is_approved"] is False

    @pytest.mark.asyncio
    async def test_get_summary_404_if_none(self, client, session_with_avatar):
        session, _ = session_with_avatar
        r = await client.get(f"/api/memory/sessions/{session['id']}/summary")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_summary(self, client, session_with_avatar):
        session, _ = session_with_avatar
        await client.post(f"/api/memory/sessions/{session['id']}/summarise", json={})
        r = await client.post(f"/api/memory/sessions/{session['id']}/approve")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == session["id"]
        assert "chunks_created" in data

    @pytest.mark.asyncio
    async def test_approve_twice_returns_409(self, client, session_with_avatar):
        session, _ = session_with_avatar
        await client.post(f"/api/memory/sessions/{session['id']}/summarise", json={})
        await client.post(f"/api/memory/sessions/{session['id']}/approve")
        r2 = await client.post(f"/api/memory/sessions/{session['id']}/approve")
        assert r2.status_code == 409

    @pytest.mark.asyncio
    async def test_list_chunks_empty(self, client, session_with_avatar):
        _, avatar = session_with_avatar
        r = await client.get(f"/api/memory/avatars/{avatar['id']}/chunks")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_list_chunks_404_for_missing_avatar(self, client):
        r = await client.get("/api/memory/avatars/99999/chunks")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_chunk_404(self, client):
        r = await client.delete("/api/memory/chunks/99999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_rolling_summary(self, client, session_with_avatar):
        session, _ = session_with_avatar
        r = await client.post(
            f"/api/memory/sessions/{session['id']}/rolling-summary",
            json={"transcript_lines": ["DM: The cave is dark.", "Alice: I light a torch."]}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == session["id"]
        assert isinstance(data["summary_text"], str)

    @pytest.mark.asyncio
    async def test_rolling_summary_appends_to_session(self, client, session_with_avatar):
        """Rolling summaries are appended to SessionSummary.rolling_summaries."""
        session, _ = session_with_avatar
        await client.post(
            f"/api/memory/sessions/{session['id']}/rolling-summary",
            json={"transcript_lines": ["DM: Something happened."]}
        )
        await client.post(
            f"/api/memory/sessions/{session['id']}/rolling-summary",
            json={"transcript_lines": ["DM: More things happened."]}
        )
        r = await client.get(f"/api/memory/sessions/{session['id']}/summary")
        assert r.status_code == 200
        data = r.json()
        assert len(data["rolling_summaries"]) == 2

    @pytest.mark.asyncio
    async def test_summarise_nonexistent_session(self, client):
        r = await client.post("/api/memory/sessions/99999/summarise", json={})
        assert r.status_code == 404


# ── Speaker attribution ────────────────────────────────────────────────────────

class TestSpeakerAttribution:
    @pytest_asyncio.fixture
    async def session_with_transcripts(self, client):
        r = await client.post("/api/sessions/", json={
            "name": "Attribution Test",
            "avatar_ids": [],
            "avatar_modes": {},
        })
        session = r.json()

        # Add some transcript entries via DB directly
        from tests.conftest import TestSessionLocal
        from app.models.transcript import Transcript
        async with TestSessionLocal() as db:
            for i, speaker in enumerate(["Unknown", "Unknown", "Speaker 0"]):
                t = Transcript(
                    session_id=session["id"],
                    speaker=speaker,
                    speaker_type="human",
                    text=f"Line {i}",
                )
                db.add(t)
            await db.commit()
        return session

    @pytest.mark.asyncio
    async def test_attribute_speakers(self, client, session_with_transcripts):
        session = session_with_transcripts
        r = await client.post(
            f"/api/sessions/{session['id']}/speakers",
            json={"attributions": {"Unknown": "Alice", "Speaker 0": "Bob"}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["updated_count"] == 3

    @pytest.mark.asyncio
    async def test_attribute_dm_sets_speaker_type(self, client, session_with_transcripts):
        session = session_with_transcripts
        r = await client.post(
            f"/api/sessions/{session['id']}/speakers",
            json={"attributions": {"Unknown": "DM"}},
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_attribute_nonexistent_session(self, client):
        r = await client.post(
            "/api/sessions/99999/speakers",
            json={"attributions": {"Unknown": "Alice"}},
        )
        assert r.status_code == 404


# ── Sheet update ───────────────────────────────────────────────────────────────

class TestSheetUpdate:
    @pytest_asyncio.fixture
    async def avatar(self, client):
        r = await client.post("/api/avatars/", json={
            "name": "Brom",
            "player_name": "Dave",
            "race": "Dwarf",
            "char_class": "Cleric",
            "hit_points_max": 40,
            "hit_points_current": 40,
            "equipment": ["Warhammer", "Shield"],
        })
        assert r.status_code == 201
        return r.json()

    @pytest.mark.asyncio
    async def test_hp_delta(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"hp_delta": -10},
        )
        assert r.status_code == 200
        data = r.json()
        assert any("HP" in c for c in data["changes"])

    @pytest.mark.asyncio
    async def test_hp_cannot_go_below_zero(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"hp_delta": -999},
        )
        assert r.status_code == 200
        # Avatar is still alive in DB — HP clamped to 0
        r2 = await client.get(f"/api/avatars/{avatar['id']}")
        assert r2.json()["hit_points_current"] == 0

    @pytest.mark.asyncio
    async def test_hp_set(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"hp_set": 25},
        )
        assert r.status_code == 200
        r2 = await client.get(f"/api/avatars/{avatar['id']}")
        assert r2.json()["hit_points_current"] == 25

    @pytest.mark.asyncio
    async def test_items_gained(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"items_gained": ["Holy Symbol", "Potion of Healing"]},
        )
        assert r.status_code == 200
        changes = r.json()["changes"]
        assert any("Holy Symbol" in c for c in changes)

    @pytest.mark.asyncio
    async def test_items_lost(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"items_lost": ["Warhammer"]},
        )
        assert r.status_code == 200
        assert any("removed" in c.lower() for c in r.json()["changes"])

    @pytest.mark.asyncio
    async def test_level_up(self, client, avatar):
        original_level = avatar["level"]
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"level_up": True},
        )
        assert r.status_code == 200
        r2 = await client.get(f"/api/avatars/{avatar['id']}")
        assert r2.json()["level"] == original_level + 1

    @pytest.mark.asyncio
    async def test_relationship_update(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={"relationship_updates": {"Kaela": "Trusted ally after saving her life"}},
        )
        assert r.status_code == 200
        assert any("Relationship" in c for c in r.json()["changes"])

    @pytest.mark.asyncio
    async def test_no_changes_returns_message(self, client, avatar):
        r = await client.post(
            f"/api/avatars/{avatar['id']}/sheet-update",
            json={},
        )
        assert r.status_code == 200
        assert "No changes" in r.json()["changes"][0]

    @pytest.mark.asyncio
    async def test_sheet_update_404_for_missing_avatar(self, client):
        r = await client.post(
            "/api/avatars/99999/sheet-update",
            json={"hp_delta": -5},
        )
        assert r.status_code == 404
