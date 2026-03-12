"""
Unit tests for Phase 7 — Polish & Inter-Avatar Dynamics.

Covers:
  - CrossAvatarReferencer: recording, retrieval, probability, age cutoff
  - Settings API: GET and PATCH endpoints
  - ContextEngine: DM hotword suppression, multi-avatar evaluation
  - PromptBuilder: cross_avatar_note injection
"""

import random
import time
import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# CrossAvatarReferencer
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossAvatarReferencer:
    def _make(self, probability=1.0, max_age=60.0):
        from app.audio.cross_avatar import CrossAvatarReferencer
        return CrossAvatarReferencer(injection_probability=probability, max_age_seconds=max_age)

    def test_no_note_when_buffer_empty(self):
        ref = self._make(probability=1.0)
        note = ref.get_reference_note(requesting_avatar_id=1, requesting_avatar_name="Kaela")
        assert note == ""

    def test_record_and_retrieve(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "We should press on to the mountains at dawn.")
        note = ref.get_reference_note(2, "Kaela")
        assert "Aldric" in note
        assert "press on" in note

    def test_excludes_requesting_avatar(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "We should press on to the mountains at dawn.")
        # Aldric requests note — should not get own speech
        note = ref.get_reference_note(1, "Aldric")
        assert note == ""

    def test_zero_probability_returns_empty(self):
        ref = self._make(probability=0.0)
        ref.record_speech(1, "Aldric", "We should press on to the mountains at dawn.")
        note = ref.get_reference_note(2, "Kaela")
        assert note == ""

    def test_full_probability_always_returns_note(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "We should press on to the mountains at dawn.")
        rng = random.Random(42)
        for _ in range(10):
            note = ref.get_reference_note(2, "Kaela", rng=rng)
            assert note != ""

    def test_short_utterance_not_recorded(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "Yes.")  # too short (< 4 words)
        note = ref.get_reference_note(2, "Kaela")
        assert note == ""

    def test_old_quotes_excluded(self):
        from app.audio.cross_avatar import AvatarQuote
        ref = self._make(probability=1.0, max_age=1.0)
        # Directly inject an old quote
        ref._buffer.append(AvatarQuote(
            avatar_id=1, name="Aldric",
            text="We should press on to the mountains at dawn.",
            timestamp=time.monotonic() - 10.0,  # 10s ago, max_age=1s
        ))
        note = ref.get_reference_note(2, "Kaela")
        assert note == ""

    def test_most_recent_quote_used(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "We should press on to the mountains at dawn.")
        ref.record_speech(2, "Kaela", "The innkeeper knows more than he lets on, I am sure of it.")
        # Requesting avatar 3 — should get most recent (Kaela's quote)
        note = ref.get_reference_note(3, "Brynn")
        assert "Kaela" in note

    def test_long_quote_truncated(self):
        ref = self._make(probability=1.0)
        long_text = "A" * 200
        ref.record_speech(1, "Aldric", long_text)
        note = ref.get_reference_note(2, "Kaela")
        assert len(note) < 250

    def test_buffer_bounded(self):
        from app.audio.cross_avatar import _BUFFER_SIZE
        ref = self._make(probability=1.0)
        for i in range(_BUFFER_SIZE + 5):
            ref.record_speech(i, f"Avatar{i}", f"This is a long enough utterance to be recorded number {i}.")
        assert ref.buffer_size <= _BUFFER_SIZE

    def test_clear_empties_buffer(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "We should press on to the mountains at dawn.")
        ref.clear()
        assert ref.buffer_size == 0

    def test_note_format(self):
        ref = self._make(probability=1.0)
        ref.record_speech(1, "Aldric", "We must find the crystal before the enemy does.")
        note = ref.get_reference_note(2, "Kaela")
        assert note.startswith("Aldric just said:")
        assert '"' in note


# ═══════════════════════════════════════════════════════════════════════════════
# Settings API
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettingsAPI:
    """Test settings router — in-memory mutation of the Settings singleton."""

    def _get(self):
        from app.routers.settings import get_current_settings
        return get_current_settings()

    def test_get_settings_returns_all_fields(self):
        s = self._get()
        assert hasattr(s, 'vad_threshold')
        assert hasattr(s, 'ollama_model')
        assert hasattr(s, 'silence_gap_trigger')
        assert hasattr(s, 'backchannel_chance')

    def test_patch_vad_threshold(self):
        from app.routers.settings import update_settings, RuntimeSettings, get_current_settings
        from app.config import get_settings

        original = get_settings().vad_threshold
        try:
            body = RuntimeSettings(vad_threshold=0.8)
            result = update_settings(body)
            assert result.vad_threshold == 0.8
        finally:
            # Restore
            object.__setattr__(get_settings(), 'vad_threshold', original)

    def test_patch_multiple_fields(self):
        from app.routers.settings import update_settings, RuntimeSettings
        from app.config import get_settings

        s = get_settings()
        orig_min = s.response_jitter_min
        orig_max = s.response_jitter_max
        try:
            body = RuntimeSettings(response_jitter_min=2.0, response_jitter_max=6.0)
            result = update_settings(body)
            assert result.response_jitter_min == 2.0
            assert result.response_jitter_max == 6.0
        finally:
            object.__setattr__(s, 'response_jitter_min', orig_min)
            object.__setattr__(s, 'response_jitter_max', orig_max)

    def test_patch_invalid_jitter_order_raises(self):
        from app.routers.settings import update_settings, RuntimeSettings
        from fastapi import HTTPException
        body = RuntimeSettings(response_jitter_min=10.0, response_jitter_max=1.0)
        with pytest.raises(HTTPException) as exc:
            update_settings(body)
        assert exc.value.status_code == 400

    def test_patch_none_fields_ignored(self):
        from app.routers.settings import update_settings, RuntimeSettings
        from app.config import get_settings
        original = get_settings().backchannel_chance
        body = RuntimeSettings(backchannel_chance=None)
        result = update_settings(body)
        # No change
        assert result.backchannel_chance == original


