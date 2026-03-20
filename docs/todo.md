# Log Integration POC - State Tracking

## Status Legend

- [ ] Not Started
- [~] In Progress
- [x] Complete
- [!] Blocked
- [-] Skipped (not needed)

> Note: This tracker was originally created for the KPMG POC. Historical references to KPMG resources (stack names, function app names, device IDs) reflect the deployed environment and are preserved for accuracy.

---

## Pre-Existing Configuration (Verified by User)

- [x] Azure cloud account configured in LogicMonitor
- [x] AWS cloud account configured in LogicMonitor
- [x] Cost Optimization Billing configured (Azure)
- [x] Cost Optimization Billing configured (AWS)

---

## ~~Phase 0: Project Setup and Environment Validation~~ (REMOVED)

Killed. Project structure grew organically. Any useful housekeeping
(`.env.example`, `validate-all.sh`) folded into Phase 8 handoff.

---

## Phase 1: AWS VPC Flow Logs Pipeline

### 1.1 CloudWatch Log Group Setup
- [ ] setup-vpc-flow-log-group.sh created
- [ ] CloudWatch Log Group "/aws/vpc/flowlogs" created
- [ ] Retention policy set (7 days)
- [ ] IAM Role "VPCFlowLogsRole" created
- [ ] Role ARN documented

### 1.2 Enable VPC Flow Logs
- [ ] enable-vpc-flow-logs.sh created
- [ ] Custom format with instance-id first configured
- [ ] VPC Flow Logs enabled on target VPC
- [ ] Flow Log ID documented

### 1.3 Deploy LMLogsForwarder Lambda (REPLACED)
- [x] deploy-lm-logs-forwarder.sh created (original, now replaced)
- [x] CloudFormation stack deployed (original)
- [x] Lambda function running (original)
- [x] Lambda ARN documented (original)

### 1.3b Deploy Webhook Forwarder Lambdas (Dual-Lambda Architecture)
- [x] lambda/webhook-forwarder/handler.py created (shared by both Lambdas)
- [x] lambda/webhook-forwarder/cloudformation.yaml created (parameterized for both stacks)
- [x] scripts/aws/deploy-webhook-forwarder.sh created (deploys both stacks)
- [x] CF stack kpmg-webhook-forwarder-vpc deployed (KPMGWebhookForwarderVPC, concurrency=5)
- [x] CF stack kpmg-webhook-forwarder-waf deployed (KPMGWebhookForwarderWAF, concurrency=1)
- [x] Both Lambda functions running with isolated concurrency
- [x] Subscription filters wired (VPC log group -> VPC Lambda, WAF log group -> WAF Lambda)
- [x] Old single-Lambda stack kpmg-webhook-forwarder deleted
- [x] Level field added to handler.py for log_level mapping (REJECT/BLOCK=warn, else=info)

### 1.4 Create Webhook LogSources for Resource Mapping
- [x] logsources/vpc_flow_logs_logsource.json spec created (updated to Webhook Attribute approach)
- [x] VPC Flow Logs Webhook LogSource created in LM portal
- [x] VPC logs mapping to EC2 instances via Webhook Attribute on instance_id
- [x] Log fields (srcaddr, dstaddr, action, etc.) populating via Webhook Attribute extraction
- [x] log_level field mapped via Webhook Attribute (key=log_level, value=Level)

### 1.5 Verify AWS VPC Flow Logs in LM Logs
- [x] verify-vpc-flow-logs.sh created
- [x] test-aws-vpc-flow.sh created
- [x] Logs visible in LM Logs (confirmed 162k+ logs flowing)
- [x] Resource mapping configured (LogSource created in 1.4; maps instance_id to system.aws.instanceid on 75 EC2 devices; ENI-only traffic with instance_id="-" will not map)

---

## Phase 2: AWS WAF/Shield/Network Firewall Monitoring

