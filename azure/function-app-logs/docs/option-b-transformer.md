# Option B: Python Azure Function Transformer

## Summary

Deploy a Python Azure Function that reads FunctionAppLogs from an Event Hub consumer group, maps fields correctly, and forwards to the LM webhook or REST ingest endpoint.

## Architecture

```
Function App Logs -> Event Hub (log-hub) -> Python Transformer Function -> LM Logs Ingest API
```

Uses the same Event Hub that already receives diagnostic logs. The transformer reads from a dedicated consumer group to avoid interfering with the existing lm-logs-azure Java Function.

## Implementation

1. Create a new Python Azure Function with Event Hub trigger
2. Read FunctionAppLogs events from the consumer group
3. Extract `properties.level` and `properties.message` from each event
4. Map severity levels: Verbose->debug, Information->info, Warning->warn, Error->error, Critical->error
5. Build LM Ingest API payload with `_lm.resourceId` for resource mapping
6. Send to LM REST Ingest API using LMv1 HMAC auth (same pattern as the VNet flow forwarder)

## Effort

- Medium: We have the pattern established in the GCP VPC Flow Logs project and the Azure VNet Flow Logs project
- Reuse lm_ingest.py (LMv1 auth, gzip, retry) from the VNet flow forwarder
- Reuse the batching pattern from flow_parser.py

## Timeline

- Days, not weeks. The building blocks exist.

## Benefits

- Tangible demo for PM and customer in short timeframe
- Full control over field mapping and log formatting
- Can handle the Linux single-quote serialization bug in our transformer
- Does not depend on upstream PR review cycle

## Risks

- Additional Azure Function to maintain
- Only fixes it for environments where this transformer is deployed
- Running cost (minimal on Consumption plan, but nonzero)
