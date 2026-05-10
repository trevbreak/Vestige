"""
Unit tests for Phase 2 audio processing modules.

These tests run without GPU/hardware dependencies — all modules
degrade gracefully when their optional libraries are not installed.
"""

import numpy as np
import pytest
import time


# ── AEC Gate ─────────────────────────────────────────────────────────────────

class TestEchoGate:
    def test_gate_open_by_default(self):
        from app.audio.aec_gate import EchoGate
        gate = EchoGate(decay_ms=50)
        assert gate.is_open() is True

    def test_gate_closes_on_tts_start(self):
        from app.audio.aec_gate import EchoGate
        gate = EchoGate(decay_ms=50)
        gate.on_tts_start()
        assert gate.is_open() is False
        assert gate.is_closed is True

    def test_gate_remains_closed_during_decay(self):
        from app.audio.aec_gate import EchoGate
        gate = EchoGate(decay_ms=200)
        gate.on_tts_start()
        gate.on_tts_end()
        # Immediately after end, gate should still be closed (decay not elapsed)
        assert gate.is_open() is False

    def test_gate_opens_after_decay(self):
        from app.audio.aec_gate import EchoGate
        gate = EchoGate(decay_ms=10)
        gate.on_tts_start()
        gate.on_tts_end()
        time.sleep(0.05)  # Wait for 10ms decay
        assert gate.is_open() is True

    def test_gate_tts_start_then_end_cycles(self):
        from app.audio.aec_gate import EchoGate
        gate = EchoGate(decay_ms=10)
        gate.on_tts_start()
        assert gate.is_closed
        gate.on_tts_end()
        time.sleep(0.05)
        assert gate.is_open()
        gate.on_tts_start()
        assert gate.is_closed


# ── Backchannel Classifier ───────────────────────────────────────────────────

class TestBackchannelClassifier:
    def test_mm_is_backchannel(self):
        from app.audio.backchannel_classifier import classify_utterance
        assert classify_utterance("mm") == "backchannel"

    def test_yeah_is_backchannel(self):
        from app.audio.backchannel_classifier import classify_utterance
        assert classify_utterance("Yeah") == "backchannel"

    def test_uh_huh_is_backchannel(self):
        from app.audio.backchannel_classifier import classify_utterance
        assert classify_utterance("uh huh") == "backchannel"

    def test_no_way_is_backchannel(self):
        from app.audio.backchannel_classifier import classify_utterance
        assert classify_utterance("no way!") == "backchannel"

    def test_long_sentence_is_statement(self):
        from app.audio.backchannel_classifier import classify_utterance
        text = "I want to attack the goblin with my sword."
        assert classify_utterance(text) == "statement"

    def test_question_is_statement(self):
        from app.audio.backchannel_classifier import classify_utterance
        assert classify_utterance("What do you think about this?") == "statement"

    def test_empty_string_is_backchannel_token_match(self):
        from app.audio.backchannel_classifier import classify_utterance
        # Empty → no tokens match, treated as statement (length 0 words ≤ 4, no token)
        assert classify_utterance("") == "statement"

    def test_is_inaudible_tags(self):
        from app.audio.backchannel_classifier import is_inaudible
        assert is_inaudible("[inaudible]") is True
        assert is_inaudible("[noise]") is True
        assert is_inaudible("Hello there") is False

    def test_case_insensitive(self):
        from app.audio.backchannel_classifier import classify_utterance
        assert classify_utterance("YEAH") == "backchannel"
        assert classify_utterance("Hmm") == "backchannel"


# ── Overlap Detector ─────────────────────────────────────────────────────────

class TestOverlapDetector:
    def _make_audio(self, length_samples: int = 16000, amplitude: int = 1000) -> np.ndarray:
        return (np.random.randn(length_samples) * amplitude).astype(np.int16)

    def test_short_segment_no_overlap(self):
        from app.audio.overlap_detector import detect_overlap
        audio = self._make_audio(100)  # too short
        assert detect_overlap(audio) is False

    def test_uniform_audio_no_overlap(self):
        from app.audio.overlap_detector import detect_overlap
        # Perfectly flat energy = single steady speaker
        audio = np.full(16000, 500, dtype=np.int16)
        assert detect_overlap(audio) is False

    def test_rms_computation(self):
        from app.audio.overlap_detector import rms
        audio = np.array([1000, -1000, 1000, -1000], dtype=np.int16)
        assert abs(rms(audio) - 1000.0) < 1.0

    def test_select_dominant_half(self):
        from app.audio.overlap_detector import select_dominant_half, rms
        # First half is loud, second is quiet
        loud = np.full(8000, 10000, dtype=np.int16)
        quiet = np.full(8000, 100, dtype=np.int16)
        audio = np.concatenate([loud, quiet])
        result = select_dominant_half(audio)
        assert rms(result) > 1000  # Should return the loud half


# ── Context Engine ───────────────────────────────────────────────────────────

