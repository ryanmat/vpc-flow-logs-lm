# Project Lessons Learned

Constraints and patterns discovered during implementation that apply to all future work.

## LogSource Configuration

- Webhook Attribute method is preferred over Dynamic(Regex) for LogSources. Pre-parse fields in the forwarder (Lambda or Azure Function) and extract them via Webhook Attribute mappings in the LogSource.
- LogSource name field is a display identifier; SourceName filter on the webhook payload is what routes logs to the correct LogSource.

## Authentication

- AWS webhook Lambda uses Bearer token auth (LM_BEARER_TOKEN env var) against the webhook ingest endpoint.
- Azure Function uses LMv1 HMAC-SHA256 auth (LM_ACCESS_ID + LM_ACCESS_KEY) against the REST Ingest API.
- These are different APIs with different auth methods. Do not mix them.

## AWS Architecture

- Dual-Lambda architecture: VPC and WAF each get a dedicated Lambda with isolated reserved concurrency to prevent resource starvation under load.
- VPC Flow Log custom format must have instance-id as the FIRST field for LM resource mapping.
- WAF CloudWatch log group name must start with "aws-waf-logs-" (AWS requirement).

## Azure Architecture

- Block-level watermarking in Table Storage for incremental blob processing. Watermark advances only on full batch success to prevent data loss on partial failures.
- Event Grid triggers on BlobCreated with PutBlockList API filter (not PutBlob) to catch committed block updates.
- Flow log blobs are PT1H.json format with nested records -> flows -> flowGroups -> flowTuples hierarchy.

## LM Ingest API

- 7MB batch size limit on LM REST Ingest API. Batch entries and check size before sending.
- The webhook endpoint rate-limits at ~10 req/s. Use SEND_DELAY between POSTs and isolated concurrency to stay under the limit.
- HTTP 202 with {"success":true,"message":"Accepted"} is the success response for REST Ingest.

## DataSource Patterns

- Groovy collection scripts on traditional collectors require AWS CLI at /usr/local/bin/aws with IAM access.
- Per-instance collection uses instanceProps.get("wildvalue") to get the rule/dimension name discovered by the AD script.
- namevalue post-processor expects "key=value" output format from collection scripts.
- LM REST API update_datasource is a FULL REPLACE, not a partial update. Omitted fields are blanked (empty string, false, null). Every update call must include the complete DataSource definition. Export first, modify, then PUT back.
- For batchscript namevalue datapoints, rawDataFieldName MUST be set to "output". If omitted, the namevalue post-processor cannot locate the script output and returns "unknown raw datapoint" errors.
- Batchscript DataSources execute on traditional collectors (collector_id > 0), not cloud-discovered resources (collector_id: -2). appliesTo must target a device with collector credentials (e.g., a collector device with azure.tenantid property), not the cloud resource itself.
- LM appliesTo DSL is NOT Groovy. Methods like `.size()` are invalid. Use regex matching (`property =~ ".+"`) to test for non-empty property values.
- Groovy script error handling: use System.err.println for errors, not println. println goes to stdout and corrupts namevalue parser output. stderr goes to collector logs where it is useful for debugging.
- LM ComplexDataPoint expressions do NOT support ternary operators (`condition ? a : b`). The expression engine silently fails, producing "No Data" instead of an error. Use simple arithmetic and prevent division-by-zero at the discovery layer (filter out zero-denominator instances) rather than guarding in the expression.
- When the same appliesTo mistake recurs (targeting cloud resources for batchscript), the root cause is not forgetting the rule -- it is that appliesTo defaults feel intuitive (hasCategory matches the resource you want data about). The correct mental model: appliesTo selects WHERE the script RUNS, not what it monitors. Batchscript runs on the collector device, not the cloud resource.

## GCP Architecture

- GCP VPC Flow Logs use Pub/Sub as the transport: Log Router sink -> Pub/Sub topic -> Cloud Function (Pub/Sub trigger) -> LM webhook.
- Cloud Functions Gen2 run on Cloud Run. Python logging module output (logger.info, logger.warning) may be invisible in Cloud Logging. Use print() with flush=True as primary output, and add logging.basicConfig(stream=sys.stderr) as belt-and-suspenders. Verify log output on first deployment -- do not assume standard logging works.
- Cloud Functions deploy from inside the source directory (e.g., cloud_function/). Package-relative imports like `from cloud_function.config import X` work in tests (where pythonpath includes root) but fail in deployment. Use try/except conditional imports: try the flat import first (from config import X), fall back to the package-relative import.
- CloudEvent trigger functions receive CloudEvent objects in production, not dicts. `cloud_event.get("data")` works on test dicts but fails on CloudEvent objects. Use `cloud_event.data` property with a try/except fallback for test compatibility. Test fixtures should use actual CloudEvent objects (from cloudevents.http import CloudEvent) rather than plain dicts.
- GCP Log Router sinks may require a re-update after initial creation before they start publishing. If Pub/Sub topic shows zero messages after sink creation and permissions are correct, re-run the sink update command with the same configuration.
- For GCP cloud-discovered devices in LM, use `system.gcp.resourcename` for resource mapping, NOT `system.hostname`. LM assigns long composite hostnames to GCP devices (e.g., "us-east1:project-id:computeengine:vm-name-hash") that do not match the simple VM name in flow log payloads.
- Each cloud provider has a different resource mapping key for webhook LogSources: AWS uses `system.aws.instanceid` (mapped from instance_id), GCP uses `system.gcp.resourcename` (mapped from vm_name), Azure uses `system.displayname` (mapped from resource name). Do not assume cross-cloud consistency.