### 2.1 Verify OOB AWS Security DataSources
- [x] verify-security-datasources.sh created
- [x] docs/aws-security-datasource-status.md created
- [x] OOB DataSources documented (corrected: 2 OOB WAF DataSources exist at account level; 0 for Shield/NFW)
- [x] Custom needs identified (Shield and NFW require custom; WAF custom built as supplement to OOB)

### 2.2 Enable WAF Logging to CloudWatch
- [x] enable-waf-logging.sh created
- [x] CloudWatch Log Group "aws-waf-logs-kpmg" created
- [x] WAF logging enabled
- [x] Subscription filter wired to dedicated KPMGWebhookForwarderWAF Lambda
- [x] logsources/waf_logs_logsource.json spec created (updated to Webhook Attribute approach)
- [x] WAF Webhook LogSource created in LM portal
- [x] WAF logs flowing through pipeline (CloudWatch -> Lambda -> webhook -> LM Logs)
- [x] WAF logs mapping to Web ACL resource (aws.arn custom property on device)
- [x] WAF log fields populating correctly (all Webhook Attribute fields verified)

### 2.3 Custom WAF CloudWatch DataSource (Groovy)
- [x] datasources/AWS_WAF_Custom.json created
- [x] datasources/KPMG_AWS_WAF_Metrics.groovy created (collection)
- [x] datasources/KPMG_AWS_WAF_Metrics_AD.groovy created (discovery)
- [x] DataSource in LM portal (id: 11442196, Locator AC26ZY, v1.1.0, group "AWS WAF", collectMethod: script)
- [x] WAF device exists in portal (id: 279643, "KPMG POC WAF WebACL", collector 26, group_id 2005)
- [x] Device properties set: system.categories=KPMG_WAF, aws.webacl.name=kpmg-poc-webacl, aws.region=us-west-2, aws.arn=<full ARN>
- [x] DataSource now applied to device (appliesTo matches KPMG_WAF category)
- [x] Repo JSON synced to match portal (collectMethod: script, appliesTo: hasCategory("KPMG_WAF"))
- [x] Metrics collection operational (2 instances: ALL aggregate + kpmg-poc-webacl rule; per-instance collection via instanceProps wildvalue)

### 2.4 Custom Shield CloudWatch DataSource (SKIPPED - POC)
- [-] Shield Advanced not deployed ($3k/mo + 1yr commit)
- [x] datasources/AWS_Shield_Custom.json created as reference spec
- [-] DataSource import deferred until Shield is available

### 2.5 Custom Network Firewall DataSource (BLOCKED - No Infra)
- [!] No Network Firewall deployed in sandbox (~$285/mo to stand up)
- [x] datasources/AWS_NetworkFirewall_Custom.json created as reference spec
- [ ] Groovy AD + collection scripts (pending infra deployment)

---

## Phase 3: Azure VNet Flow Logs Pipeline

### 3.1 Azure Storage and Event Grid (Replaced Event Hub)
- [-] setup-event-hub.sh created (not needed, Event Grid used instead)
- [x] Resource group: CTA_Resource_Group (eastus, pre-existing)
- [-] Event Hub Namespace (not needed, Event Grid triggers directly from blob storage)
- [-] Event Hub "log-hub" (not needed)
- [x] Storage account: rmazurestorage (flow log blobs + watermark table)
- [x] Storage account: kpmgfuncstore (Function App backing store)
- [x] Event Grid subscription: vnet-flow-log-events (on rmazurestorage, BlobCreated trigger)

### 3.2 Deploy Azure Function
- [-] deploy-azure-function.sh created (deployed via Azure CLI instead of Terraform)
- [-] Terraform configuration (not used)
- [x] Azure Function deployed: kpmg-vnet-flow-forwarder (Python 3.11, Linux, Consumption plan)
- [x] Function vnet_flow_processor active and running
- [x] App settings configured (LM_COMPANY, LM_ACCESS_ID, LM_ACCESS_KEY, AZURE_STORAGE_CONNECTION_STRING, WATERMARK_TABLE_NAME, TARGET_VNET_RESOURCE_ID, LM_DEVICE_DISPLAY_NAME)
- [x] Application Insights connected (InstrumentationKey=f6dc530c-7d2a-4746-b1a6-c79592020660)

