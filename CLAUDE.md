# LM Log Integrations

Multi-cloud log integration POC for Product Engineering stress testing.

## Session Startup

### Available MCP Servers

| Server | Purpose | Key Tools |
| ------ | ------- | --------- |
| **logicmonitor** | LogicMonitor portal operations | Device/alert management, API queries |
| **quantum-mcp** | Quantum computing and optimization | quantum_anneal, quantum_kernel, quantum_simulate, quantum_vqe, quantum_qaoa |

## Project Info

- Github repo: https://github.com/ryanmat/AWS-Azure-KMPG-POC
- Github branch: main (use feature branches for development)
- Documentation: https://www.logicmonitor.com/support

## Folder Structure

```
aws/          - AWS integrations (VPC Flow Logs, WAF, Shield, Network Firewall)
azure/        - Azure integrations (VNet Flow Logs, Function App Logs)
gcp/          - GCP integrations (VPC Flow Logs)
shared/       - Cross-cloud scripts (load-env, validate-lm, validate-all)
docs/         - Internal planning and status docs (excluded from git)
```

## Implementation Files

- Plan: docs/plan.md
- Progress: docs/todo.md
- Lessons: docs/lessons.md

## Architectural Constraints

| Constraint | Details |
|-----------|---------|
| No Cloud Collectors | Cannot modify or rely on cloud collectors. All DataSources use Groovy collection scripts. |
| Dual-Lambda Architecture | VPC and WAF each have dedicated Lambdas with isolated concurrency to prevent resource starvation. |
| Webhook for AWS Logs | AWS logs (VPC Flow, WAF) forwarded via Lambda to LM webhook ingest endpoints. |
| Webhook LogSources | Resource mapping and log field extraction use Webhook Attribute method on pre-parsed fields. |
| Lambda Pre-Parsing | handler.py parses VPC flow log fields and WAF JSON fields into top-level payload keys before sending to webhook. |
| Bearer Token Auth (AWS) | Webhook Lambda uses Bearer token auth (LM_BEARER_TOKEN). |
| LMv1 Auth (Azure) | Azure Function uses LMv1 HMAC-SHA256 auth for REST Ingest API. |
| Event Grid (Azure) | Azure VNet flow logs use Event Grid (BlobCreated trigger), not Event Hub. |
| Block Watermarking (Azure) | Block-level watermarks in Table Storage for incremental blob processing. Advances only on full batch success. |
| 7MB Batch Limit | LM REST Ingest API has a 7MB batch size limit. |
| Shield Skipped | AWS Shield Advanced ($3k/mo + 1yr commit) not deployed. JSON spec exists as reference. |
| Network Firewall Blocked | AWS Network Firewall not deployed in sandbox (~$285/mo). JSON spec exists. |
