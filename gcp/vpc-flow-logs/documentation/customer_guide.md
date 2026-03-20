# GCP VPC Flow Logs to LogicMonitor

## Deployment Guide

---

## 1. Overview

This integration ingests GCP VPC Flow Logs into LogicMonitor's LM Logs platform using a serverless Cloud Function. The Cloud Function acts as a thin relay: it receives flow log events from a Pub/Sub topic and forwards them as individual JSON objects to the LM Webhook endpoint.

**Key benefits:**

- No VMs or Fluentd to manage (fully serverless)
- No API rate limits (webhook endpoint is not subject to REST API rate limits)
- All log filtering, resource mapping, and tag extraction is configurable in the LM portal UI
- Auto-scales with traffic volume
- Minimal GCP cost (Pub/Sub + Cloud Function invocations)

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        GCP Environment                           │
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ VPC Subnets  │───>│ Cloud Logging │───>│ Log Router Sink  │    │
│  │ (Flow Logs)  │    │  (automatic)  │    │   (filter)       │    │
│  └─────────────┘    └──────────────┘    └────────┬─────────┘    │
│                                                   │              │
│                                          ┌────────v─────────┐   │
│                                          │   Pub/Sub Topic   │   │
│                                          │ (vpc-flowlogs-lm) │   │
│                                          └────────┬─────────┘   │
│                                                   │              │
│                                          ┌────────v─────────┐   │
│                                          │  Cloud Function   │   │
│                                          │  (relay to LM)    │   │
│                                          └────────┬─────────┘   │
│                                                   │              │
└───────────────────────────────────────────────────┼──────────────┘
                                                    │ HTTPS POST
                                                    v
                                    ┌───────────────────────────┐
                                    │     LogicMonitor Portal    │
                                    │                           │
                                    │  Webhook Endpoint:        │
                                    │  /rest/api/v1/webhook/    │
                                    │    ingest/GCP-VPC-FlowLogs│
                                    │                           │
                                    │  ┌─────────────────────┐  │
                                    │  │ Webhook LogSource    │  │
                                    │  │ - Filters            │  │
                                    │  │ - Log Fields (tags)  │  │
                                    │  │ - Resource Mappings  │  │
                                    │  └─────────────────────┘  │
                                    │                           │
                                    │  ┌─────────────────────┐  │
                                    │  │     LM Logs Page     │  │
                                    │  │ - Search / Query     │  │
                                    │  │ - Anomaly Detection  │  │
                                    │  │ - LogAlerts          │  │
                                    │  └─────────────────────┘  │
                                    └───────────────────────────┘
```

**Data flow:**

1. VPC subnets with Flow Logs enabled emit log entries to Cloud Logging
2. A Log Router sink filters for VPC flow log entries and exports them to Pub/Sub
3. Each Pub/Sub message triggers the Cloud Function via Eventarc
4. The Cloud Function extracts the flow log payload and POSTs it to the LM Webhook endpoint
5. The Webhook LogSource in LM parses the JSON, extracts tags, and maps to resources
6. Logs are searchable, alertable, and visible on the LM Logs page

---

## 3. Prerequisites

### 3.1 GCP Requirements

- A GCP project with billing enabled
- VPC subnets where you want flow logs captured
- Permissions to create:
  - Pub/Sub topics
  - Log Router sinks
  - Cloud Functions (2nd gen)
  - Secret Manager secrets
- `gcloud` CLI installed and authenticated, or access to GCP Cloud Shell

**Required IAM roles for the deployer:**

| Role | Purpose |
|------|---------|
| `roles/pubsub.admin` | Create Pub/Sub topic |
| `roles/logging.admin` | Create Log Router sink |
| `roles/cloudfunctions.admin` | Deploy Cloud Function |
| `roles/secretmanager.admin` | Create secrets |
| `roles/iam.serviceAccountUser` | Assign service account to function |

### 3.2 LogicMonitor Requirements

- A LogicMonitor portal with **LM Logs** enabled
- An API Only User with **Manage** permission for **Logs & Traces**
- A Bearer Token generated for that user

### 3.3 Software Requirements

- `gcloud` CLI (version 400.0.0 or later)
- `git` (to clone the repository)
- `bash` (shell scripts use bash)

---

## 4. Step 1: Configure VPC Flow Logs on Subnets

VPC Flow Logs must be enabled on each subnet you want to monitor. Logs are captured at the subnet level, not the VPC level.

### 4.1 Enable via Console

1. Navigate to **VPC Network > VPC Networks** in the GCP Console
2. Click on the VPC network containing your target subnets
3. Click on the subnet name
4. Click **Edit**
5. Under **Flow Logs**, select **On**
6. Configure:

| Parameter | Recommended (POC) | Recommended (Production) |
|-----------|-------------------|--------------------------|
| Aggregation Interval | 5 minutes | 5-15 minutes |
| Include metadata | All metadata | All metadata |
| Sample rate | 50% | 10-50% (tune per volume) |
| Log filtering | None | Optional: filter by port/protocol |

7. Click **Save**

### 4.2 Enable via gcloud

```bash
gcloud compute networks subnets update SUBNET_NAME \
    --region=REGION \
    --enable-flow-logs \
    --logging-aggregation-interval=interval-5-min \
    --logging-flow-sampling=0.5 \
    --logging-metadata=include-all
