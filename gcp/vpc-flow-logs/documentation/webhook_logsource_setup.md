# Webhook LogSource Configuration Guide

## GCP VPC Flow Logs Integration for LogicMonitor

---

## 1. Prerequisites

Before configuring the Webhook LogSource, ensure you have:

- A LogicMonitor portal with **LM Logs** enabled
- **Admin** or **Manage** permission on the portal
- The Cloud Function deployed and sending data (see [customer_guide.md](customer_guide.md))
- The webhook source name used during deployment (default: `GCP-VPC-FlowLogs`)

---

## 2. Create an API Only User and Bearer Token

The webhook endpoint requires a Bearer Token for authentication. This token is associated with an API Only User.

### 2.1 Create the API Only User

1. Navigate to **Settings > Users and Roles > Users**
2. Click **Add > API Only User**
3. Configure the user:
   - **Username:** `gcp-vpc-flowlogs-webhook` (or similar descriptive name)
   - **Roles:** Assign a role with **Manage** permission for **Logs & Traces**
   - **Status:** Active
4. Click **Save**

> The API Only User does not need device management permissions. It only needs
> Logs & Traces access to ingest webhook data.

### 2.2 Generate a Bearer Token

1. Open the API Only User you just created
2. Navigate to the **API Tokens** tab
3. Click **Add API Token**
4. Select **Bearer Token** as the token type
5. Set an appropriate expiration (or no expiration for long-running integrations)
6. Click **Generate**
7. **Copy the token immediately** — it will not be shown again

> Store this token securely. It will be used as the `LM_BEARER_TOKEN` value
> in the Cloud Function configuration and GCP Secret Manager.

### 2.3 Webhook URL Format

The webhook URL uses this format:

```
https://<portal>.logicmonitor.com/rest/api/v1/webhook/ingest/<sourceName>
```

For example, with portal `acmecorp` and default source name:

```
https://acmecorp.logicmonitor.com/rest/api/v1/webhook/ingest/GCP-VPC-FlowLogs
```

---

## 3. Create the Webhook LogSource

### 3.1 Navigate to LogSource Creation

1. Go to **Modules > My Module Toolbox**
2. Click **Add > LogSource**
3. Select **Webhook** as the type

### 3.2 Basic Settings

| Field | Value |
|-------|-------|
| Name | `GCP VPC Flow Logs` |
| Description | `Ingests GCP VPC Flow Logs via webhook from Cloud Function relay` |
| Group | `Cloud / GCP` (create if it does not exist) |
| Technical Notes | `Source: GCP Cloud Function triggered by Pub/Sub. See project documentation for architecture details.` |

### 3.3 Configure Filters

Filters determine which incoming webhook messages are processed by this LogSource.

Click **Add Filter** and configure:

| Attribute | Operation | Value |
|-----------|-----------|-------|
| SourceName | Equal | `GCP-VPC-FlowLogs` |

> Use "Equal" for exact source name matching. If you deploy multiple
> Cloud Functions with different source names, create separate LogSources
> for each, or use "Contain" with a common prefix.

### 3.4 Configure Log Fields (Tags)

Log Fields extract values from the incoming JSON payload and create searchable tags in LM Logs. The Cloud Function promotes key fields to the top level of the JSON payload as strings, so use the **Webhook Attribute** method (not Dynamic/JSON path).

**Important:** LM webhook LogSources only process **string values** as metadata. The Cloud Function in this project stringifies all top-level payload values. Non-string types (integers, booleans, objects) are silently ignored by the LogSource field extractor.

Click **Add Log Field** for each of the following:

| Key | Method | Value |
|-----|--------|-------|
| `src_ip` | Webhook Attribute | `src_ip` |
| `dest_ip` | Webhook Attribute | `dest_ip` |
| `src_port` | Webhook Attribute | `src_port` |
| `dest_port` | Webhook Attribute | `dest_port` |
| `protocol` | Webhook Attribute | `protocol` |
| `bytes_sent` | Webhook Attribute | `bytes_sent` |
| `packets_sent` | Webhook Attribute | `packets_sent` |
| `reporter` | Webhook Attribute | `reporter` |
| `vm_name` | Webhook Attribute | `vm_name` |
| `log_level` | Webhook Attribute | `Level` |
| `resource_type` | Webhook Attribute | `resourceType` |

> Protocol values are numeric strings (IANA protocol numbers): "6" = TCP,
> "17" = UDP, "1" = ICMP. All values are strings in the payload.

### 3.5 Configure Resource Mappings

Resource Mappings associate incoming logs with monitored devices in LogicMonitor.

Click **Add Resource Mapping** and configure:

| Key | Method | Value |
|-----|--------|-------|
| `system.gcp.resourcename` | Webhook Attribute | `vm_name` |

**Critical notes on resource mapping:**

- Use `system.gcp.resourcename` (not `system.hostname`). For GCP cloud-discovered devices, `system.hostname` contains a long composite string (e.g., `us-east1:project-id:computeengine:vm-name-hash`) that will never match the simple VM name from flow logs.
- Use the **Webhook Attribute** method (not Static or RegexGroup). The Cloud Function promotes `vm_name` to a top-level string key for this purpose.
- The GCP project must be added as a **Cloud Account** in LM for device auto-discovery. Without this, no devices exist to map to.
- If `vm_name` is not present in the payload (external traffic with no associated VM), the log will be stored as a "deviceless" log. Deviceless logs are still searchable and alertable in LM Logs.

