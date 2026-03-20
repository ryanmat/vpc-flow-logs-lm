# KPMG Canada Network Logging and Cost Attribution POC - Technical Specification

## Overview

This document specifies the technical requirements for building a LogicMonitor-based network monitoring and cost attribution solution for KPMG Canada across Azure and AWS environments.

---

## 1. Scope

### 1.1 Azure Requirements

| Requirement | Description |
|-------------|-------------|
| VNet Flow Logs | Ingest VNet flow logs to LM Logs for traffic pattern analysis and top talkers identification |
| DNS/Private Link/Private Endpoints | Monitor Azure DNS zones, Private Link, and Private Endpoint resources |
| Egress Cost Attribution | Dashboard correlating network traffic with cost data by department/tag |
| Performance Benchmarking | Inter-region and hybrid latency measurement |

### 1.2 AWS Requirements

| Requirement | Description |
|-------------|-------------|
| VPC Flow Logs | Ingest VPC flow logs to LM Logs for traffic pattern analysis and top talkers |
| WAF/Shield/Network Firewall | Metrics AND logs for all three services |
| Egress Cost Attribution | Dashboard correlating VPC flow traffic with CUR cost data |
| Performance Benchmarking | Inter-AZ, inter-region, and hybrid latency measurement |

---

## 2. Pre-Existing Configuration (Assumed Complete)

- Azure cloud account configured in LogicMonitor
- AWS cloud account configured in LogicMonitor
- Cost Optimization Billing configured for both clouds
- User has sandbox access to Azure and AWS environments
- User will provide `az login` and AWS environment exports

---

## 3. Architecture

### 3.1 Azure VNet Flow Logs Pipeline

```
VNet Flow Logs --> Storage Account --> Event Hub --> Azure Function --> LM Logs Ingestion API
                                                            |
                                                    (LogicMonitor ARM Template)
```

**Components:**
1. Storage Account (for flow log storage)
2. Event Hub Namespace
3. Event Hub
4. Azure Function (Java-based, from logicmonitor/lm-logs-azure)
5. Diagnostic Settings (to route VNet flow logs)
6. Resource Mapping in LM Logs

**Key Configuration:**
- Each Azure region requires separate Event Hub + Function deployment
- Azure Function uses:
  - `LogsEventHubConnectionString`
  - `LogicMonitorCompanyName`
  - `LogicMonitorAccessId`
  - `LogicMonitorAccessKey`
  - `AzureClientID`

### 3.2 AWS VPC Flow Logs Pipeline

```
VPC Flow Logs --> CloudWatch Logs --> Lambda Subscription Filter --> LMLogsForwarder --> LM Logs Ingestion API
                                                                            |
                                                                  (LogicMonitor CloudFormation)
```

**Components:**
1. CloudWatch Log Group (`/aws/ec2/networkInterface` for EC2 flow logs, or custom)
2. IAM Role with required permissions
3. VPC Flow Log configuration
4. CloudFormation Stack (deploys LMLogsForwarder Lambda)
5. Lambda Subscription Filter
6. Resource Mapping in LM Logs

**CloudFormation Parameters:**
- `FunctionName`: LMLogsForwarder (default)
- `LMAccessId`: LogicMonitor API Access ID
- `LMAccessKey`: LogicMonitor API Access Key
- `LMCompanyName`: LogicMonitor portal name
- `LMRegexScrub`: Optional regex for scrubbing
- `PermissionsBoundaryArn`: Optional IAM boundary

**VPC Flow Log Custom Format (Required):**
```
${instance-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status}
```
Note: `instance-id` MUST be the first field for LogicMonitor resource mapping.

### 3.3 AWS WAF/Shield/Network Firewall

**Metrics (CloudWatch DataSources - Verify OOB):**

| Service | Key Metrics |
|---------|-------------|
| WAF | AllowedRequests, BlockedRequests, CountedRequests, PassedRequests |
| Shield | DDoSDetected, DDoSAttackBitsPerSecond, DDoSAttackPacketsPerSecond, DDoSAttackRequestsPerSecond |
| Network Firewall | DroppedPackets, PassedPackets, ReceivedPackets |

**Logs Pipeline (WAF detailed logs):**
```
WAF Logging --> CloudWatch Logs --> Lambda Subscription Filter --> LMLogsForwarder --> LM Logs
```

OR

```
WAF Logging --> S3 Bucket --> S3 Event Notification --> LMLogsForwarder Lambda --> LM Logs
```

### 3.4 Azure DNS/Private Link/Private Endpoints

**Monitoring Approach:**
- Azure DNS Zones: Azure Monitor DataSource (auto-discovered)
- Private Endpoints: PropertySource for metadata, Azure Monitor metrics
- Private Link: Azure Monitor metrics via DataSource