### 3.3 Enable VNet Flow Logs
- [-] enable-vnet-flow-logs.sh created (configured via Azure portal/CLI)
- [x] Network Watcher enabled (eastus)
- [x] Storage Account: rmazurestorage (flow log destination)
- [x] VNet Flow Logs enabled: kpmg-cta-vnet-flow-log on CTA-vnet (JSON v2)
- [x] 56+ blobs in insights-logs-flowlogflowevent container

### 3.4 Verify Azure VNet Flow Logs in LM Logs
- [-] verify-vnet-flow-logs.sh (tests/azure/test_e2e.sh exists as equivalent)
- [x] Azure Function showing activity (fires every ~1 min on blob events, 52+ watermark entries)
- [x] Event Grid delivering events (BlobCreated + PutBlockList)
- [x] Logs accepted by LM (HTTP 202, {"success":true,"message":"Accepted"})
- [x] LM device: US-E1:virtualNetwork:CTA-vnet (id: 289252, group_id: 2005)
- [x] Resource mapping via system.displayname + azure.resourceid

---

## Phase 4: Azure DNS/Private Link/Private Endpoint Monitoring

### 4.1 Verify Azure DNS Zone DataSource
- [ ] verify-dns-datasources.sh created
- [ ] docs/azure-dns-status.md created
- [ ] DNS Zone DataSource verified
- [ ] Metrics collection confirmed

### 4.2 Create Private Endpoint PropertySource
- [ ] propertysources/Azure_PrivateEndpoint_Properties.xml created
- [ ] import-privateendpoint-propertysource.sh created
- [ ] PropertySource imported
- [ ] Properties populating on resources

### 4.3 Create Private Endpoint Health Dashboard
- [ ] dashboards/azure-private-endpoint-health.json created
- [ ] import-privateendpoint-dashboard.sh created
- [ ] Dashboard imported
- [ ] Widgets displaying data

---

## Phase 5: Performance Benchmarking

### 5.1 Configure Website Checks for Azure Endpoints
- [ ] create-website-checks.sh created
- [ ] configs/website-checks-azure.json.example created
- [ ] configs/website-checks-aws.json.example created
- [ ] Website checks created in LM

### 5.2 Configure Collector-Based Latency Checks
- [ ] docs/collector-latency-setup.md created
- [ ] configs/ping-targets.json.example created
- [ ] configure-ping-targets.sh created
- [ ] Ping targets added to LM

### 5.3 Create Performance Dashboard
- [ ] dashboards/performance-benchmark.json created
- [ ] import-performance-dashboard.sh created
- [ ] Dashboard imported
- [ ] All widgets populated

---

## Phase 6: Egress Cost Attribution Dashboards

### 6.1 Create AWS Egress Cost Dashboard
- [ ] dashboards/aws-egress-cost.json created
- [ ] import-egress-cost-dashboard.sh created
- [ ] Dashboard imported
- [ ] Cost data displaying
- [ ] Flow data displaying

### 6.2 Create Azure Egress Cost Dashboard
- [ ] dashboards/azure-egress-cost.json created
- [ ] import-egress-cost-dashboard.sh created
- [ ] Dashboard imported
- [ ] Cost data displaying
- [ ] Flow data displaying

### 6.3 Create Unified Multi-Cloud Cost Dashboard
- [ ] dashboards/multicloud-egress-overview.json created
- [ ] import-multicloud-dashboard.sh created
- [ ] Dashboard imported
- [ ] Both clouds represented

---

## Phase 7: AWS WAF/Shield Dashboard

### 7.1 Create AWS Security Dashboard
- [ ] dashboards/aws-security-operations.json created
- [ ] import-security-dashboard.sh created
- [ ] Dashboard imported
- [ ] WAF metrics displaying
- [ ] Shield metrics displaying
- [ ] Network Firewall metrics displaying

