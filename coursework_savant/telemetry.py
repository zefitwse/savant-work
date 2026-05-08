from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from typing import Any, Dict, Iterator, Optional


_TRACER: Any = None
_INITIALIZED = False


def init_telemetry(default_service_name: str) -> Any:
    """Initialize optional OpenTelemetry tracing.

    The project should keep running when OpenTelemetry packages or an OTLP
    collector are not available. In that case this module quietly falls back to
    no-op spans.
    """

    global _TRACER, _INITIALIZED
    if _INITIALIZED:
        return _TRACER
    _INITIALIZED = True

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        _TRACER = None
        return None

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name = os.getenv("OTEL_SERVICE_NAME", default_service_name)

    if endpoint:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)

    _TRACER = trace.get_tracer(service_name)
    return _TRACER


@contextmanager
def start_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
    tracer = _TRACER
    if tracer is None:
        with nullcontext() as span:
            yield span
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        yield span


def instrument_fastapi(app: Any, default_service_name: str = "coursework-control-api") -> None:
    init_telemetry(default_service_name)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except Exception:
        return
    try:
        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        return

