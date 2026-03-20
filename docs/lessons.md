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
