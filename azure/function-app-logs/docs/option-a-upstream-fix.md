# Option A: Upstream Fix to lm-logs-azure

## Summary

Submit a PR to the logicmonitor/lm-logs-azure Java repository to fix Azure Function App log parsing for Linux Function Apps.

## Problem

The lm-logs-azure Java Function (LogsEventProcessor) does not properly extract severity and message from FunctionAppLogs events on Linux Function Apps. Specifically:
- `properties.level` is not mapped to the LM log level
- `properties.message` is not extracted as the log message body
- Linux Function Apps serialize certain fields with single quotes instead of double quotes, breaking JSON parsing

## Proposed Fix

1. Modify `LogEventProperties.java` to read `properties.level` and `properties.message` from the event payload
2. Add a sanitization step that normalizes single-quote JSON from Linux Function Apps before parsing
3. Map Azure log levels (Verbose, Information, Warning, Error, Critical) to LM levels (debug, info, warn, error, error)

## Effort

- Medium: Requires Java, Gradle, and LogicMonitor SDK knowledge
- Files to modify: LogEventProperties.java, possibly EventHubTriggerFunction.java
- Needs understanding of the Azure Functions Java SDK event model

## Timeline

- Engineering review and merge process applies
- Depends on LM engineering team capacity and PR review cycle

## Benefits

- Fixes the issue for ALL customers using Azure Function App logs with lm-logs-azure
- No additional infrastructure or runtime cost
- Maintained by LogicMonitor going forward

## Risks

- PR may take time to review and merge
- Linux single-quote bug may have broader implications in the Java SDK
- We do not control the release timeline