---

## Phase 8: Final Integration and Testing

### 8.1 End-to-End Test Suite
- [ ] tests/run-all-tests.sh created
- [ ] All individual test scripts created
- [ ] Full test suite passes
- [ ] docs/test-report.md generated

### 8.2 Documentation and Handoff
- [ ] docs/deployment-guide.md created
- [ ] docs/architecture-diagram.md created
- [ ] docs/dashboard-guide.md created
- [ ] docs/maintenance-guide.md created
- [ ] README.md updated

---

## Out-of-Box DataSource Verification Checklist

### Azure DataSources
- [ ] Azure_DNS_Zones - Discovery verified
- [ ] Azure_DNS_Zones - Metrics collecting
- [ ] Azure_PrivateEndpoints - Discovery verified
- [ ] Azure_PrivateEndpoints - Metrics collecting
- [ ] Azure_ExpressRoute - Discovery verified (if applicable)
- [ ] Azure_ExpressRoute - Metrics collecting
- [ ] Azure_VPNGateway - Discovery verified (if applicable)
- [ ] Azure_VPNGateway - Metrics collecting

### AWS DataSources
- [ ] AWS_WAF* - Discovery verified
- [ ] AWS_WAF* - Metrics collecting
- [ ] AWS_Shield* - Discovery verified
- [ ] AWS_Shield* - Metrics collecting
- [ ] AWS_NetworkFirewall* - Discovery verified
- [ ] AWS_NetworkFirewall* - Metrics collecting
- [ ] AWS_DirectConnect - Discovery verified (if applicable)
- [ ] AWS_DirectConnect - Metrics collecting
- [ ] AWS_VPNConnection - Discovery verified (if applicable)
- [ ] AWS_VPNConnection - Metrics collecting
- [ ] AWS_Route53HealthCheck - Discovery verified
- [ ] AWS_Route53HealthCheck - Metrics collecting

---

## Environment Variables Checklist

### LogicMonitor
- [ ] LM_COMPANY set
- [ ] LM_ACCESS_ID set
- [ ] LM_ACCESS_KEY set
- [ ] LM_BEARER_TOKEN set (optional)

### Azure
- [ ] AZURE_SUBSCRIPTION_ID set
- [ ] AZURE_RESOURCE_GROUP set
- [ ] AZURE_REGION set
- [ ] AZURE_CLIENT_ID set

### AWS
- [ ] AWS_ACCESS_KEY_ID set (or using IAM role)
- [ ] AWS_SECRET_ACCESS_KEY set (or using IAM role)
- [ ] AWS_DEFAULT_REGION set
- [ ] AWS_ACCOUNT_ID set

---

## Architectural Constraints

These constraints apply to all work going forward:

| Constraint | Details |
|-----------|---------|
| No Cloud Collectors | We cannot modify or rely on cloud collectors. All DataSources use Groovy collection scripts. |
| Dual-Lambda Architecture | VPC and WAF each have dedicated Lambdas with isolated concurrency to prevent resource starvation. |
| Webhook for Logs | AWS logs (VPC Flow, WAF) are forwarded via Lambda to LM webhook ingest endpoints, not the raw ingestion API. |
| Webhook LogSources | Resource mapping and log field extraction use Webhook Attribute method on pre-parsed fields from handler.py. |
| Lambda Pre-Parsing | handler.py parses VPC flow log fields and WAF JSON fields into top-level payload keys before sending to webhook. |
| Shield Skipped | AWS Shield Advanced ($3k/mo + 1yr commit) is not deployed for this POC. JSON template exists as a spec. |
| Network Firewall Requires Infra | AWS Network Firewall is not deployed in sandbox. Requires ~$285/mo to stand up for testing. |
| Bearer Token Auth | Webhook Lambda uses Bearer token auth (in .env as LM_BEARER_TOKEN). |
| Azure Event Grid | Azure VNet flow logs use Event Grid (BlobCreated trigger on storage account), not Event Hub. |
| Azure LMv1 Auth | Azure Function uses LMv1 HMAC-SHA256 auth for REST Ingest API (not webhook, not bearer token). |
| Azure Watermarking | Block-level watermarks in Table Storage for incremental blob processing. Advances only on full batch success. |
| Azure Region | All Azure resources in eastus (CTA_Resource_Group). |

