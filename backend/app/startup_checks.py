"""
Startup model health checks.

Eagerly loads every AI model at server boot and runs a lightweight
inference probe on each one.  Results are stored in a module-level
registry so the /api/system/status endpoint can report real loaded
state rather than "is the package installed?".

Startup sequence
────────────────
1. VAD      — load silero, run one 30 ms zero chunk
2. Whisper  — load faster-whisper, transcribe 0.1 s of silence
3. Embedder — load sentence-transformers, embed one word
4. TTS      — load XTTS-v2 (optional); synthesise nothing, just check load
5. Ollama   — HTTP ping + model list
6. Claude   — validate API key is set (no inference call to avoid cost)

Any critical failure (VAD, Whisper, Embedder) logs ERROR and is surfaced
in the status endpoint.  TTS and LLM failures are WARNING only — the app
runs without them.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
import urllib.error
import structlog
import numpy as np

log = structlog.get_logger()

# ── Global registry  ──────────────────────────────────────────────────────────
# Keys are component names; values are dicts with at least:
#   ok: bool, loaded: bool, error: str | None, latency_ms: float
_results: dict[str, dict] = {}


def get_status() -> dict[str, dict]:
    """Return a copy of the last check results."""
    return dict(_results)


def all_critical_ok() -> bool:
    """True only if VAD, Whisper, and Embedder all loaded and probed OK."""
    critical = ("vad", "whisper", "embedder")
    return all(_results.get(c, {}).get("ok") for c in critical)


# ── Individual checks  ────────────────────────────────────────────────────────

def _check_vad() -> dict:
    t0 = time.monotonic()
    try:
        import torch
        from silero_vad import load_silero_vad
        model = load_silero_vad()
        # Probe: one silent 512-sample chunk at 16 kHz
        # silero requires sr / chunk_len <= 31.25, i.e. chunk >= 512 samples at 16 kHz
        chunk = torch.zeros(512, dtype=torch.float32)
        with torch.no_grad():
            prob = model(chunk, 16000).item()
        ms = round((time.monotonic() - t0) * 1000)
        log.info("startup.vad_ok", prob=round(prob, 4), latency_ms=ms)
        return {"ok": True, "loaded": True, "probe_prob": round(prob, 4), "latency_ms": ms}
    except ImportError:
        ms = round((time.monotonic() - t0) * 1000)
        log.error("startup.vad_missing", note="silero-vad not installed")
        return {"ok": False, "loaded": False, "error": "silero-vad not installed", "latency_ms": ms}
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000)
        log.error("startup.vad_failed", error=str(e))
        return {"ok": False, "loaded": False, "error": str(e), "latency_ms": ms}


def _check_whisper() -> dict:
    from app.config import get_settings
    from app.audio.transcriber import transcriber
    s = get_settings()
    t0 = time.monotonic()

    # Load via the singleton — this is the only place WhisperModel(...) is ever called.
    # AudioPipeline reuses this same instance, so CUDA is initialised exactly once.
    ok = transcriber.load(
        model_size=s.whisper_model,
        device=s.whisper_device,
        compute_type=s.whisper_compute_type,
    )
    if not ok:
        ms = round((time.monotonic() - t0) * 1000)
        err = "load failed — check logs for details"
        return {"ok": False, "loaded": False, "error": err,
                "model": s.whisper_model, "device": s.whisper_device,
                "compute_type": s.whisper_compute_type, "latency_ms": ms}

    # Probe: transcribe 0.1 s of silence through the singleton
    try:
        silence = np.zeros(1600, dtype=np.int16)  # int16 as pipeline sends
        transcriber.transcribe(silence, sample_rate=16000)
        ms = round((time.monotonic() - t0) * 1000)
        log.info("startup.whisper_ok", model=s.whisper_model,
                 device=s.whisper_device, compute_type=s.whisper_compute_type,
                 latency_ms=ms)
        return {
            "ok": True, "loaded": True,
            "model": s.whisper_model, "device": s.whisper_device,
            "compute_type": s.whisper_compute_type,
            "latency_ms": ms,
        }
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000)
        log.error("startup.whisper_probe_failed", error=str(e))
        return {"ok": False, "loaded": True, "error": str(e),
                "model": s.whisper_model, "device": s.whisper_device,
                "compute_type": s.whisper_compute_type, "latency_ms": ms}


def _check_embedder() -> dict:
    t0 = time.monotonic()
    try:
        import torch
        from sentence_transformers import SentenceTransformer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        # Probe: embed one word
        vec = model.encode("hello", normalize_embeddings=True)
        dim = len(vec)
        ms = round((time.monotonic() - t0) * 1000)
        log.info("startup.embedder_ok", dim=dim, device=device, latency_ms=ms)
        return {"ok": True, "loaded": True, "dim": dim, "device": device, "latency_ms": ms}
    except ImportError:
        ms = round((time.monotonic() - t0) * 1000)
        log.error("startup.embedder_missing", note="sentence-transformers not installed")
        return {"ok": False, "loaded": False, "error": "sentence-transformers not installed", "latency_ms": ms}
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000)
        log.error("startup.embedder_failed", error=str(e))
        return {"ok": False, "loaded": False, "error": str(e), "latency_ms": ms}


def _check_tts() -> dict:
    """
    Load XTTS-v2 via the module-level singleton.  Optional — WARNING only if
    unavailable.  Must run BEFORE Whisper so XTTS claims its CUDA allocations
    first; loading order affects CTranslate2 CUDA stream assignment.
    """
    from app.audio.tts import tts_engine
    t0 = time.monotonic()
    ok = tts_engine.load(device="cuda")
    ms = round((time.monotonic() - t0) * 1000)
    if ok:
        log.info("startup.tts_ok", latency_ms=ms)
        return {"ok": True, "loaded": True, "latency_ms": ms}
    else:
        log.warning("startup.tts_failed_or_missing",
                    note="TTS unavailable — avatars will be silent")
        return {"ok": False, "loaded": False,
                "error": "TTS load failed — check logs", "latency_ms": ms}


def _check_ollama() -> dict:
    from app.config import get_settings
    s = get_settings()
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(f"{s.ollama_base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = json.loads(resp.read())
        models = [m["name"] for m in body.get("models", [])]
        configured_present = any(s.ollama_model in m for m in models)
        ms = round((time.monotonic() - t0) * 1000)
        if configured_present:
            log.info("startup.ollama_ok", model=s.ollama_model, available_models=models, latency_ms=ms)
        else:
            log.warning("startup.ollama_model_missing",
                        configured=s.ollama_model, available=models,
                        note=f"Run: ollama pull {s.ollama_model}")
        return {
            "ok": True,
            "model_present": configured_present,
            "configured_model": s.ollama_model,
            "available_models": models,
            "latency_ms": ms,
        }
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000)
        log.warning("startup.ollama_unreachable", url=s.ollama_base_url, error=str(e))
        return {"ok": False, "model_present": False, "error": str(e), "latency_ms": ms}


def _check_claude() -> dict:
    from app.config import get_settings
    s = get_settings()
    t0 = time.monotonic()
    try:
        import anthropic  # noqa: F401
        key_set = bool(s.anthropic_api_key and not s.anthropic_api_key.startswith("sk-ant-..."))
        ms = round((time.monotonic() - t0) * 1000)
        if key_set:
            log.info("startup.claude_ok", model=s.claude_model, latency_ms=ms)
        else:
            log.warning("startup.claude_no_key", note="ANTHROPIC_API_KEY not set — Claude routing will stub")
        return {"ok": key_set, "sdk_installed": True, "api_key_set": key_set,
                "model": s.claude_model, "latency_ms": ms}
    except ImportError:
        ms = round((time.monotonic() - t0) * 1000)
        log.warning("startup.claude_sdk_missing", note="anthropic SDK not installed")
        return {"ok": False, "sdk_installed": False, "api_key_set": False,
                "error": "anthropic not installed", "latency_ms": ms}


# ── Main entrypoint  ──────────────────────────────────────────────────────────

async def run_startup_checks() -> None:
    """
    Run all model checks at server startup.

    CPU-bound checks (model loads) run in the thread pool so the event loop
    stays responsive.  Results are stored in _results for later querying.
    """
    loop = asyncio.get_running_loop()
    log.info("startup.checks_begin")

    # All GPU models load sequentially to avoid CUDA context corruption.
    # Order matters: TTS (XTTS-v2) must claim its CUDA allocations before
    # Whisper (CTranslate2), otherwise a device-side assert is triggered.
    # VAD (silero/torch) and embedder (sentence-transformers) follow.
    for name, fn in [
        ("tts",      _check_tts),
        ("vad",      _check_vad),
        ("whisper",  _check_whisper),
        ("embedder", _check_embedder),
    ]:
        _results[name] = await loop.run_in_executor(None, fn)

    # Network-only checks — safe to run concurrently
    ollama_fut = loop.run_in_executor(None, _check_ollama)
    claude_fut = loop.run_in_executor(None, _check_claude)
    _results["ollama"], _results["claude"] = await asyncio.gather(ollama_fut, claude_fut)

    # Summary banner
    ok  = [k for k, v in _results.items() if v.get("ok")]
    bad = [k for k, v in _results.items() if not v.get("ok")]
    log.info("startup.checks_done", ok=ok, failed=bad, critical_ready=all_critical_ok())

    if not all_critical_ok():
        log.error(
            "startup.CRITICAL_MODEL_FAILURE",
            failed=[k for k in ("vad", "whisper", "embedder") if not _results.get(k, {}).get("ok")],
            note="Audio pipeline will not function until these are resolved.",
        )