class TestContextEngine:
    def _engine_with_avatar(self, mode="active"):
        from app.audio.context_engine import ContextEngine
        engine = ContextEngine()
        engine.register_avatar(1, "Aldric", mode)
        return engine

    def test_absent_avatar_never_responds(self):
        engine = self._engine_with_avatar(mode="absent")
        d = engine.evaluate("Aldric, what do you do?", avatar_id=1)
        assert d.should_respond is False
        assert d.reason == "mode_absent"

    def test_direct_address_triggers_response(self):
        engine = self._engine_with_avatar()
        d = engine.evaluate("Aldric, what do you think?", avatar_id=1)
        assert d.should_respond is True
        assert d.priority <= 3

    def test_question_with_name_is_high_priority(self):
        engine = self._engine_with_avatar()
        d = engine.evaluate("Aldric, what do you do?", avatar_id=1)
        assert d.should_respond is True
        assert d.interrupt_score >= 0.6

    def test_passive_ignores_general_speech(self):
        engine = self._engine_with_avatar(mode="passive")
        d = engine.evaluate("The goblin strikes the fighter!", avatar_id=1)
        assert d.should_respond is False

    def test_passive_responds_to_name(self):
        engine = self._engine_with_avatar(mode="passive")
        d = engine.evaluate("Aldric, what do you do?", avatar_id=1)
        assert d.should_respond is True

    def test_aec_gate_suppresses(self):
        engine = self._engine_with_avatar()
        engine.on_aec_gate_changed(closed=True)
        d = engine.evaluate("Aldric!", avatar_id=1)
        assert d.should_respond is False
        assert d.reason == "aec_gate_closed"

    def test_human_speaking_suppresses(self):
        engine = self._engine_with_avatar()
        engine.on_human_speech_start()
        d = engine.evaluate("Aldric!", avatar_id=1)
        assert d.should_respond is False

    def test_dm_hotword_suppresses(self):
        engine = self._engine_with_avatar()
        engine.on_dm_hotword()
        d = engine.evaluate("Aldric, attack!", avatar_id=1)
        assert d.should_respond is False
        assert d.reason == "dm_hotword_active"

    def test_self_cooldown_suppresses(self):
        engine = self._engine_with_avatar()
        # Simulate avatar just spoke
        engine.on_avatar_spoke(1)
        d = engine.evaluate("Aldric, what now?", avatar_id=1)
        assert d.should_respond is False
        assert d.reason == "self_cooldown"

    def test_combat_context_routes_to_gpt4o(self):
        engine = self._engine_with_avatar()
        d = engine.evaluate("Aldric, roll initiative!", avatar_id=1)
        assert d.should_respond is True
        assert d.context_type == "combat_turn"
        assert d.route == "gpt4o"

    def test_backstory_routes_to_claude(self):
        engine = self._engine_with_avatar()
        d = engine.evaluate("Aldric, tell us about your childhood and family.", avatar_id=1)
        assert d.should_respond is True
        assert d.route == "claude"

    def test_silence_gap_triggers_passive_response(self):
        engine = self._engine_with_avatar()
        # No name, no question, but long silence gap
        d = engine.evaluate("The tavern is quiet.", avatar_id=1, silence_gap=10.0)
        assert d.should_respond is True
        assert d.priority == 5

    def test_interrupt_confidence_scoring(self):
        from app.audio.context_engine import _interrupt_confidence
        # Name + question + directed fragment = capped at 1.0
        assert _interrupt_confidence("Aldric, what do you think?", "Aldric") == 1.0
        # "What do you think?" — question (0.3) + directed fragment "what do you" (0.4) = 0.7
        assert _interrupt_confidence("What do you think?", "Aldric") == pytest.approx(0.7)
        # No signals at all
        assert _interrupt_confidence("The sky is blue.", "Aldric") == 0.0


# ── Pipeline API ─────────────────────────────────────────────────────────────

class TestPipelineAPI:
    @pytest.mark.asyncio
    async def test_pipeline_status_no_session(self, client):
        """Pipeline status for unknown session returns not running."""
        r = await client.get("/api/pipeline/9999/status")
        assert r.status_code == 200
        assert r.json()["running"] is False

    @pytest.mark.asyncio
    async def test_start_pipeline_no_session(self, client):
        """Starting pipeline for non-existent session returns 404."""
        r = await client.post("/api/pipeline/9999/start")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_pipeline_not_running(self, client):
        """Stopping a non-running pipeline returns gracefully."""
        r = await client.post("/api/pipeline/1/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "not_running"

    @pytest.mark.asyncio
    async def test_start_pipeline_ended_session(self, client):
        """Starting pipeline for an ended session returns 400."""
        session = (await client.post("/api/sessions/", json={
            "name": "Test", "avatar_ids": [], "avatar_modes": {}
        })).json()
        await client.post(f"/api/sessions/{session['id']}/end")
        r = await client.post(f"/api/pipeline/{session['id']}/start")
        assert r.status_code == 400
