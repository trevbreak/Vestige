"""
LLM Response Dispatcher.

The end-to-end orchestrator for one avatar response cycle:

  1. Build holding phrase → play immediately (presence layer)
  2. Assemble AvatarContext from DB + pipeline state
  3. Build prompt (system + user)
  4. Call LLM in thread pool (non-blocking)
  5. Post-process the response
  6. Apply jitter delay
  7. Synthesize TTS
  8. Enqueue audio in output manager
  9. Update avatar cooldown in context engine

Called by AudioPipeline._flush_buffer when context_engine.evaluate() fires.
"""

from __future__ import annotations

import asyncio
import time
import structlog
from dataclasses import dataclass

from app.config import get_settings
from app.llm.prompt_builder import PromptBuilder, AvatarContext
from app.llm.router import call_llm, LLMResponse
from app.audio.response_post_processor import ResponsePostProcessor, ProcessedResponse

log = structlog.get_logger()
settings = get_settings()

_prompt_builder = PromptBuilder()
_post_processor = ResponsePostProcessor()


@dataclass
class DispatchRequest:
    """Everything the dispatcher needs to generate one avatar response."""
    session_id: int
    avatar_id: int
    avatar_name: str
    context_type: str
    interrupt_score: float
    priority: int

    # Avatar DB fields (flat — no ORM access inside dispatcher)
    race: str = "Human"
    char_class: str = "Fighter"
    level: int = 1
    alignment: str = ""
    background: str = ""
    player_name: str = ""
    personality_traits: str = ""
    ideals: str = ""
    bonds: str = ""
    flaws: str = ""
    sentence_style: str = ""
    verbal_tics: str = ""
    never_say: str = ""
    hit_points_current: int = 10
    hit_points_max: int = 10
    spell_slots: dict = None
    active_conditions: list = None
    relationships: dict = None

    # Current session context
    transcript_lines: list[str] = None   # ["Speaker: text", ...]
    memory_chunks: list[str] = None      # Phase 5: retrieved memory
    available_actions_text: str = ""     # Phase 6: combat action block
    cross_avatar_note: str = ""

    def __post_init__(self):
        if self.spell_slots is None:
            self.spell_slots = {}
        if self.active_conditions is None:
            self.active_conditions = []
        if self.relationships is None:
            self.relationships = {}
        if self.transcript_lines is None:
            self.transcript_lines = []
        if self.memory_chunks is None:
            self.memory_chunks = []


class LLMDispatcher:
    """
    Per-session dispatcher. One instance per running session.

    Holds references to the shared presence layer, output manager,
    TTS engine, and context engine for this session.
    """

    def __init__(
        self,
        session_id: int,
        tts_engine,           # TTSEngine
        output_manager,       # AudioOutputManager
        presence_layer,       # PresenceLayer
        context_engine,       # ContextEngine (for cooldown updates)
        broadcast_fn,         # async (dict) → None
    ):
        self.session_id = session_id
        self._tts = tts_engine
        self._output = output_manager
        self._presence = presence_layer
        self._context_engine = context_engine
        self._broadcast = broadcast_fn

    async def dispatch(self, req: DispatchRequest) -> None:
        """
        Handle one full response cycle for one avatar.
        Safe to call concurrently for different avatars.
        """
        log.info(
            "dispatcher.dispatch_start",
            avatar=req.avatar_name,
            context=req.context_type,
            priority=req.priority,
        )

        # 1. Play holding phrase immediately (before LLM call)
        await self._presence.play_holding_phrase(
            avatar_id=req.avatar_id,
            avatar_name=req.avatar_name,
            context_type=req.context_type,
            tts_engine=self._tts,
        )

        # 2. Build prompt
        ctx = AvatarContext(
            name=req.avatar_name,
            race=req.race,
            char_class=req.char_class,
            level=req.level,
            alignment=req.alignment,
            background=req.background,
            player_name=req.player_name,
            personality_traits=req.personality_traits,
            ideals=req.ideals,
            bonds=req.bonds,
            flaws=req.flaws,
            sentence_style=req.sentence_style,
            verbal_tics=req.verbal_tics,
            never_say=req.never_say,
            hit_points_current=req.hit_points_current,
            hit_points_max=req.hit_points_max,
            spell_slots=req.spell_slots,
            active_conditions=req.active_conditions,
            relationships=req.relationships,
            memory_chunks=req.memory_chunks,
            transcript_lines=req.transcript_lines,
            context_type=req.context_type,
            available_actions_text=req.available_actions_text,
            cross_avatar_note=req.cross_avatar_note,
        )
        system_prompt, user_message = _prompt_builder.build(ctx)

        # 3. LLM call in thread pool
        recent_text = " ".join(req.transcript_lines[-5:]) if req.transcript_lines else ""
        loop = asyncio.get_running_loop()
        llm_result: LLMResponse = await loop.run_in_executor(
            None,
            lambda: call_llm(system_prompt, user_message, req.context_type, recent_text),
        )

        if not llm_result.text:
            log.warning(
                "dispatcher.llm_empty",
                avatar=req.avatar_name,
                route=llm_result.route,
                error=llm_result.error,
            )
            return

        # 4. Post-process
        processed: ProcessedResponse = _post_processor.process(
            raw_text=llm_result.text,
            context_type=req.context_type,
            avatar_name=req.avatar_name,
        )

        log.info(
            "dispatcher.llm_done",
            avatar=req.avatar_name,
            route=llm_result.route,
            latency_ms=round(llm_result.latency_ms),
            text_preview=processed.text[:60],
            emotion=processed.emotion,
            delay_s=round(processed.delay_seconds, 1),
        )

        # 5. Jitter delay (simulate natural thinking time)
        await asyncio.sleep(processed.delay_seconds)

        # 6. TTS synthesis in thread pool
        tts_result = await loop.run_in_executor(
            None,
            lambda: self._tts.synthesize(
                text=processed.text,
                avatar_id=req.avatar_id,
                emotion=processed.emotion,
            ),
        )

        # 7. Broadcast transcript entry for the avatar's speech
        await self._broadcast({
            "type": "transcript",
            "session_id": self.session_id,
            "entry": {
                "session_id": self.session_id,
                "speaker": req.avatar_name,
                "speaker_type": "avatar",
                "text": processed.text,
                "utterance_type": "speech",
                "confidence": 1.0,
                "audio_start_ms": 0,
                "audio_end_ms": 0,
                "interrupt_score": req.interrupt_score,
                "context_type": req.context_type,
                "llm_route": llm_result.route,
            },
        })

        # 8. Enqueue audio
        await self._output.enqueue(
            avatar_id=req.avatar_id,
            avatar_name=req.avatar_name,
            wav_bytes=tts_result.audio_bytes,
            priority=req.priority,
            volume=1.0,
            utterance_type="speech",
        )

        # 9. Mark avatar as having spoken (updates context engine cooldowns)
        self._context_engine.on_avatar_spoke(req.avatar_id)

        # 10. Add avatar's response to the rolling transcript context
        pipeline = getattr(self, "_pipeline", None)
        if pipeline is not None:
            pipeline.add_transcript_line(req.avatar_name, processed.text)

        log.info(
            "dispatcher.dispatch_done",
            avatar=req.avatar_name,
            bytes=len(tts_result.audio_bytes),
        )