### 3.6 Save the LogSource

1. Review all settings
2. Click **Save**
3. The LogSource will begin processing incoming webhook messages immediately

---

## 4. Verify Logs Are Flowing

### 4.1 Check LM Logs Page

1. Navigate to **Logs** in the LogicMonitor portal
2. In the search bar, enter: `sourceName = "GCP-VPC-FlowLogs"`
3. You should see flow log entries appearing within a few minutes of traffic generation

### 4.2 Verify Resource Mapping

1. Click on any log entry to expand its details
2. Confirm that:
   - The log is associated with the correct resource (VM)
   - All configured Log Fields (tags) are populated
   - The `src_ip`, `dest_ip`, `protocol`, and port fields are correct

### 4.3 Verify Tag Extraction

In the Logs search, use tag-based queries to confirm extraction is working:

```
src_ip = "10.0.0.5"
dest_port = 443
protocol = 6
vm_name = "web-frontend-01"
```

### 4.4 Common Verification Issues

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| No logs appearing | Cloud Function not receiving messages | Check Cloud Function logs, verify Pub/Sub topic and sink |
| Logs appear but no tags | Log Fields method or values incorrect | Verify Webhook Attribute method with correct top-level key names |
| Logs show under default logsource | Non-string payload values | Verify all payload values are strings. Integers/booleans cause silent LogSource skip. |
| Logs not mapped to devices | Resource mapping key mismatch | Use `system.gcp.resourcename` (not `system.hostname`). Ensure GCP Cloud Account is added to LM. |
| Logs mapped to wrong device | VM name collision | Use more specific mapping (e.g., project_id + vm_name) |

---

## 5. LogAlert Examples

LogAlerts trigger based on log content and can notify via escalation chains.

### 5.1 High Volume Traffic Alert

Detect flows with unusually high byte counts (potential data exfiltration).

1. Navigate to **Alerts > Alert Rules** or configure inline in the LogSource
2. Create a LogAlert:
   - **Name:** `GCP VPC - High Byte Count Flow`
   - **Query:** `bytes_sent > 100000000` (100 MB)
   - **Severity:** Warning
   - **Description:** `Large data transfer detected: {{src_ip}} -> {{dest_ip}}, {{bytes_sent}} bytes`

### 5.2 External Traffic to Sensitive Ports

Alert on external traffic reaching sensitive internal ports.

- **Name:** `GCP VPC - External Access to Sensitive Ports`
- **Query:** `dest_port IN (22, 3389, 5432, 3306, 27017) AND NOT src_ip STARTS_WITH "10."`
- **Severity:** Error
- **Description:** `External access to sensitive port: {{src_ip}}:{{src_port}} -> {{dest_ip}}:{{dest_port}}`

### 5.3 Traffic from Unexpected Regions

Alert on traffic originating from geographic regions outside your expected operating area.

- **Name:** `GCP VPC - Unexpected Source Region`
- **Query:** `src_location.country NOT IN ("usa", "can", "gbr")` (adjust to your expected countries)
- **Severity:** Warning
- **Description:** `Traffic from unexpected region: {{src_location.country}} ({{src_ip}} -> {{dest_ip}})`

### 5.4 High Connection Volume per Source

Alert when a single source IP generates an unusually high number of flow log entries (potential scanning or DDoS).

- **Name:** `GCP VPC - High Connection Volume`
- **Query:** `src_ip = "<specific_ip>"` with count threshold
- **Severity:** Warning
- **Description:** `High connection volume from {{src_ip}}: {{count}} flows in window`

> LogAlert query syntax may vary depending on your LM Logs version.
> Consult the LogicMonitor documentation for the latest query operators.

---

## 6. Advanced Configuration

### 6.1 Multiple Source Names

If you deploy separate Cloud Functions per GCP project, use distinct source names:

- `GCP-VPC-FlowLogs-Production`
- `GCP-VPC-FlowLogs-Staging`
- `GCP-VPC-FlowLogs-SharedServices`

The Webhook LogSource filter `SourceName Contain GCP-VPC-FlowLogs` will match all of them. Create separate LogSources if you need different Log Fields or Resource Mappings per project.

### 6.2 Excluding Noisy Traffic

Add LogSource-level filters to exclude known noisy traffic patterns. Use the top-level payload key names (not nested JSON paths):

| Attribute | Operation | Value | Purpose |
|-----------|-----------|-------|---------|
| `protocol` | Not Equal | `1` | Exclude ICMP |
| `dest_port` | Not Equal | `53` | Exclude DNS |

### 6.3 Custom Timestamp

By default, the webhook endpoint uses the receipt time as the log timestamp. To use the flow log's original timestamp, add a Log Field:

| Key | Method | Value |
|-----|--------|-------|
| `_timestamp` | Dynamic | `start_time` |

This instructs LM Logs to use the flow log's `start_time` as the log entry timestamp.
