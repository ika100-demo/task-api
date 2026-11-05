"""OpenTelemetry tracing for task-api.

Configured through the standard OpenTelemetry variables, which the platform's observability
addon injects: OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://otel-collector:4318),
OTEL_EXPORTER_OTLP_PROTOCOL (http/protobuf by default, or grpc), OTEL_SERVICE_NAME and
OTEL_RESOURCE_ATTRIBUTES. The older OTLP_ENDPOINT (gRPC) still works. Tracing is a no-op
until configure_tracing() is called from the application entrypoint.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter


def tracing_enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTLP_ENDPOINT"))


def build_exporter() -> SpanExporter:
    """OTLP exporter chosen from the environment (the SDK reads the endpoint and headers itself)."""
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        if os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf") == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcExporter,
            )

            return GrpcExporter()
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HttpExporter,
        )

        return HttpExporter()
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as LegacyExporter,
    )

    return LegacyExporter(endpoint=os.environ["OTLP_ENDPOINT"])


def configure_tracing(service_name: str = "task-api") -> None:
    """Configure OpenTelemetry tracing with an OTLP exporter."""
    # OTEL_SERVICE_NAME wins over the default name when the platform sets it
    attributes = {} if os.environ.get("OTEL_SERVICE_NAME") else {"service.name": service_name}
    provider = TracerProvider(resource=Resource.create(attributes))
    provider.add_span_processor(BatchSpanProcessor(build_exporter()))
    trace.set_tracer_provider(provider)
