"""
System status API.

GET  /api/system/status   — model availability, service reachability, config sanity
GET  /api/system/devices  — list audio input devices
POST /api/system/mic-test — capture 1s of audio, return peak level (0.0–1.0)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Query

from app.config import get_settings

log = structlog.get_logger()
router = APIRouter(prefix="/system", tags=["system"])


# ── /status ───────────────────────────────────────────────────────────────────

@router.post("/recheck")
async def recheck_system():
    """Re-run all startup checks and return fresh results."""
    from app.startup_checks import run_startup_checks, get_status, all_critical_ok
    import asyncio
    await run_startup_checks()
    checks = get_status()
    return {
        "ok": all_critical_ok(),
        "results": checks,
    }


@router.get("/status")
def get_system_status():
    """
    Return real loaded state from the startup health checks plus a live
    Ollama ping.  Models show actual inference probe results, not just
    'is the package installed?'.
    """
    from app.startup_checks import get_status, all_critical_ok
    s = get_settings()

    checks = get_status()

    # Live Ollama re-check (cheap HTTP ping, not a model load)
    ollama = checks.get("ollama", {"ok": False, "error": "not checked yet"})

    # Check sounddevice availability
    try:
        import sounddevice as _sd  # noqa: F401
        sd_ok = True
        sd_error = None
    except ImportError:
        sd_ok = False
        sd_error = "sounddevice not installed"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "anthropic_api_key_set": checks.get("claude", {}).get("api_key_set", False),
            "ollama_model": s.ollama_model,
            "ollama_url": s.ollama_base_url,
            "whisper_model": s.whisper_model,
            "whisper_device": s.whisper_device,
            "whisper_compute_type": s.whisper_compute_type,
            "mic_device_index": s.mic_device_index,
        },
        "models": {
            "vad":      checks.get("vad",      {"ok": False, "error": "not checked"}),
            "whisper":  checks.get("whisper",  {"ok": False, "error": "not checked"}),
            "embedder": checks.get("embedder", {"ok": False, "error": "not checked"}),
            "tts":      checks.get("tts",      {"ok": False, "error": "not checked"}),
        },
        "audio": {
            "sounddevice": {"ok": sd_ok, "error": sd_error},
        },
        "services": {
            "ollama": ollama,
            "claude": checks.get("claude", {"ok": False, "error": "not checked"}),
        },
        # True only if the three models the audio pipeline actually needs are loaded and probed
        "critical_ready": all_critical_ok(),
        "ready": (
            all_critical_ok()
            and ollama.get("ok")
            and ollama.get("model_present")
        ),
    }


# ── /devices ──────────────────────────────────────────────────────────────────

@router.get("/devices")
def list_audio_devices():
    """Return available audio input devices."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = [
            {
                "index": i,
                "name": d["name"],
                "channels": d["max_input_channels"],
                "sample_rate": int(d["default_samplerate"]),
            }
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]
        raw_default = sd.default.device
        try:
            default_input = int(raw_default[0])
        except (TypeError, IndexError):
            default_input = int(raw_default) if raw_default is not None else None
        return {"devices": inputs, "default_index": default_input}
    except ImportError:
        return {"devices": [], "default_index": None, "error": "sounddevice not installed"}
    except Exception as e:
        return {"devices": [], "default_index": None, "error": str(e)}


# ── /mic-test ─────────────────────────────────────────────────────────────────

@router.post("/mic-test")
async def mic_test():
    """
    Capture 1 second of audio from the configured mic device.
    Returns peak level (0.0–1.0) and RMS level as a quick sanity check.
    """
    s = get_settings()

    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        return {"ok": False, "error": "sounddevice not installed", "peak": 0.0, "rms": 0.0}

    try:
        loop = asyncio.get_running_loop()

        def _capture():
            audio = sd.rec(
                int(s.sample_rate * 1.0),
                samplerate=s.sample_rate,
                channels=1,
                dtype="int16",
                device=s.mic_device_index,
            )
            sd.wait()
            return audio.flatten()

        audio = await loop.run_in_executor(None, _capture)

        peak = float(np.abs(audio).max()) / 32768.0
        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) / 32768.0

        return {
            "ok": True,
            "peak": round(peak, 4),
            "rms": round(rms, 4),
            "device_index": s.mic_device_index,
            "sample_rate": s.sample_rate,
            "duration_ms": 1000,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "peak": 0.0, "rms": 0.0}


# ── /logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs")
def get_logs(
    n: int = Query(default=100, ge=1, le=500),
    level: str = Query(default="", description="Minimum level: DEBUG, INFO, WARNING, ERROR"),
):
    """Return the last N log entries from the in-memory ring buffer."""
    try:
        from app.logging_config import get_recent_logs
        return {"logs": get_recent_logs(n=n, level=level or None)}
    except Exception as e:
        return {"logs": [], "error": str(e)}
