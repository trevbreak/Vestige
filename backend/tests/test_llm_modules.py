"""
Unit tests for Phase 4 AI Brain modules.

Tests run without real LLM backends:
  - PromptBuilder is pure Python, fully testable
  - LLMRouter: select_route logic tested; actual HTTP calls mocked/stubbed
  - LLMDispatcher: tested with mock LLM that returns canned response
"""

import asyncio
import pytest


# ── Prompt Builder ────────────────────────────────────────────────────────────

class TestPromptBuilder:
    def _ctx(self, **kwargs):
        from app.llm.prompt_builder import AvatarContext
        defaults = dict(
            name="Aldric",
            race="Human",
            char_class="Fighter",
            level=5,
            alignment="Lawful Good",
            background="Soldier",
            player_name="Alice",
            personality_traits="Brave and direct.",
            sentence_style="Action first, then speech.",
            verbal_tics="Invokes his deity occasionally.",
            never_say="I guess, whatever",
            hit_points_current=32,
            hit_points_max=45,
            context_type="combat_turn",
            transcript_lines=["Unknown: The goblin lunges at Aldric!", "Unknown: What do you do?"],
        )
        defaults.update(kwargs)
        return AvatarContext(**defaults)

    def _build(self, **kwargs):
        from app.llm.prompt_builder import PromptBuilder
        pb = PromptBuilder()
        return pb.build(self._ctx(**kwargs))

    def test_system_contains_identity(self):
        system, _ = self._build()
        assert "Aldric" in system
        assert "Human Fighter" in system
        assert "Level 5" in system

    def test_system_contains_player_absent(self):
        system, _ = self._build()
        assert "Alice" in system
        assert "absent" in system.lower()

    def test_system_contains_alignment_background(self):
        system, _ = self._build()
        assert "Lawful Good" in system
        assert "Soldier" in system

    def test_system_contains_personality(self):
        system, _ = self._build()
        assert "Brave and direct" in system

    def test_system_contains_character_voice(self):
        system, _ = self._build()
        assert "Action first, then speech" in system
        assert "Invokes his deity" in system
        assert "I guess, whatever" in system

    def test_system_contains_mechanical_state(self):
        system, _ = self._build()
        assert "32/45" in system

    def test_system_contains_response_rules(self):
        system, _ = self._build()
        assert "NEVER" in system
        assert "first person" in system.lower()
        assert "No markdown" in system

    def test_system_contains_context_type(self):
        system, _ = self._build(context_type="backstory_call")
        assert "backstory_call" in system

    def test_length_instruction_varies_by_context(self):
        system_combat, _ = self._build(context_type="combat_turn")
        system_back, _ = self._build(context_type="backstory_call")
        # Combat: short instructions; backstory: longer allowed
        assert "1 sentence" in system_combat
        assert "4 sentences" in system_back

    def test_user_message_contains_transcript(self):
        _, user = self._build()
        assert "goblin lunges" in user
        assert "What do you do?" in user

    def test_user_message_contains_respond_cue(self):
        _, user = self._build()
        assert "Respond now as Aldric" in user

    def test_relationships_included(self):
        system, _ = self._build(relationships={"Riven": "Mistrusts, but respects in combat."})
        assert "Riven" in system
        assert "Mistrusts" in system

    def test_memory_chunks_included(self):
        system, _ = self._build(memory_chunks=["Aldric once fought a dragon in Ironhold."])
        assert "RELEVANT MEMORY" in system
        assert "Ironhold" in system

    def test_memory_section_omitted_when_empty(self):
        system, _ = self._build(memory_chunks=[])
        assert "RELEVANT MEMORY" not in system

    def test_spell_slots_included(self):
        system, _ = self._build(spell_slots={"1": 2, "2": 1})
        assert "Spell slots" in system

    def test_active_conditions_included(self):
        system, _ = self._build(active_conditions=["poisoned", "prone"])
        assert "poisoned" in system
        assert "prone" in system

    def test_empty_transcript_fallback(self):
        _, user = self._build(transcript_lines=[])
        assert "quiet" in user.lower()

    def test_transcript_capped_at_30_lines(self):
        lines = [f"Unknown: line {i}" for i in range(50)]
        _, user = self._build(transcript_lines=lines)
        # Should contain recent lines, not all 50
        assert "line 49" in user
        assert "line 0" not in user

    def test_cross_avatar_note_included(self):
        system, _ = self._build(
            relationships={"Riven": "Wary."},
            cross_avatar_note="Riven just disagreed with the plan.",
        )
        assert "Riven just disagreed" in system