**Custom PropertySource Required:**
- Gather: Connection state, linked resource, private IP
- Apply to: `system.azure.resourcetype == "Microsoft.Network/privateEndpoints"`

### 3.5 Performance Benchmarking

**Azure:**
- Website Checks: Synthetic monitoring from LM checkpoints to Azure endpoints
- Collector-based: Ping/traceroute from Azure-deployed Collector to on-prem
- ExpressRoute/VPN metrics via Azure Monitor DataSource

**AWS:**
- Website Checks: Synthetic monitoring from LM checkpoints to AWS endpoints
- Collector-based: Ping/traceroute between AZs/regions
- Direct Connect/VPN metrics via CloudWatch DataSource
- Route 53 Health Check metrics: ConnectionTime, SSLHandshakeTime

---

## 4. LM Logs Queries

### 4.1 Top Talkers (AWS VPC Flow)

```
source="vpc-flow-logs" action="ACCEPT"
| stats sum(bytes) as total_bytes by srcaddr, dstaddr
| sort -total_bytes
| limit 20
```

### 4.2 Top Talkers (Azure VNet Flow)

```
source="vnet-flow-logs"
| stats sum(bytes) as total_bytes by srcIp, dstIp
| sort -total_bytes
| limit 20
```

### 4.3 Rejected Traffic Analysis

```
source="vpc-flow-logs" action="REJECT"
| stats count as rejected_count by srcaddr, dstport, protocol
| sort -rejected_count
```

### 4.4 Traffic by Protocol

```
source="vpc-flow-logs"
| stats sum(bytes) as total_bytes by protocol
| sort -total_bytes
```

---

## 5. Dashboard Specifications

### 5.1 Network Flow Dashboard (Per Cloud)

**Widgets:**
1. Top Talkers by Bytes (Table Widget with Log Query)
2. Traffic Volume Over Time (Custom Graph)
3. Allowed vs Rejected Traffic (Pie Chart)
4. Traffic by Protocol Distribution (Pie Chart)
5. Traffic by Destination Port (Table)

### 5.2 Egress Cost Dashboard

**Widgets:**
1. Egress Cost by Region (from Cost Optimization data)
2. Egress Cost by Department Tag (from Cost Optimization data)
3. Top Egress Destinations (from flow logs)
4. Cost Trend Over Time (Custom Graph)

### 5.3 WAF/Shield Dashboard (AWS)

**Widgets:**
1. WAF Allowed vs Blocked Over Time
2. Top Blocked Rules
3. Shield Attack Detection Status
4. Network Firewall Drop Rate

### 5.4 Performance Dashboard

**Widgets:**
1. Inter-Region Latency (Website Check response times)
2. Hybrid Latency (Collector ping data)
3. ExpressRoute/Direct Connect Health
4. VPN Tunnel Status

---

## 6. Out-of-Box DataSources to Verify

### 6.1 Azure

| DataSource | Purpose | Verification |
|------------|---------|--------------|
| Azure_DNS_Zones | DNS zone metrics | Check discovery, verify metrics |
| Azure_PrivateEndpoints | Private Endpoint health | Check discovery, verify metrics |
| Azure_ExpressRoute | ExpressRoute circuit metrics | Check discovery, verify BitsIn/Out |
| Azure_VPNGateway | VPN Gateway metrics | Check discovery, verify tunnel metrics |
| Azure_CostManagement | Cost data (if applicable) | Verify cost data flow |

### 6.2 AWS

| DataSource | Purpose | Verification |
|------------|---------|--------------|
| AWS_WAF* | WAF metrics | Check discovery, verify AllowedRequests/BlockedRequests |
| AWS_Shield* | Shield metrics | Check if subscribed, verify DDoSDetected |
| AWS_NetworkFirewall* | Firewall metrics | Check discovery, verify Dropped/PassedPackets |
| AWS_DirectConnect | Direct Connect metrics | Check discovery, verify ConnectionState |
| AWS_VPNConnection | VPN metrics | Check discovery, verify TunnelState |
| AWS_Route53HealthCheck | Health check metrics | Check discovery, verify latency metrics |

*Note: May require custom DataSource if not OOB available. Use CloudWatch Active Discovery method.

---

## 7. Custom Code Artifacts

### 7.1 Azure

| Artifact | Type | Description |
|----------|------|-------------|
| deploy-azure-logs.sh | Bash Script | Deploy Event Hub + Azure Function via Terraform/ARM |
| configure-vnet-flow.sh | Bash Script | Enable VNet flow logs, configure diagnostic settings |
| azure-private-endpoint.propertysource | PropertySource | Gather Private Endpoint metadata |
| azure-network-dashboard.json | Dashboard | Network flow visualization |

