# LM Log Integrations

Multi-cloud log integration POC for Product Engineering. Ingests VPC/VNet flow logs, WAF logs, and security metrics from AWS, Azure, and GCP into LogicMonitor LM Logs.

## Cloud Providers

### AWS (`aws/`)

| Integration | Status | Path |
|-------------|--------|------|
| VPC Flow Logs | Operational | `aws/vpc-flow-logs/` |
| WAF Logs + Metrics | Operational | `aws/waf/` |
| Shield Advanced | Spec only ($3k/mo) | `aws/shield/` |
| Network Firewall | Spec only (no infra) | `aws/network-firewall/` |

**Pipeline:** CloudWatch Logs -> Lambda (webhook forwarder) -> LM Webhook Ingest

### Azure (`azure/`)

| Integration | Status | Path |
|-------------|--------|------|
| VNet Flow Logs | Operational | `azure/vnet-flow-logs/` |
| Function App Logs | Options drafted | `azure/function-app-logs/` |

**Pipeline:** Storage Account -> Event Grid -> Azure Function -> LM REST Ingest API

### GCP (`gcp/`)

| Integration | Status | Path |
|-------------|--------|------|
| VPC Flow Logs | Operational | `gcp/vpc-flow-logs/` |

**Pipeline:** Pub/Sub -> Cloud Function -> LM Webhook Ingest

## Testing Each Integration

```bash
# AWS VPC Flow Logs
bash aws/vpc-flow-logs/tests/test-aws-vpc-flow.sh

# Azure VNet Flow Logs (Python tests)
cd azure/vnet-flow-logs && python -m pytest tests/

# Azure VNet Flow Logs (E2E)
bash azure/vnet-flow-logs/tests/test_e2e.sh

# GCP VPC Flow Logs
cd gcp/vpc-flow-logs && uv run pytest
```

## Setup

1. Copy `.env.example` to `.env` and fill in credentials
2. Run `shared/scripts/validate-all.sh` to verify environment
3. See `docs/` for detailed plans and status

## Docs

- `docs/plan.md` - Implementation plan
- `docs/todo.md` - Progress tracking
- `docs/lessons.md` - Learned patterns and constraints
- `docs/logging_spec.md` - Technical specification
- `docs/aws-security-datasource-status.md` - AWS DataSource audit
