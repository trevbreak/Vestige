"""
Settings API — Phase 7.

Exposes runtime-tunable config values for the DM settings panel.
Uses the shared Settings singleton; changes take effect immediately
without restart (fields are re-read each time from the singleton).

Note: changes are in-memory only — they reset on server restart.
A separate .env write mechanism can be added later if persistence is needed.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.config import get_settings

router = APIRouter(prefix="/settings", tags=["settings"])


# ── Schema ────────────────────────────────────────────────────────────────────

class RuntimeSettings(BaseModel):
    """Settings that can be tuned at runtime without restart."""

    # Credentials (write-only; never echoed back)
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None

    # LLM routing
    claude_model: Optional[str] = None
    claude_max_tokens: Optional[int] = Field(None, ge=64, le=4096)
    gpt4o_model: Optional[str] = None
    gpt4o_max_tokens: Optional[int] = Field(None, ge=64, le=1024)
    gpt4o_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)

    # STT
    deepgram_endpointing_ms: Optional[int] = Field(None, ge=200, le=3000)

    # TTS
    elevenlabs_model_quality: Optional[str] = None
    elevenlabs_model_fast: Optional[str] = None

    # Audio input
    aec_decay_ms: Optional[int] = Field(None, ge=0, le=2000)

    # Trigger timing
    silence_gap_trigger: Optional[float] = Field(None, ge=1.0, le=30.0)
    self_cooldown_seconds: Optional[float] = Field(None, ge=1.0, le=120.0)
    avatar_cooldown_seconds: Optional[float] = Field(None, ge=0.5, le=30.0)
    interrupt_confidence_threshold: Optional[float] = Field(None, ge=0.1, le=1.0)

    # Naturalism
    response_jitter_min: Optional[float] = Field(None, ge=0.0, le=10.0)
    response_jitter_max: Optional[float] = Field(None, ge=0.0, le=20.0)
    backchannel_min_gap: Optional[float] = Field(None, ge=2.0, le=60.0)
    backchannel_chance: Optional[float] = Field(None, ge=0.0, le=1.0)

    # Audio device
    mic_device_index: Optional[int] = Field(None, ge=0)

    # Avatar-to-avatar
    max_avatar_chain_depth: Optional[int] = Field(None, ge=1, le=10)
    avatar_speech_cooldown_s: Optional[float] = Field(None, ge=1.0, le=60.0)

    # Character traits
    trait_decay_weekly_pct: Optional[float] = Field(None, ge=0.0, le=1.0)
    trait_manifestation_base_probability: Optional[float] = Field(None, ge=0.0, le=1.0)

    # Prompt architecture
    actor_instructions_offset: Optional[int] = Field(None, ge=0, le=10)

    # Memory
    memory_top_k: Optional[int] = Field(None, ge=1, le=20)
    transcript_context_lines: Optional[int] = Field(None, ge=5, le=100)
    summary_method: Optional[str] = None
    summary_previous_sessions: Optional[int] = Field(None, ge=0, le=20)


class SettingsOut(BaseModel):
    """All currently active runtime settings."""
    # Credentials (masked — only shows whether set)
    anthropic_api_key_set: bool
    openai_api_key_set: bool
    deepgram_api_key_set: bool
    elevenlabs_api_key_set: bool
    # LLM
    claude_model: str
    claude_max_tokens: int
    gpt4o_model: str
    gpt4o_max_tokens: int
    gpt4o_temperature: float
    # STT
    deepgram_endpointing_ms: int
    # TTS
    elevenlabs_model_quality: str
    elevenlabs_model_fast: str
    # Audio
    aec_decay_ms: int
    # Timing
    silence_gap_trigger: float
    self_cooldown_seconds: float
    avatar_cooldown_seconds: float
    interrupt_confidence_threshold: float
    # Naturalism
    response_jitter_min: float
    response_jitter_max: float
    backchannel_min_gap: float
    backchannel_chance: float
    # Audio device
    mic_device_index: int
    # Avatar-to-avatar
    max_avatar_chain_depth: int
    avatar_speech_cooldown_s: float
    # Character traits
    trait_decay_weekly_pct: float
    trait_manifestation_base_probability: float
    # Prompt architecture
    actor_instructions_offset: int
    # Memory
    memory_top_k: int
    transcript_context_lines: int
    summary_method: str
    summary_previous_sessions: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=SettingsOut)
def get_current_settings():
    """Return all currently active runtime-tunable settings."""
    s = get_settings()
    return SettingsOut(
        anthropic_api_key_set=bool(s.anthropic_api_key),
        openai_api_key_set=bool(s.openai_api_key),
        deepgram_api_key_set=bool(s.deepgram_api_key),
        elevenlabs_api_key_set=bool(s.elevenlabs_api_key),
        claude_model=s.claude_model,
        claude_max_tokens=s.claude_max_tokens,
        gpt4o_model=s.gpt4o_model,
        gpt4o_max_tokens=s.gpt4o_max_tokens,
        gpt4o_temperature=s.gpt4o_temperature,
        deepgram_endpointing_ms=s.deepgram_endpointing_ms,
        elevenlabs_model_quality=s.elevenlabs_model_quality,
        elevenlabs_model_fast=s.elevenlabs_model_fast,
        aec_decay_ms=s.aec_decay_ms,
        silence_gap_trigger=s.silence_gap_trigger,
        self_cooldown_seconds=s.self_cooldown_seconds,
        avatar_cooldown_seconds=s.avatar_cooldown_seconds,
        interrupt_confidence_threshold=s.interrupt_confidence_threshold,
        response_jitter_min=s.response_jitter_min,
        response_jitter_max=s.response_jitter_max,
        backchannel_min_gap=s.backchannel_min_gap,
        backchannel_chance=s.backchannel_chance,
        mic_device_index=s.mic_device_index,
        max_avatar_chain_depth=s.max_avatar_chain_depth,
        avatar_speech_cooldown_s=s.avatar_speech_cooldown_s,
        trait_decay_weekly_pct=s.trait_decay_weekly_pct,
        trait_manifestation_base_probability=s.trait_manifestation_base_probability,
        actor_instructions_offset=s.actor_instructions_offset,
        memory_top_k=s.memory_top_k,
        transcript_context_lines=s.transcript_context_lines,
        summary_method=s.summary_method,
        summary_previous_sessions=s.summary_previous_sessions,
    )


@router.patch("", response_model=SettingsOut)
def update_settings(body: RuntimeSettings):
    """
    Update one or more runtime settings.
    Changes take effect immediately; resets on server restart.
    """
    s = get_settings()

    # Validate jitter ordering
    jitter_min = body.response_jitter_min if body.response_jitter_min is not None else s.response_jitter_min
    jitter_max = body.response_jitter_max if body.response_jitter_max is not None else s.response_jitter_max
    if jitter_min > jitter_max:
        raise HTTPException(400, "response_jitter_min must be ≤ response_jitter_max")

    if body.summary_method is not None and body.summary_method not in ("facts", "short", "balanced", "long"):
        raise HTTPException(400, "summary_method must be one of: facts, short, balanced, long")

    _VALID_CLAUDE_MODELS = {
        "claude-sonnet-4-6", "claude-opus-4-7",
        "claude-haiku-4-5-20251001", "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
    }
    _VALID_GPT4O_MODELS = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo"}
    _VALID_ELEVENLABS_MODELS = {
        "eleven_v3", "eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2",
    }
    if body.claude_model is not None and body.claude_model not in _VALID_CLAUDE_MODELS:
        raise HTTPException(400, f"claude_model must be one of: {sorted(_VALID_CLAUDE_MODELS)}")
    if body.gpt4o_model is not None and body.gpt4o_model not in _VALID_GPT4O_MODELS:
        raise HTTPException(400, f"gpt4o_model must be one of: {sorted(_VALID_GPT4O_MODELS)}")
    if body.elevenlabs_model_quality is not None and body.elevenlabs_model_quality not in _VALID_ELEVENLABS_MODELS:
        raise HTTPException(400, f"elevenlabs_model_quality must be one of: {sorted(_VALID_ELEVENLABS_MODELS)}")
    if body.elevenlabs_model_fast is not None and body.elevenlabs_model_fast not in _VALID_ELEVENLABS_MODELS:
        raise HTTPException(400, f"elevenlabs_model_fast must be one of: {sorted(_VALID_ELEVENLABS_MODELS)}")

    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        if hasattr(s, key):
            object.__setattr__(s, key, val)

    # Note: llm/router.py now calls get_settings() fresh on each invocation,
    # so no module-level reference needs patching here.

    return get_current_settings()