### 7.2 AWS

| Artifact | Type | Description |
|----------|------|-------------|
| deploy-aws-logs.sh | Bash Script | Deploy CloudFormation stack for LMLogsForwarder |
| configure-vpc-flow.sh | Bash Script | Create CloudWatch log group, enable VPC flow logs |
| configure-waf-logging.sh | Bash Script | Enable WAF logging to CloudWatch |
| aws-waf-cloudwatch.datasource | DataSource | Custom WAF metrics (if needed) |
| aws-network-dashboard.json | Dashboard | Network flow visualization |

### 7.3 Cross-Cloud

| Artifact | Type | Description |
|----------|------|-------------|
| egress-cost-dashboard.json | Dashboard | Multi-cloud egress cost attribution |
| performance-baseline-dashboard.json | Dashboard | Performance benchmarking |
| website-checks.json | Website Check Config | Synthetic checks for performance |

---

## 8. Testing Strategy

### 8.1 Integration Tests

1. **Log Ingestion Verification**
   - Generate test traffic in cloud environment
   - Verify logs appear in LM Logs within 5 minutes
   - Validate resource mapping is correct

2. **Metric Collection Verification**
   - Trigger CloudWatch/Azure Monitor metrics
   - Verify datapoints appear in Raw Data tab
   - Confirm alert thresholds function

3. **Dashboard Validation**
   - Load dashboard
   - Verify all widgets populate
   - Confirm data accuracy against source

### 8.2 Validation Checkpoints

| Phase | Checkpoint | Success Criteria |
|-------|------------|------------------|
| AWS VPC Flow | Log ingestion | Logs visible in LM Logs |
| AWS VPC Flow | Resource mapping | Logs map to correct EC2/VPC resource |
| AWS WAF | Metrics visible | AllowedRequests/BlockedRequests in Raw Data |
| AWS WAF | Logs ingestion | WAF logs visible in LM Logs |
| Azure VNet Flow | Log ingestion | Logs visible in LM Logs |
| Azure VNet Flow | Resource mapping | Logs map to correct VNet/VM resource |
| Azure DNS | Metrics visible | Query volume in Raw Data |
| Azure Private Endpoint | PropertySource | Properties populated on resource |
| Dashboards | Widget population | All widgets show data |

---

## 9. Environment Variables Required

### 9.1 LogicMonitor

```bash
export LM_COMPANY="<portal_name>"          # e.g., "kpmg"
export LM_ACCESS_ID="<api_access_id>"
export LM_ACCESS_KEY="<api_access_key>"
export LM_BEARER_TOKEN="<bearer_token>"    # Alternative auth
```

### 9.2 Azure (User Provides via az login)

```bash
export AZURE_SUBSCRIPTION_ID="<subscription_id>"
export AZURE_RESOURCE_GROUP="<resource_group>"
export AZURE_REGION="<region>"             # e.g., "eastus"
export AZURE_CLIENT_ID="<client_id>"       # From LM Azure cloud account
```

### 9.3 AWS (User Provides via exports)

```bash
export AWS_ACCESS_KEY_ID="<access_key>"
export AWS_SECRET_ACCESS_KEY="<secret_key>"
export AWS_DEFAULT_REGION="<region>"       # e.g., "us-east-1"
export AWS_ACCOUNT_ID="<account_id>"
```

---

## 10. Dependencies

### 10.1 Tools

- Azure CLI (`az`)
- AWS CLI (`aws`)
- Terraform (optional, for Azure deployment)
- jq (JSON processing)
- curl (API calls)

### 10.2 LogicMonitor

- LM Logs enabled
- Cost Optimization Billing configured
- Cloud accounts (Azure + AWS) configured
- API tokens with appropriate permissions

### 10.3 Cloud Permissions

**Azure:**
- Contributor on Resource Group
- Network Watcher access for flow logs
- Event Hub Data Owner
- Storage Blob Data Contributor

**AWS:**
- IAM permissions for CloudFormation deployment
- VPC Flow Log creation
- CloudWatch Logs access
- Lambda deployment
- WAF configuration access

---

## 11. References

- LogicMonitor LM Logs AWS: https://github.com/logicmonitor/lm-logs-aws
- LogicMonitor LM Logs Azure: https://github.com/logicmonitor/lm-logs-azure
- AWS VPC Flow Logs: https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html
- Azure VNet Flow Logs: https://learn.microsoft.com/en-us/azure/network-watcher/vnet-flow-logs-overview
- LogicMonitor AWS Service Config: https://www.logicmonitor.com/support/aws-service-configuration-for-log-ingestion
- LogicMonitor Azure Resource Log Config: https://www.logicmonitor.com/support/azure-resource-log-configuration-for-log-ingestion
