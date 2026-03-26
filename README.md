# LM Log Integrations

Multi-cloud log and metric integration for Product Engineering stress testing. Ingests VPC/VNet flow logs, WAF logs, security metrics, and infrastructure capacity data from AWS, Azure, and GCP into LogicMonitor.

## Architecture

Each cloud provider uses a different ingest path, but all deliver structured log entries to the LM Logs API with `_lm.resourceId` mapping for automatic resource association.

| Cloud | Trigger | Compute | Auth | Ingest Method |
|-------|---------|---------|------|---------------|
| AWS | CloudWatch Logs subscription filter | Lambda (dual: VPC + WAF) | Bearer token | Webhook |
| Azure | Event Grid (BlobCreated) | Azure Function | LMv1 HMAC-SHA256 | REST Ingest API |
| GCP | Pub/Sub | Cloud Function | Bearer token | Webhook |

## Cloud Providers

### AWS (`aws/`)

| Integration | Status | Path |
|-------------|--------|------|
| VPC Flow Logs | Operational | `aws/vpc-flow-logs/` |
| WAF Logs + Metrics | Operational | `aws/waf/` |
| Shield Advanced | Spec only ($3k/mo) | `aws/shield/` |
| Network Firewall | Spec only (no infra) | `aws/network-firewall/` |

**Pipeline:** CloudWatch Logs -> Lambda (webhook forwarder) -> LM Webhook Ingest

Dual-Lambda architecture: `WebhookForwarderVPC` and `WebhookForwarderWAF` each have dedicated CloudFormation stacks with isolated reserved concurrency to prevent resource starvation.

**Key scripts:**
- `aws/vpc-flow-logs/scripts/setup-vpc-flow-log-group.sh` - Create log group and IAM role
- `aws/vpc-flow-logs/scripts/deploy-webhook-forwarder.sh` - Deploy both Lambda stacks
- `aws/waf/scripts/enable-waf-logging.sh` - Enable WAF logging and wire subscription

### Azure (`azure/`)

| Integration | Status | Path |
|-------------|--------|------|
| VNet Flow Logs | Operational | `azure/vnet-flow-logs/` |
| VNet Subnet IP Usage | Operational | `azure/vnet-subnet-usage/` |
| Function App Logs | Options drafted | `azure/function-app-logs/` |

**Log Pipeline:** Storage Account -> Event Grid (BlobCreated/PutBlockList) -> Azure Function -> LM REST Ingest API

Incremental processing: block-level watermarks in Table Storage track which blocks have been processed. Only new blocks are read on each trigger, avoiding full blob reprocessing. Concurrency is limited to 1 (`maxConcurrentCalls`) to prevent watermark race conditions.

**Metric Pipeline:** Groovy batchscript on collector -> Azure ARM REST API (`virtualNetworks/usages`) -> LM DataSource

The VNet Subnet IP Usage DataSource monitors available IP addresses per subnet. Azure Monitor has no native metric for subnet IP utilization, so this uses the ARM REST API directly. Alerts at 80/90/95% usage to prevent allocation failures.

**Key files:**
- `azure/vnet-flow-logs/function/vnet-flow-forwarder/` - Function App source
- `azure/vnet-subnet-usage/datasources/` - DataSource JSON + Groovy collection/AD scripts
- `azure/vnet-flow-logs/tests/` - Unit and integration tests

### GCP (`gcp/`)

| Integration | Status | Path |
|-------------|--------|------|
| VPC Flow Logs | Operational | `gcp/vpc-flow-logs/` |

**Pipeline:** Cloud Logging -> Log Router sink -> Pub/Sub -> Cloud Function (2nd gen) -> LM Webhook Ingest

VPC Flow Logs are captured by Cloud Logging, routed via a Log Router sink to a Pub/Sub topic, and processed by a Gen2 Cloud Function triggered by Eventarc. The function parses CloudEvent-wrapped LogEntries, extracts flow log fields (connection, instances, VPC, GKE details), and forwards structured JSON to the LM webhook endpoint with Bearer token auth. Supports both Ingest API (LMv1 HMAC) and Webhook paths.

**Infrastructure:** Provisioned via `gcloud` CLI scripts (no Terraform). Secret Manager stores LM credentials. The function scales to zero when idle (e2-micro test VM generates flow traffic).

**Key files:**
- `gcp/vpc-flow-logs/cloud_function/main.py` - Cloud Function entry point
- `gcp/vpc-flow-logs/cloud_function/flow_log_parser.py` - CloudEvent/LogEntry parsing
- `gcp/vpc-flow-logs/cloud_function/lm_client.py` - HTTP client for LM endpoints
- `gcp/vpc-flow-logs/infra/setup_gcp.sh` - Provision Pub/Sub, Log Router, Secret Manager
- `gcp/vpc-flow-logs/infra/deploy_function.sh` - Deploy Cloud Function
- `gcp/vpc-flow-logs/documentation/customer_guide.md` - Full deployment walkthrough
- `gcp/vpc-flow-logs/documentation/webhook_logsource_setup.md` - LM Webhook LogSource config

**LM Webhook LogSource notes:**
- Resource mapping must use `system.gcp.resourcename` (not `system.hostname`) for GCP cloud-discovered devices
- Filter: `SourceName Equal GCP-VPC-FlowLogs`
- Payload includes `Level` and `resourceType` fields for LogSource extraction

## Testing

```bash
# AWS VPC Flow Logs (requires AWS credentials)
bash aws/vpc-flow-logs/tests/test-aws-vpc-flow.sh

# Azure VNet Flow Logs (unit tests, no credentials needed)
cd azure/vnet-flow-logs && python -m pytest tests/ -v

# Azure VNet Flow Logs (integration tests, requires AZURE_STORAGE_CONNECTION_STRING)
cd azure/vnet-flow-logs && python -m pytest tests/test_integration.py -v

# Azure VNet Subnet IP Usage (unit tests, no credentials needed)
cd azure/vnet-subnet-usage && uv run pytest tests/ -v

# Azure VNet Subnet IP Usage (integration tests, requires AZURE_TENANT_ID + service principal)
cd azure/vnet-subnet-usage && uv run pytest tests/test_integration.py -v

# GCP VPC Flow Logs
cd gcp/vpc-flow-logs && uv run pytest
```

## Setup

1. Copy `.env.example` to `.env` and fill in credentials
2. Run `shared/scripts/validate-all.sh` to verify environment
3. Deploy per-cloud pipelines using the scripts in each cloud directory

## Constraints

| Constraint | Details |
|-----------|---------|
| No Cloud Collectors | All DataSources use Groovy collection scripts, not cloud collectors |
| 7MB Batch Limit | LM REST Ingest API enforces a 7MB batch size limit |
| Bearer Token (AWS/GCP) | Lambda and Cloud Function use `LM_BEARER_TOKEN` for webhook auth |
| LMv1 HMAC (Azure) | Function uses `LM_ACCESS_ID` + `LM_ACCESS_KEY` for REST Ingest auth |
| GCP Secret Manager | Cloud Function loads LM credentials from Secret Manager at runtime |
| Shield Skipped | AWS Shield Advanced not deployed ($3k/mo + 1yr commitment) |
| Network Firewall Blocked | Not deployed in sandbox (~$285/mo); JSON spec exists as reference |