```

### 4.3 Cost Considerations

VPC Flow Logs generate Cloud Logging data billed at **$0.50/GiB** (first 50 GiB/month free). High-traffic environments can generate significant volume. Control costs with:

- **Sampling rate:** Reduce from 50% to 10% for high-traffic subnets
- **Aggregation interval:** Increase from 5 min to 15 min (fewer but larger entries)
- **Log filtering:** Enable at the subnet level to capture only specific ports or protocols
- **Log Router sink filter:** Narrow the sink to specific subnets or flow directions

---

## 5. Step 2: Run the GCP Setup Script

The setup script creates the Pub/Sub topic, Log Router sink, and Secret Manager entries.

### 5.1 Clone the Repository

```bash
git clone https://github.com/ryanmat/lm-gpcVPCFlowLogs.git
cd lm-gpcVPCFlowLogs
```

### 5.2 Run the Setup Script

```bash
./infra/setup_gcp.sh \
    --project YOUR_PROJECT_ID \
    --region YOUR_REGION \
    --company YOUR_LM_PORTAL_NAME
```

The script will:

1. Enable required GCP APIs (Pub/Sub, Cloud Functions, Secret Manager, etc.)
2. Create the Pub/Sub topic `vpc-flowlogs-lm`
3. Create a Log Router sink that exports VPC Flow Logs to the topic
4. Grant the sink's service account permission to publish to the topic
5. Create Secret Manager entries for `lm-company-name` and `lm-bearer-token`

You will be prompted to enter the LM Bearer Token interactively. Have it ready from the LM portal (see [webhook_logsource_setup.md](webhook_logsource_setup.md), Section 2).

### 5.3 What the Setup Creates

| Resource | Name | Purpose |
|----------|------|---------|
| Pub/Sub Topic | `vpc-flowlogs-lm` | Receives flow log entries from Cloud Logging |
| Log Router Sink | `vpc-flowlogs-to-lm` | Exports flow logs from Cloud Logging to Pub/Sub |
| Secret | `lm-company-name` | LM portal name for URL construction |
| Secret | `lm-bearer-token` | Bearer token for webhook authentication |

---

## 6. Step 3: Deploy the Cloud Function

### 6.1 Run the Deployment Script

```bash
./infra/deploy_function.sh \
    --project YOUR_PROJECT_ID \
    --region YOUR_REGION
```

### 6.2 Deployment Options

| Flag | Default | Description |
|------|---------|-------------|
| `--function` | `vpc-flowlogs-to-lm` | Cloud Function name |
| `--topic` | `vpc-flowlogs-lm` | Pub/Sub topic to trigger from |
| `--source-name` | `GCP-VPC-FlowLogs` | Webhook source name in LM |
| `--memory` | `256Mi` | Function memory allocation |
| `--timeout` | `60` | Function timeout in seconds |
| `--use-ingest` | (not set) | Use Phase 1 Ingest API instead of Webhook |
| `--service-account` | (auto) | Custom service account for the function |

### 6.3 Verify Deployment

Check the function status:

```bash
gcloud functions describe vpc-flowlogs-to-lm \
    --project=YOUR_PROJECT_ID \
    --region=YOUR_REGION \
    --gen2
```

Check function logs:

```bash
gcloud functions logs read vpc-flowlogs-to-lm \
    --project=YOUR_PROJECT_ID \
    --region=YOUR_REGION \
    --gen2 \
    --limit=20
