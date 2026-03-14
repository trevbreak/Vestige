"""
LLM Observability — Arize Phoenix + OpenTelemetry.

Initialised once at startup (before init_db).  Starts a local Phoenix UI
at http://localhost:6006 and instruments all LLM calls with OpenTelemetry spans.

• Claude calls are auto-instrumented via openinference-instrumentation-anthropic.
• Ollama calls are manually wrapped in router.py.

Degrades gracefully — if arize-phoenix is not installed the function returns False
and the rest of the app continues normally.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def init_tracing() -> bool:
    """
    Launch Phoenix in-process and configure the global OTel TracerProvider.

    Returns True on success, False if arize-phoenix is not installed or init fails.
    """
    try:
        import phoenix as px
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        # Start Phoenix UI in a background thread (non-blocking)
        px.launch_app()

        # Configure the global OTel tracer to export to Phoenix's local collector
        exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument the Anthropic SDK — all claude calls get spans automatically
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        AnthropicInstrumentor().instrument()

        log.info("tracing.phoenix_started", ui="http://localhost:6006")
        return True

    except ImportError:
        log.info(
            "tracing.phoenix_not_installed",
            note="Install arize-phoenix to enable LLM tracing: pip install arize-phoenix",
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
    from contextlib import nullcontext

    def start_as_current_span(self, name: str, **_):
        from contextlib import nullcontext
        return nullcontext()
