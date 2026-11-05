"""Tracing is configured from the standard OpenTelemetry variables; off without an endpoint."""

import pytest

from task_api import tracing


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    names = (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
    )
    for k in names:
        monkeypatch.delenv(k, raising=False)


def test_disabled_without_an_endpoint():
    assert tracing.tracing_enabled() is False


def test_standard_endpoint_enables_tracing_with_the_http_exporter(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
    assert tracing.tracing_enabled() is True
    assert type(tracing.build_exporter()).__module__.endswith("proto.http.trace_exporter")


def test_grpc_protocol_is_honoured(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    assert type(tracing.build_exporter()).__module__.endswith("proto.grpc.trace_exporter")


def test_legacy_variable_still_works(monkeypatch):
    monkeypatch.setenv("OTLP_ENDPOINT", "http://localhost:4317")
    assert tracing.tracing_enabled() is True
    assert type(tracing.build_exporter()).__module__.endswith("proto.grpc.trace_exporter")
