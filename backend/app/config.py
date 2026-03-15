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
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_s: float = 30.0
    claude_model: str = "claude-haiku-4-5-20251001"
    claude_max_tokens: int = 256

    # ── Audio Input ───────────────────────────────────────────────────────
    mic_device_index: int = 0
    sample_rate: int = 16000        # Hz — required by silero-vad and faster-whisper
    chunk_ms: int = 30              # VAD chunk size in ms (silero needs 30ms @ 16 kHz)
    vad_threshold: float = 0.30          # Silero VAD sensitivity (0.0–1.0)
    vad_trailing_silence_ms: int = 1500  # ms of silence required before flushing speech buffer
    aec_decay_ms: int = 200              # ms to gate mic after TTS ends
    whisper_model: str = "large-v3"      # faster-whisper model size (requires restart to change)
    whisper_device: str = "cuda"          # "cuda" | "cpu" (requires restart to change)
    whisper_compute_type: str = "float16" # "float16" | "int8" | "float32" (requires restart to change)
    whisper_beam_size: int = 5            # beam search width — higher = more accurate, slower
    whisper_no_speech_threshold: float = 0.80  # drop segments where no_speech_prob exceeds this
    whisper_log_prob_threshold: float = -2.0   # drop segments below this avg log-prob

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

    # ── Memory ────────────────────────────────────────────────────────────
    memory_top_k: int = 5
    transcript_context_lines: int = 30
    mid_session_compress_mins: int = 60

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
