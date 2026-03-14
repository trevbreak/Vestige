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

    # Credentials
    anthropic_api_key: Optional[str] = None  # write-only; never echoed back

    # LLM routing
    ollama_model: Optional[str] = None
    claude_model: Optional[str] = None
    claude_max_tokens: Optional[int] = Field(None, ge=64, le=4096)
    ollama_timeout_s: Optional[float] = Field(None, ge=5.0, le=300.0)

    # Audio input
    vad_threshold: Optional[float] = Field(None, ge=0.05, le=0.99)
    aec_decay_ms: Optional[int] = Field(None, ge=0, le=2000)
    whisper_no_speech_threshold: Optional[float] = Field(None, ge=0.1, le=1.0)
    whisper_log_prob_threshold: Optional[float] = Field(None, ge=-5.0, le=0.0)

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

    # Memory
    memory_top_k: Optional[int] = Field(None, ge=1, le=20)
    transcript_context_lines: Optional[int] = Field(None, ge=5, le=100)


class SettingsOut(BaseModel):
    """All currently active runtime settings."""
    # Credentials (masked)
    anthropic_api_key_set: bool
    # LLM
    ollama_model: str
    claude_model: str
    claude_max_tokens: int
    ollama_timeout_s: float
    # Audio
    vad_threshold: float
    aec_decay_ms: int
    whisper_no_speech_threshold: float
    whisper_log_prob_threshold: float
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
    # Memory
    memory_top_k: int
    transcript_context_lines: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=SettingsOut)
def get_current_settings():
    """Return all currently active runtime-tunable settings."""
    s = get_settings()
    return SettingsOut(
        anthropic_api_key_set=bool(s.anthropic_api_key and s.anthropic_api_key != "sk-ant-..."),
        ollama_model=s.ollama_model,
        claude_model=s.claude_model,
        claude_max_tokens=s.claude_max_tokens,
        ollama_timeout_s=s.ollama_timeout_s,
        vad_threshold=s.vad_threshold,
        aec_decay_ms=s.aec_decay_ms,
        whisper_no_speech_threshold=s.whisper_no_speech_threshold,
        whisper_log_prob_threshold=s.whisper_log_prob_threshold,
        silence_gap_trigger=s.silence_gap_trigger,
        self_cooldown_seconds=s.self_cooldown_seconds,
        avatar_cooldown_seconds=s.avatar_cooldown_seconds,
        interrupt_confidence_threshold=s.interrupt_confidence_threshold,
        response_jitter_min=s.response_jitter_min,
        response_jitter_max=s.response_jitter_max,
        backchannel_min_gap=s.backchannel_min_gap,
        backchannel_chance=s.backchannel_chance,
        mic_device_index=s.mic_device_index,
        memory_top_k=s.memory_top_k,
        transcript_context_lines=s.transcript_context_lines,
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

    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        if hasattr(s, key):
            object.__setattr__(s, key, val)

    # Note: llm/router.py now calls get_settings() fresh on each invocation,
    # so no module-level reference needs patching here.

    return get_current_settings()