```

---

## 7. Step 4: Configure the Webhook LogSource in LogicMonitor

Follow the detailed setup guide: [webhook_logsource_setup.md](webhook_logsource_setup.md)

Summary of steps:

1. Create an API Only User with Logs & Traces Manage permission
2. Generate a Bearer Token for that user
3. Create a Webhook LogSource named "GCP VPC Flow Logs"
4. Configure filters (SourceName contains "GCP-VPC-FlowLogs")
5. Configure Log Fields for tag extraction (src_ip, dest_ip, protocol, etc.)
6. Configure Resource Mapping (system.hostname from src_instance.vm_name)

---

## 8. Step 5: Verify End-to-End Flow

### 8.1 Generate Test Traffic

From a VM within the VPC (with flow logs enabled on its subnet):

```bash
./infra/generate_test_traffic.sh \
    --target TARGET_VM_IP \
    --project YOUR_PROJECT_ID
```

This generates HTTP, HTTPS, SSH, and DNS traffic plus a burst of requests for volume.

### 8.2 Check Cloud Logging (Wait 5-10 Minutes)

VPC Flow Logs are aggregated over the configured interval. After generating traffic, wait at least 5-10 minutes.

```bash
gcloud logging read \
    'resource.type="gce_subnetwork" log_id("compute.googleapis.com/vpc_flows")' \
    --project=YOUR_PROJECT_ID \
    --limit=10 \
    --format=json
```

### 8.3 Check Cloud Function Logs

```bash
gcloud functions logs read vpc-flowlogs-to-lm \
    --project=YOUR_PROJECT_ID \
    --region=YOUR_REGION \
    --gen2 \
    --limit=20
```

Look for log lines like:

```
Processed flow log: 10.128.0.5 -> 10.128.0.10, bytes=1234, endpoint=webhook, success=True
```

### 8.4 Check LM Logs

1. Navigate to **Logs** in the LogicMonitor portal
2. Search for: `sourceName = "GCP-VPC-FlowLogs"`
3. Verify that:
   - Flow log entries are appearing
   - Tags (src_ip, dest_ip, protocol, etc.) are populated
   - Resource mapping is working (logs associated with correct devices)

---

## 9. Tuning and Cost Optimization

### 9.1 Adjusting Sampling Rate

The sampling rate controls what percentage of flows are logged. Reduce it for high-traffic subnets:

```bash
gcloud compute networks subnets update SUBNET_NAME \
    --region=REGION \
    --logging-flow-sampling=0.1   # 10% sampling
```

### 9.2 Adjusting Aggregation Interval

Longer intervals mean fewer, larger log entries:

```bash
gcloud compute networks subnets update SUBNET_NAME \
    --region=REGION \
    --logging-aggregation-interval=interval-15-min
```

### 9.3 Log Router Sink Filter Examples

Narrow the sink filter to reduce volume. Edit the sink in the GCP Console or via gcloud.

**Only specific subnets:**

```
resource.type="gce_subnetwork"
log_id("compute.googleapis.com/vpc_flows")
resource.labels.subnetwork_name="my-subnet"
```

**Only TCP traffic:**

```
resource.type="gce_subnetwork"
log_id("compute.googleapis.com/vpc_flows")
jsonPayload.connection.protocol=6
```

**Only traffic on specific ports:**

```
resource.type="gce_subnetwork"
log_id("compute.googleapis.com/vpc_flows")
(jsonPayload.connection.dest_port=443 OR jsonPayload.connection.dest_port=80)
```

**Exclude internal-only traffic (external flows only):**

```
resource.type="gce_subnetwork"
log_id("compute.googleapis.com/vpc_flows")
jsonPayload.reporter="DEST"
NOT jsonPayload.src_instance:*
```

### 9.4 Webhook LogSource Filters

In the LM portal, you can add include/exclude filters on the Webhook LogSource to drop logs before they are indexed. This reduces LM Logs ingestion costs.

### 9.5 Estimated Costs

| Component | Cost Factor |
|-----------|-------------|
| VPC Flow Logs (Cloud Logging) | $0.50/GiB ingested (first 50 GiB free/month) |
| Pub/Sub | $40/TiB of message delivery |
| Cloud Function | $0.40/million invocations + compute time |
| Secret Manager | $0.06/10,000 access operations |
| LM Logs | Based on your LM Logs ingestion tier |

---

## 10. Troubleshooting

### 10.1 No Logs Appearing in Pub/Sub

**Symptoms:** Cloud Function is not firing, no messages in Pub/Sub.

**Check:**

1. Verify VPC Flow Logs are enabled on the subnet:
   ```bash
   gcloud compute networks subnets describe SUBNET_NAME \
       --region=REGION \
       --format="get(enableFlowLogs)"
   ```

2. Verify flow logs exist in Cloud Logging:
   ```bash
   gcloud logging read \
       'resource.type="gce_subnetwork" log_id("compute.googleapis.com/vpc_flows")' \
       --limit=5
   ```

3. Verify the Log Router sink exists and is not disabled:
   ```bash
   gcloud logging sinks describe vpc-flowlogs-to-lm
   ```

4. Verify the sink's service account has publish permission on the topic:
   ```bash
   gcloud pubsub topics get-iam-policy vpc-flowlogs-lm
   ```

### 10.2 Cloud Function Errors

**Symptoms:** Function is receiving messages but failing.

**Check function logs:**

```bash
gcloud functions logs read vpc-flowlogs-to-lm \
    --project=YOUR_PROJECT_ID \
    --region=YOUR_REGION \
    --gen2 \
    --limit=50