## LM Webhook LogSource Behavior

- LM webhook returns HTTP 202 "Accepted" regardless of whether a LogSource actually processes the log. 202 does NOT mean logs are visible in portal. Always verify logs appear in the Logs tab, not just the HTTP response.
- If no LogSource matches the incoming webhook payload (resource mapping fails, SourceName filter mismatch, or LogSource deleted), logs are silently dropped. No error feedback to the sender.
- LM silently drops webhook logs when resource mapping fails. Resource mapping compares a webhook field value against a device property. If the values do not match (e.g., vm_name="flow-log-test" vs system.hostname="us-east1:project:computeengine:flow-log-test-hash"), the log is accepted but never attached to a device.
- Do NOT delete and recreate LogSources to change configuration. Edit in place. Deleting creates a window where no LogSource matches, and any logs sent during that window are silently lost (202 accepted, never visible).
- When the default LogSource handles logs but a custom LogSource does not, the issue is almost certainly in the custom LogSource's resource mapping or filter configuration, not in the webhook payload. The default LogSource is more permissive.
- LM webhook LogSources ONLY process string values as metadata. Non-string payload values (integers, booleans, objects, arrays) cause the LogSource to silently skip field extraction. Logs fall through to the default webhook handler with no error or warning. AWS Lambda naturally sends strings (parsed from text format); GCP Cloud Logging preserves native JSON types (integers for ports, protocol, bytes). Always str() all top-level payload values before sending to LM webhook.
- WebhookAttribute extraction only reads top-level JSON keys. Nested values (e.g., src_instance.vm_name inside a flow log record) are invisible to the LogSource. Promote needed nested values to top-level keys in the forwarder before sending. This matches the AWS pattern where instance_id, eni, srcaddr are all top-level.
- Webhook LogSource appliesTo is NOT a valid configuration field. Webhook LogSources route by SourceName filter on the payload, not appliesTo. Do not waste time debugging appliesTo on webhook LogSources.
- LogSource "Not in use" status means no logs have been successfully processed through it yet. It does NOT mean the LogSource is disabled or misconfigured. Status changes to active after the first successful log processing.

## GCP Deployment

- GCP Secret Manager is required for storing LM credentials (bearer token, company name). Cloud Function reads secrets at runtime via google-cloud-secret-manager SDK.
- Cloud Function deployment iterations are cheap and fast (~60s each). Iterate aggressively on deployment issues rather than trying to get it perfect locally.
- VPC Flow Logs require a dedicated subnet with flow logging enabled. The e2-micro tier is sufficient for generating test traffic.

## Correction Log

Format: YYYY-MM-DD | category | brief description

2026-03-25 | code quality | CloudEvent data access used dict .get() method which fails on production CloudEvent objects. Tests passed because test fixtures used plain dicts. Fixed with try/except for cloud_event.data property access.
2026-03-25 | code quality | Module imports used package-relative paths (from cloud_function.config import) that fail when Cloud Functions deploys from inside the source directory. Fixed with conditional imports (try flat, except package-relative).
2026-03-25 | debugging | Python logging module output was invisible in Cloud Run Gen2. Spent time wondering why no logs appeared. print(flush=True) works reliably. Added logging.basicConfig(stream=sys.stderr) as secondary path.
2026-03-25 | tool usage | GCP Log Router sink was correctly configured with permissions but not publishing. Re-running the sink update command with identical config resolved the issue. No root cause identified.
2026-03-25 | tool usage | LM Webhook LogSource resource mapping used system.hostname which contains a long composite string for GCP devices. Flow log vm_name field never matches. Fixed by using system.gcp.resourcename.
2026-03-25 | tool usage | LM webhook returns 202 regardless of processing outcome. Assumed 202 meant logs were ingested. Logs were silently dropped due to resource mapping failure. Must verify in portal.
2026-03-25 | tool usage | Deleted and recreated custom LogSource to change config. Logs sent during the gap were silently dropped. Should have edited in place.
2026-03-26 | tool usage | GCP Cloud Function sent numeric payload values (ports, protocol as integers). LM webhook LogSource silently skipped field extraction for non-string values. Custom LogSource appeared broken; default LogSource handled logs because it does not depend on field extraction. Fixed by str() on all top-level values.
2026-03-26 | tool usage | WebhookAttribute resource mapping field (vm_name) was nested inside src_instance/dest_instance objects. WebhookAttribute only reads top-level keys. Promoted vm_name to top-level in Cloud Function before sending.
2026-03-26 | debugging | Multiple agents theorized empty appliesTo was causing LogSource to fail. Ryan found official LM docs confirming appliesTo is not a webhook LogSource field. Wasted investigation time on a non-issue. Always check official docs before accepting agent-generated theories.
