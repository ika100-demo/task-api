# Environment variables

Configuration is read exclusively from environment variables. Defaults below are the application defaults. The deployed values are set per environment in the system's gitops-app repo (`system.yaml`: a component's `env`, and `replicas`, `resources` under `instances.<env>`).

## Core

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP port the service listens on. |
| `LOG_LEVEL` | `INFO` | Logging level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Observability

| Variable | Default | Description |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(unset — tracing disabled)_ | Standard OpenTelemetry endpoint, e.g. `http://otel-collector:4318`; injected by the platform's observability setting of the environment. When set, `configure_tracing()` runs at startup. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | `http/protobuf` or `grpc`. |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | _(project name)_ | Resource attributes; set by the observability setting of the environment. |
| `OTLP_ENDPOINT` | _(unset)_ | Legacy gRPC endpoint (kept for compatibility); prefer the standard variables. |
| `METRICS_PORT` | `8080` | Port serving `/metrics` (same as the main HTTP port unless overridden). |
