# SigNoz (optional backend)

This lab's default compose uses **Jaeger**. SigNoz is a drop-in OTLP backend if you prefer dashboards + alerts in one place.

## Quick path

1. Install / run SigNoz (their docker / helm docs).
2. Point mcp-trace at the SigNoz OTLP endpoint:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317   # or SigNoz collector host
./scripts/run-trace.sh
python lab/agent.py
```

3. Open the SigNoz UI → Traces → filter `service.name = agent-obs-lab`.

No SigNoz compose is vendored here (heavy footprint). Keep Jaeger for the 1–2 week MVP skeleton.