```

**Common errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `ValueError: LM_COMPANY_NAME` | Missing environment variable | Check Secret Manager and function deployment |
| `ValueError: LM_BEARER_TOKEN` | Missing bearer token | Add secret to Secret Manager and redeploy |
| `requests.ConnectionError` | Cannot reach LM endpoint | Check network/firewall, verify portal name |
| `401 Unauthorized` | Invalid bearer token | Regenerate token in LM portal, update secret |
| `Skipping malformed message` | Non-flow-log message in topic | Expected for test messages; real flow logs should parse correctly |

### 10.3 Logs in LM But Not Mapped to Resources

**Symptoms:** Logs appear in LM Logs but show as "deviceless" (not associated with a resource).

**Causes and fixes:**

1. **VM name mismatch:** The `src_instance.vm_name` in flow logs must match `system.hostname` of a monitored device in LM. Ensure GCP VMs are monitored with matching hostnames.

2. **External traffic:** Flow logs from external sources (no `src_instance`) will always be deviceless. This is expected behavior.

3. **Resource mapping not configured:** Verify the Webhook LogSource has the Resource Mapping set to `system.hostname = src_instance.vm_name`.

### 10.4 Volume or Cost Too High

**Symptoms:** Too many log entries, high Cloud Logging or LM Logs costs.

**Actions (in order of impact):**

1. Reduce sampling rate on high-traffic subnets (see Section 9.1)
2. Increase aggregation interval (see Section 9.2)
3. Narrow the Log Router sink filter (see Section 9.3)
4. Add Webhook LogSource filters to drop unwanted traffic in LM
5. Disable flow logs on subnets that do not need monitoring

### 10.5 Function Timeout or Memory Errors

**Symptoms:** Function crashes with timeout or OOM errors.

The default configuration (256Mi memory, 60s timeout) handles normal flow log volume. If you experience issues:

```bash
# Increase memory
./infra/deploy_function.sh --project YOUR_PROJECT --region YOUR_REGION --memory 512Mi

# Increase timeout
./infra/deploy_function.sh --project YOUR_PROJECT --region YOUR_REGION --timeout 120
```

---

## Appendix A: VPC Flow Log Fields

Each flow log entry contains these fields:

| Field | Description | Example |
|-------|-------------|---------|
| `connection.src_ip` | Source IP address | `10.128.0.5` |
| `connection.dest_ip` | Destination IP address | `10.128.0.10` |
| `connection.src_port` | Source port | `52340` |
| `connection.dest_port` | Destination port | `443` |
| `connection.protocol` | IANA protocol number | `6` (TCP) |
| `bytes_sent` | Bytes transferred in the flow | `"1234"` |
| `packets_sent` | Packets transferred | `"10"` |
| `start_time` | Flow start timestamp | `2026-02-26T12:00:00Z` |
| `end_time` | Flow end timestamp | `2026-02-26T12:00:05Z` |
| `reporter` | Which endpoint reported | `SRC` or `DEST` |
| `src_instance.vm_name` | Source VM name (if internal) | `web-frontend-01` |
| `src_instance.project_id` | Source VM project | `my-project` |
| `src_vpc.vpc_name` | Source VPC network name | `default` |
| `src_vpc.subnetwork_name` | Source subnet name | `default` |
| `src_gke_details` | GKE pod/service details (if GKE) | (nested object) |
| `src_location` / `dest_location` | Geographic info (external IPs) | country, region, ASN |

## Appendix B: Protocol Number Reference

| Number | Protocol |
|--------|----------|
| 1 | ICMP |
| 6 | TCP |
| 17 | UDP |
| 50 | ESP |
| 47 | GRE |