# ═══════════════════════════════════════════════════════════════════════════════
# ContextEngine — DM Hotword & Multi-Avatar
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextEngineDMHotword:
    def _engine_with_avatar(self):
        from app.audio.context_engine import ContextEngine
        engine = ContextEngine()
        engine.register_avatar(1, "Aldric", "active")
        return engine

    def test_hotword_suppresses_response(self):
        engine = self._engine_with_avatar()
        engine.on_dm_hotword()
        decision = engine.evaluate("Aldric, what do you do?", avatar_id=1)
        assert not decision.should_respond
        assert decision.reason == "dm_hotword_active"

    def test_response_allowed_after_hotword_expires(self):
        """Simulate hotword having fired >30s ago — should allow response."""
        import time
        engine = self._engine_with_avatar()
        # Manually set hotword timestamp to >30s in the past
        engine._dm_hotword_at = time.monotonic() - 35.0
        decision = engine.evaluate("Aldric, what do you do?", avatar_id=1)
        # Should NOT be blocked by hotword (may still fail other checks but not hotword)
        assert decision.reason != "dm_hotword_active"

    def test_absent_avatar_never_responds(self):
        from app.audio.context_engine import ContextEngine
        engine = ContextEngine()
        engine.register_avatar(2, "Kaela", "absent")
        decision = engine.evaluate("Kaela, what do you do?", avatar_id=2)
        assert not decision.should_respond
        assert decision.reason == "mode_absent"

    def test_passive_avatar_responds_when_named(self):
        from app.audio.context_engine import ContextEngine
        engine = ContextEngine()
        engine.register_avatar(2, "Kaela", "passive")
        decision = engine.evaluate("Kaela, your thoughts on this?", avatar_id=2)
        assert decision.should_respond

    def test_passive_avatar_silent_when_not_named(self):
        from app.audio.context_engine import ContextEngine
        engine = ContextEngine()
        engine.register_avatar(2, "Kaela", "passive")
        decision = engine.evaluate("The tavern is quiet tonight.", avatar_id=2)
        assert not decision.should_respond

    def test_multi_avatar_independent_decisions(self):
        from app.audio.context_engine import ContextEngine
        engine = ContextEngine()
        engine.register_avatar(1, "Aldric", "active")
        engine.register_avatar(2, "Kaela", "passive")

        # Direct question to Aldric by name — Aldric should respond
        d1 = engine.evaluate("Aldric, what do you think?", avatar_id=1)
        assert d1.should_respond
        # Passive avatar with no name mention and pure statement — should not respond
        d2 = engine.evaluate("The tavern is quiet tonight.", avatar_id=2)
        assert not d2.should_respond

    def test_cooldown_suppresses_same_avatar(self):
        import time
        engine = self._engine_with_avatar()
        # Simulate avatar having just spoken
        engine._avatar_states[1].last_spoke_at = time.monotonic()
        engine._last_any_avatar_spoke = time.monotonic()
        decision = engine.evaluate("Aldric, what do you do?", avatar_id=1)
        assert not decision.should_respond
        assert decision.reason in ("self_cooldown", "avatar_cooldown")


# ═══════════════════════════════════════════════════════════════════════════════
# PromptBuilder — cross_avatar_note injection
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptBuilderCrossAvatarNote:
    def _ctx(self, cross_avatar_note="", **kwargs):
        from app.llm.prompt_builder import AvatarContext
        return AvatarContext(
            name="Kaela",
            race="Elf",
            char_class="Ranger",
            level=5,
            cross_avatar_note=cross_avatar_note,
            relationships={"Aldric": "trusted companion"},
            **kwargs,
        )

    def test_cross_avatar_note_injected_in_prompt(self):
        from app.llm.prompt_builder import PromptBuilder
        pb = PromptBuilder()
        ctx = self._ctx(cross_avatar_note='Aldric just said: "We must press on."')
        system, _ = pb.build(ctx)
        assert "Aldric just said" in system

    def test_no_cross_avatar_note_no_injection(self):
        from app.llm.prompt_builder import PromptBuilder
        pb = PromptBuilder()
        ctx = self._ctx(cross_avatar_note="")
        system, _ = pb.build(ctx)
        # Party relationships section present but no "just said"
        assert "just said" not in system

    def test_cross_avatar_note_in_party_relationships_section(self):
        from app.llm.prompt_builder import PromptBuilder
        pb = PromptBuilder()
        ctx = self._ctx(cross_avatar_note='Aldric just said: "We must press on."')
        system, _ = pb.build(ctx)
        # Should appear after the PARTY RELATIONSHIPS header
        rel_idx = system.find("PARTY RELATIONSHIPS")
        note_idx = system.find("Aldric just said")
        assert rel_idx != -1
        assert note_idx > rel_idx