# ── LLM Router ────────────────────────────────────────────────────────────────

class TestLLMRouter:
    def test_combat_routes_to_ollama(self):
        from app.llm.router import select_route
        assert select_route("combat_turn") == "ollama"

    def test_casual_roleplay_routes_to_ollama(self):
        from app.llm.router import select_route
        assert select_route("casual_roleplay") == "ollama"

    def test_direct_question_routes_to_ollama(self):
        from app.llm.router import select_route
        assert select_route("direct_question") == "ollama"

    def test_emotional_beat_routes_to_claude(self):
        from app.llm.router import select_route
        assert select_route("emotional_beat") == "claude"

    def test_backstory_call_routes_to_claude(self):
        from app.llm.router import select_route
        assert select_route("backstory_call") == "claude"

    def test_npc_social_routes_to_claude(self):
        from app.llm.router import select_route
        assert select_route("npc_social") == "claude"

    def test_moral_dilemma_routes_to_claude(self):
        from app.llm.router import select_route
        assert select_route("moral_dilemma") == "claude"

    def test_keyword_escalation_backstory(self):
        from app.llm.router import select_route
        # "casual_roleplay" would normally be ollama, but "backstory" keyword escalates to claude
        result = select_route("casual_roleplay", recent_transcript="tell me about your backstory")
        assert result == "claude"

    def test_keyword_escalation_trauma(self):
        from app.llm.router import select_route
        result = select_route("combat_turn", recent_transcript="the trauma of that day")
        assert result == "claude"

    def test_keyword_escalation_family(self):
        from app.llm.router import select_route
        result = select_route("casual_roleplay", recent_transcript="what happened to your family?")
        assert result == "claude"

    def test_no_escalation_on_neutral_text(self):
        from app.llm.router import select_route
        result = select_route("casual_roleplay", recent_transcript="the goblin attacks the village")
        assert result == "ollama"

    def test_ollama_stub_when_unreachable(self):
        """Ollama call returns stub response when server is not running."""
        from app.llm.router import call_ollama
        result = call_ollama("System.", "User.", model="llama3.1:8b")
        # Should return an LLMResponse without crashing
        assert result.route in ("ollama", "stub")
        assert isinstance(result.text, str)
        assert isinstance(result.error, str)

    def test_claude_stub_when_no_api_key(self):
        """Claude call returns stub when no API key is configured."""
        from app.llm.router import call_claude
        import unittest.mock
        with unittest.mock.patch("app.llm.router.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            mock_settings.claude_model = "claude-haiku-4-5-20251001"
            result = call_claude("System.", "User.")
        assert result.route == "stub"
        assert result.error == "no_api_key"

    def test_call_llm_routes_correctly(self):
        """call_llm selects the right backend based on context_type."""
        from app.llm.router import call_llm
        import unittest.mock
        with unittest.mock.patch("app.llm.router.call_ollama") as mock_ollama, \
             unittest.mock.patch("app.llm.router.call_claude") as mock_claude:
            from app.llm.router import LLMResponse
            mock_ollama.return_value = LLMResponse(text="I attack.", route="ollama", model="llama3.1:8b")
            mock_claude.return_value = LLMResponse(text="I hesitate.", route="claude", model="claude-haiku")
            # Combat → Ollama
            call_llm("sys", "user", "combat_turn")
            mock_ollama.assert_called_once()
            mock_claude.assert_not_called()
            mock_ollama.reset_mock()
            # Emotional → Claude
            call_llm("sys", "user", "emotional_beat")
            mock_claude.assert_called_once()
            mock_ollama.assert_not_called()


# ── LLM Dispatcher ────────────────────────────────────────────────────────────

class TestLLMDispatcher:
    def _make_dispatcher(self, llm_text="I draw my sword and step forward."):
        """Build a dispatcher wired to mock TTS, output manager, presence layer."""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock, patch
        from app.llm.dispatcher import LLMDispatcher
        from app.audio.aec_gate import EchoGate

        messages = []

        async def broadcast(msg):
            messages.append(msg)

        tts = MagicMock()
        tts.synthesize.return_value = MagicMock(audio_bytes=b"RIFF" + b"\x00" * 100)

        output = MagicMock()
        output.enqueue = AsyncMock()

        presence = MagicMock()
        presence.play_holding_phrase = AsyncMock()

        context_engine = MagicMock()
        context_engine.on_avatar_spoke = MagicMock()

        dispatcher = LLMDispatcher(
            session_id=1,
            tts_engine=tts,
            output_manager=output,
            presence_layer=presence,
            context_engine=context_engine,
            broadcast_fn=broadcast,
        )
        dispatcher._avatar_profiles = {}

        return dispatcher, messages, tts, output, presence, context_engine, llm_text

    @pytest.mark.asyncio
    async def test_dispatch_plays_holding_phrase(self):
        from unittest.mock import patch
        from app.llm.dispatcher import DispatchRequest, LLMDispatcher
        dispatcher, messages, tts, output, presence, ce, llm_text = self._make_dispatcher()

        with patch("app.llm.dispatcher.call_llm") as mock_llm, \
             patch("app.llm.dispatcher._post_processor") as mock_proc, \
             patch("asyncio.sleep", return_value=None):
            from app.llm.router import LLMResponse
            from app.audio.response_post_processor import ProcessedResponse
            mock_llm.return_value = LLMResponse(text=llm_text, route="ollama", model="llama3.1:8b")
            mock_proc.process.return_value = ProcessedResponse(
                text=llm_text, emotion="default", delay_seconds=0.0, original=llm_text
            )

            req = DispatchRequest(
                session_id=1, avatar_id=1, avatar_name="Aldric",
                context_type="combat_turn", interrupt_score=0.8, priority=2,
            )
            await dispatcher.dispatch(req)

        presence.play_holding_phrase.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_calls_tts(self):
        from unittest.mock import patch
        from app.llm.dispatcher import DispatchRequest
        dispatcher, messages, tts, output, presence, ce, llm_text = self._make_dispatcher()

        with patch("app.llm.dispatcher.call_llm") as mock_llm, \
             patch("app.llm.dispatcher._post_processor") as mock_proc, \
             patch("asyncio.sleep", return_value=None):
            from app.llm.router import LLMResponse
            from app.audio.response_post_processor import ProcessedResponse
            mock_llm.return_value = LLMResponse(text=llm_text, route="ollama", model="llama3.1:8b")
            mock_proc.process.return_value = ProcessedResponse(
                text=llm_text, emotion="default", delay_seconds=0.0, original=llm_text
            )
            req = DispatchRequest(
                session_id=1, avatar_id=1, avatar_name="Aldric",
                context_type="combat_turn", interrupt_score=0.8, priority=2,
            )
            await dispatcher.dispatch(req)

        tts.synthesize.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_enqueues_audio(self):
        from unittest.mock import patch
        from app.llm.dispatcher import DispatchRequest
        dispatcher, messages, tts, output, presence, ce, llm_text = self._make_dispatcher()

        with patch("app.llm.dispatcher.call_llm") as mock_llm, \
             patch("app.llm.dispatcher._post_processor") as mock_proc, \
             patch("asyncio.sleep", return_value=None):
            from app.llm.router import LLMResponse
            from app.audio.response_post_processor import ProcessedResponse
            mock_llm.return_value = LLMResponse(text=llm_text, route="ollama", model="llama3.1:8b")
            mock_proc.process.return_value = ProcessedResponse(
                text=llm_text, emotion="default", delay_seconds=0.0, original=llm_text
            )
            req = DispatchRequest(
                session_id=1, avatar_id=1, avatar_name="Aldric",
                context_type="combat_turn", interrupt_score=0.8, priority=2,
            )
            await dispatcher.dispatch(req)

        output.enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_broadcasts_transcript_entry(self):
        from unittest.mock import patch
        from app.llm.dispatcher import DispatchRequest
        dispatcher, messages, tts, output, presence, ce, llm_text = self._make_dispatcher()

        with patch("app.llm.dispatcher.call_llm") as mock_llm, \
             patch("app.llm.dispatcher._post_processor") as mock_proc, \
             patch("asyncio.sleep", return_value=None):
            from app.llm.router import LLMResponse
            from app.audio.response_post_processor import ProcessedResponse
            mock_llm.return_value = LLMResponse(text=llm_text, route="ollama", model="llama3.1:8b")
            mock_proc.process.return_value = ProcessedResponse(
                text=llm_text, emotion="default", delay_seconds=0.0, original=llm_text
            )
            req = DispatchRequest(
                session_id=1, avatar_id=1, avatar_name="Aldric",
                context_type="combat_turn", interrupt_score=0.8, priority=2,
            )
            await dispatcher.dispatch(req)

        transcript_msgs = [m for m in messages if m.get("type") == "transcript"]
        assert len(transcript_msgs) == 1
        assert transcript_msgs[0]["entry"]["speaker"] == "Aldric"
        assert transcript_msgs[0]["entry"]["text"] == llm_text

    @pytest.mark.asyncio
    async def test_dispatch_updates_cooldown(self):
        from unittest.mock import patch
        from app.llm.dispatcher import DispatchRequest
        dispatcher, messages, tts, output, presence, ce, llm_text = self._make_dispatcher()

        with patch("app.llm.dispatcher.call_llm") as mock_llm, \
             patch("app.llm.dispatcher._post_processor") as mock_proc, \
             patch("asyncio.sleep", return_value=None):
            from app.llm.router import LLMResponse
            from app.audio.response_post_processor import ProcessedResponse
            mock_llm.return_value = LLMResponse(text=llm_text, route="ollama", model="llama3.1:8b")
            mock_proc.process.return_value = ProcessedResponse(
                text=llm_text, emotion="default", delay_seconds=0.0, original=llm_text
            )
            req = DispatchRequest(
                session_id=1, avatar_id=1, avatar_name="Aldric",
                context_type="combat_turn", interrupt_score=0.8, priority=2,
            )
            await dispatcher.dispatch(req)

        ce.on_avatar_spoke.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_dispatch_skips_on_empty_llm_response(self):
        """If LLM returns empty string, TTS should not be called."""
        from unittest.mock import patch
        from app.llm.dispatcher import DispatchRequest
        dispatcher, messages, tts, output, presence, ce, llm_text = self._make_dispatcher()

        with patch("app.llm.dispatcher.call_llm") as mock_llm, \
             patch("asyncio.sleep", return_value=None):
            from app.llm.router import LLMResponse
            mock_llm.return_value = LLMResponse(text="", route="stub", model="llama3.1:8b", error="timeout")
            req = DispatchRequest(
                session_id=1, avatar_id=1, avatar_name="Aldric",
                context_type="combat_turn", interrupt_score=0.8, priority=2,
            )
            await dispatcher.dispatch(req)

        tts.synthesize.assert_not_called()
        output.enqueue.assert_not_awaited()
