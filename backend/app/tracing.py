"""
LLM Observability — Arize Phoenix + OpenTelemetry.

Initialised once at startup (before init_db).  Configures the global OTel
TracerProvider to export spans to a running Phoenix instance at
http://localhost:6006.

Phoenix must be running separately — start it once with:
    pip install arize-phoenix
    phoenix serve

Our app only needs arize-phoenix-otel (slim client) to configure the exporter.

• Claude calls are auto-instrumented via openinference-instrumentation-anthropic.
• Ollama calls are manually wrapped in router.py.

Degrades gracefully — if arize-phoenix-otel is not installed, or Phoenix is
not running, the function returns False and the rest of the app continues
normally with no tracing.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def init_tracing() -> bool:
    """
    Configure the global OTel TracerProvider to export to Phoenix.

    Returns True on success, False if packages are missing or Phoenix
    is not reachable.
    """
    try:
        # phoenix.otel comes from arize-phoenix-otel (slim client, no server dependency)
        from phoenix.otel import register

        # Register OTel TracerProvider pointing at Phoenix's OTLP HTTP endpoint.
        # phoenix.otel.register handles TracerProvider + BatchSpanProcessor + exporter.
        register(
            endpoint="http://localhost:6006/v1/traces",
            project_name="vestige",
            batch=True,
            verbose=False,
        )

        # Auto-instrument the Anthropic SDK — all Claude calls get spans automatically
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        AnthropicInstrumentor().instrument()

        log.info("tracing.configured", collector="http://localhost:6006/v1/traces",
                 note="Spans will be exported when Phoenix is running (phoenix serve)")
        return True

    except ImportError:
        log.info(
            "tracing.phoenix_not_installed",
            note="Install arize-phoenix-otel for LLM tracing: pip install arize-phoenix-otel",
        )
        return False
    except Exception as exc:
        log.warning("tracing.init_failed", error=str(exc))
        return False


def get_tracer(name: str = "vestige"):
    """
    Return an OTel tracer.  Returns a no-op tracer if OTel is not configured.
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpTracer:
    """Minimal no-op tracer for use when OTel is not installed."""

    def start_as_current_span(self, name: str, **_):
        from contextlib import nullcontext
        return nullcontext()
