from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path

# Resolve .env relative to this file's location (backend/app/), going up to project root
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    # ── Server ────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:4173"
    debug_mode: bool = False

    # ── Observability ─────────────────────────────────────────────────────
    # Set LOG_LEVEL=DEBUG in .env to see full LLM prompts, VAD chunks, etc.
    # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    log_level: str = "INFO"

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/campaign.db"

    # ── AI / LLM ──────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 256
    gpt4o_model: str = "gpt-4o"
    gpt4o_max_tokens: int = 200
    gpt4o_temperature: float = 0.85

    # Kept for backward compat during migration — no longer used for routing
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_s: float = 30.0

    # ── STT — Deepgram ────────────────────────────────────────────────────
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_endpointing_ms: int = 800   # ms of silence = end of utterance

    # Kept for backward compat — faster-whisper/silero no longer primary path
    sample_rate: int = 16000
    chunk_ms: int = 30
    vad_threshold: float = 0.30
    vad_trailing_silence_ms: int = 1500
    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_beam_size: int = 5
    whisper_no_speech_threshold: float = 0.80
    whisper_log_prob_threshold: float = -2.0

    # ── TTS — ElevenLabs ──────────────────────────────────────────────────
    elevenlabs_api_key: str = ""
    elevenlabs_model_quality: str = "eleven_v3"          # for emotional/story moments
    elevenlabs_model_fast: str = "eleven_flash_v2_5"     # for combat/quick reactions

    # ── Audio Input ───────────────────────────────────────────────────────
    mic_device_index: int = 0
    aec_decay_ms: int = 200    # ms to gate mic after TTS ends

    # ── Trigger Timing ────────────────────────────────────────────────────
    silence_gap_trigger: float = 4.0    # seconds of silence before passive response
    self_cooldown_seconds: float = 12.0 # min gap before same avatar speaks again
    avatar_cooldown_seconds: float = 3.0  # min gap between any two avatars
    interrupt_confidence_threshold: float = 0.6  # score required for LLM response

    # ── Naturalism ────────────────────────────────────────────────────────
    response_jitter_min: float = 1.5  # min seconds before response plays
    response_jitter_max: float = 4.0  # max seconds before response plays
    backchannel_min_gap: float = 8.0  # min seconds between backchannels
    backchannel_chance: float = 0.35  # probability of backchannel when eligible

    # ── Avatar-to-avatar ──────────────────────────────────────────────────
    max_avatar_chain_depth: int = 3
    avatar_speech_cooldown_s: float = 8.0

    # ── Character traits ──────────────────────────────────────────────────
    trait_decay_weekly_pct: float = 0.10
    trait_manifestation_base_probability: float = 0.30

    # ── Prompt architecture ───────────────────────────────────────────────
    actor_instructions_offset: int = 3   # inject actor reminder N messages from history end

    # ── Memory ────────────────────────────────────────────────────────────
    memory_top_k: int = 5
    transcript_context_lines: int = 30
    mid_session_compress_mins: int = 60
    summary_method: str = "balanced"     # "facts" | "short" | "balanced" | "long"
    summary_previous_sessions: int = 6   # how many prior summaries to include as context

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def chunk_samples(self) -> int:
        """Number of audio samples per VAD chunk."""
        return int(self.sample_rate * self.chunk_ms / 1000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