---

## Blockers and Notes

| Date | Item | Blocker/Note | Resolution |
|------|------|--------------|------------|
| 2026-01-30 | Shield Advanced | $3k/mo, skipped for POC | Document as ready-to-deploy spec |
| 2026-01-30 | Network Firewall | No NFW deployed in sandbox | Needs infra deployment (~$285/mo) |
| 2026-01-30 | Cloud Collectors | Cannot touch cloud collectors | Use Groovy DataSources instead |
| 2026-01-30 | Log Resource Mapping | Logs landing unmapped (_resource.id=0) | Resolved: webhook forwarder + LogSources |
| 2026-02-04 | WAF DataSource appliesTo | DataSource was not matching WAF device | Resolved: device category set to KPMG_WAF, DataSource now applied |
| 2026-02-04 | WAF Device Properties | Device 279643 missing properties | Resolved: aws.webacl.name, aws.region, system.categories set via API |
| 2026-02-04 | Repo JSON out of sync | Repo had awscloudwatch, portal has script | Resolved: repo JSON synced to match portal |
| 2026-02-04 | OOB WAF DataSources | Originally reported 0 OOB WAF DataSources | Corrected: 2 OOB exist (ids 810, 948) at cloud account level |
| 2026-02-04 | MCP Tool Search Bug | name_filter and displayName~ filters do not return results; only group_id and direct ID work | Reported to Ryan for MCP server fix |
| 2026-02-04 | Old Webhook Lambda | KPMGWebhookForwarder (id:281723) is dead in portal, pending auto-delete | No action needed, will auto-clean |
| 2026-02-04 | WAF Metrics NaN | namevalue parser couldn't match output (batch vs per-instance mismatch) | Resolved: switched to per-instance collection using instanceProps.get("wildvalue") |

---

## Change Log

| Date | Phase | Change | Author |
|------|-------|--------|--------|
| | | Initial plan created | |
| 2026-01-30 | 1-2 | Replace LM Lambda forwarder with webhook forwarder Lambda | Ryan + Claude |
| 2026-01-30 | 1-2 | Add Webhook LogSources for VPC Flow Logs and WAF Logs | Ryan + Claude |
| 2026-01-30 | 2 | Skip Shield Advanced deployment (cost), keep JSON spec | Ryan + Claude |
| 2026-01-30 | 2 | Confirm Groovy-only approach (no cloud collector changes) | Ryan + Claude |
| 2026-01-30 | 1-2 | Split single Lambda into dual-Lambda architecture (VPC + WAF) | Ryan + Claude |
| 2026-01-30 | 1-2 | Switch LogSources from Dynamic(Regex) to Webhook Attribute extraction | Ryan + Claude |
| 2026-01-30 | 1-2 | Add Level field to handler.py for log_level mapping | Ryan + Claude |
| 2026-01-30 | 1-2 | WAF logs pipeline operational (CloudWatch -> Lambda -> webhook -> LM Logs) | Ryan + Claude |
| 2026-02-04 | 1-2 | Reconcile todo.md: mark Phase 2.1 complete, fix Phase 1.5 stale note, flag WAF DataSource/device gaps | Ryan + Claude |
| 2026-02-04 | 2 | Fix WAF DataSource collection: switch from batch to per-instance, fix namevalue parsing, restore rawDataFieldName | Ryan + Claude |
| 2026-02-04 | 3 | Verify Phase 3 complete: Azure Function deployed, VNet flow logs enabled, Event Grid wired, LM accepting logs (202) | Ryan + Claude |

