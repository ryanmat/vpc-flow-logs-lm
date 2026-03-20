# KPMG Logging POC - Implementation Plan

## Overview

This plan breaks down the KPMG network logging and cost attribution POC into small, iterative chunks that build on each other. Each phase contains discrete prompts for Claude Code to execute in a test-driven manner.

---

## Phase 0: Project Setup and Environment Validation

### 0.1 Project Structure and Configuration

**Objective:** Create project structure and validate environment access.

```text
[Prompt 0.1: Project Structure Setup]

Context: We are building a LogicMonitor-based network monitoring and cost attribution POC for KPMG Canada. The project involves ingesting flow logs from Azure VNet and AWS VPC into LM Logs, monitoring WAF/Shield/Network Firewall, and creating dashboards for egress cost attribution.

Task: Create the project directory structure with the following layout:

kpmg-logging-poc/
  scripts/
    aws/
    azure/
    common/
  datasources/
  propertysources/
  dashboards/
  configs/
  tests/
  docs/

Create a README.md in the root explaining the project purpose and structure.

Create a .env.example file with placeholders for:
- LM_COMPANY
- LM_ACCESS_ID  
- LM_ACCESS_KEY
- LM_BEARER_TOKEN
- AZURE_SUBSCRIPTION_ID
- AZURE_RESOURCE_GROUP
- AZURE_REGION
- AZURE_CLIENT_ID
- AWS_DEFAULT_REGION
- AWS_ACCOUNT_ID

Create scripts/common/load-env.sh that sources .env if it exists.

Acceptance Criteria:
- Directory structure created
- README.md exists with clear documentation
- .env.example has all required variables
- load-env.sh sources environment variables
```

### 0.2 Environment Validation Scripts

```text
[Prompt 0.2: Environment Validation Scripts]

Context: We need to validate that the user's environment is properly configured before proceeding with deployments.

Task: Create validation scripts:

1. scripts/common/validate-lm.sh
   - Check LM_COMPANY, LM_ACCESS_ID, LM_ACCESS_KEY are set
   - Make a test API call to LogicMonitor to verify credentials
   - Use: curl -s -H "Authorization: LMv1 $LM_ACCESS_ID:$SIGNATURE:$EPOCH" "https://$LM_COMPANY.logicmonitor.com/santaba/rest/setting/accesslogs?size=1"
   - Exit 0 if successful, exit 1 with error message if not

2. scripts/azure/validate-azure.sh
   - Check Azure CLI is installed (az --version)
   - Check user is logged in (az account show)
   - Verify AZURE_SUBSCRIPTION_ID matches current subscription
   - Exit 0 if successful, exit 1 with error message if not

3. scripts/aws/validate-aws.sh
   - Check AWS CLI is installed (aws --version)
   - Check credentials are configured (aws sts get-caller-identity)
   - Verify AWS_ACCOUNT_ID matches current identity
   - Exit 0 if successful, exit 1 with error message if not

4. scripts/common/validate-all.sh
   - Run all three validation scripts
   - Report overall status

Acceptance Criteria:
- Each script is executable (chmod +x)
- Scripts provide clear error messages on failure
- Scripts exit with appropriate codes
- validate-all.sh aggregates results
```

---

## Phase 1: AWS VPC Flow Logs Pipeline

### 1.1 CloudWatch Log Group Setup

```text
[Prompt 1.1: AWS CloudWatch Log Group for VPC Flow Logs]

Context: AWS VPC Flow Logs require a CloudWatch Log Group as a destination. LogicMonitor expects the log stream name to match the instance ID for proper resource mapping. We need to create the log group and IAM role.

Task: Create scripts/aws/setup-vpc-flow-log-group.sh that:

1. Creates a CloudWatch Log Group named "/aws/vpc/flowlogs"
   - Use: aws logs create-log-group --log-group-name "/aws/vpc/flowlogs"
   - Handle case where log group already exists (exit gracefully)

2. Sets retention policy to 7 days to control costs
   - Use: aws logs put-retention-policy --log-group-name "/aws/vpc/flowlogs" --retention-in-days 7

3. Creates an IAM role "VPCFlowLogsRole" with trust policy for vpc-flow-logs.amazonaws.com
   - Trust policy allows vpc-flow-logs.amazonaws.com to assume the role
   - Attach policy allowing logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents, logs:DescribeLogGroups, logs:DescribeLogStreams

4. Outputs the role ARN for use in later steps

Prerequisites check at script start:
- Run validate-aws.sh first

Include error handling throughout. Use set -e for strict mode.

Acceptance Criteria:
- Log group created or already exists
- Retention policy set to 7 days
- IAM role created with correct trust relationship
- Policy attached with required permissions
- Role ARN output to stdout
```

### 1.2 Enable VPC Flow Logs

```text
[Prompt 1.2: Enable VPC Flow Logs with Custom Format]

Context: LogicMonitor requires instance-id as the FIRST field in VPC Flow Logs for proper resource mapping. We need to enable flow logs on the target VPC with a custom format.

Task: Create scripts/aws/enable-vpc-flow-logs.sh that:

1. Accepts parameters:
   - VPC_ID (required): The VPC to enable flow logs on
   - IAM_ROLE_ARN (required): The role ARN from previous step
   - LOG_GROUP_NAME (optional, default: /aws/vpc/flowlogs)

2. Defines the custom log format with instance-id first:
   FLOW_LOG_FORMAT='${instance-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status}'

3. Creates the VPC Flow Log:
   aws ec2 create-flow-logs \
     --resource-type VPC \
     --resource-ids $VPC_ID \
     --traffic-type ALL \
     --log-destination-type cloud-watch-logs \
     --log-group-name $LOG_GROUP_NAME \
     --deliver-logs-permission-arn $IAM_ROLE_ARN \
     --log-format "$FLOW_LOG_FORMAT"

4. Verifies flow log was created:
   aws ec2 describe-flow-logs --filter "Name=resource-id,Values=$VPC_ID"

5. Outputs the Flow Log ID

Include usage message if parameters missing.

Acceptance Criteria:
- Script accepts VPC_ID and IAM_ROLE_ARN parameters
- Custom format has instance-id as first field
- Flow log created successfully
- Flow log ID output to stdout
```

### 1.3 Deploy LMLogsForwarder Lambda

```text
[Prompt 1.3: Deploy LMLogsForwarder via CloudFormation]

Context: LogicMonitor provides a CloudFormation template that deploys the LMLogsForwarder Lambda function. This Lambda forwards logs from CloudWatch to LM Logs.

Task: Create scripts/aws/deploy-lm-logs-forwarder.sh that:

1. Loads environment variables (source ../common/load-env.sh)

2. Validates required LM variables are set:
   - LM_ACCESS_ID
   - LM_ACCESS_KEY
   - LM_COMPANY

3. Defines stack parameters:
   STACK_NAME="lm-logs-forwarder"
   TEMPLATE_URL="https://logicmonitor-logs-forwarder.s3.amazonaws.com/source/latest.yaml"

4. Deploys the CloudFormation stack:
   aws cloudformation create-stack \
     --stack-name $STACK_NAME \
     --template-url $TEMPLATE_URL \
     --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
     --parameters \
       ParameterKey=FunctionName,ParameterValue=LMLogsForwarder \
       ParameterKey=LMAccessId,ParameterValue=$LM_ACCESS_ID \
       ParameterKey=LMAccessKey,ParameterValue=$LM_ACCESS_KEY \
       ParameterKey=LMCompanyName,ParameterValue=$LM_COMPANY

5. Waits for stack creation to complete:
   aws cloudformation wait stack-create-complete --stack-name $STACK_NAME

6. On failure, checks if stack already exists and reports status

7. Outputs the Lambda function ARN

Acceptance Criteria:
- Environment variables validated
- CloudFormation stack deployed successfully
- Script handles existing stack gracefully
- Lambda ARN output to stdout
```

### 1.4 Create Lambda Subscription Filter

```text
[Prompt 1.4: Create CloudWatch Logs Subscription Filter]

Context: The LMLogsForwarder Lambda needs a subscription filter to receive logs from the VPC Flow Logs CloudWatch Log Group.

Task: Create scripts/aws/create-subscription-filter.sh that:

1. Accepts parameters:
   - LOG_GROUP_NAME (optional, default: /aws/vpc/flowlogs)
   - FILTER_NAME (optional, default: LMLogsForwarder)

2. Gets the Lambda function ARN:
   LAMBDA_ARN=$(aws lambda get-function --function-name LMLogsForwarder --query 'Configuration.FunctionArn' --output text)

3. Adds Lambda permission for CloudWatch Logs to invoke:
   aws lambda add-permission \
     --function-name LMLogsForwarder \
     --statement-id "CloudWatchLogsInvoke-${LOG_GROUP_NAME//\//-}" \
     --action "lambda:InvokeFunction" \
     --principal "logs.amazonaws.com" \
     --source-arn "arn:aws:logs:${AWS_DEFAULT_REGION}:${AWS_ACCOUNT_ID}:log-group:${LOG_GROUP_NAME}:*"

4. Creates the subscription filter:
   aws logs put-subscription-filter \
     --log-group-name $LOG_GROUP_NAME \
     --filter-name $FILTER_NAME \
     --filter-pattern "" \
     --destination-arn $LAMBDA_ARN

5. Verifies subscription filter exists:
   aws logs describe-subscription-filters --log-group-name $LOG_GROUP_NAME

Handle case where permission or filter already exists.

Acceptance Criteria:
- Lambda permission added for CloudWatch Logs
- Subscription filter created
- Filter links log group to Lambda function
```

### 1.5 Verify AWS VPC Flow Logs in LM Logs

```text
[Prompt 1.5: Verify VPC Flow Logs in LogicMonitor]

Context: After the pipeline is deployed, we need to verify that logs are flowing into LogicMonitor's LM Logs.

Task: Create scripts/aws/verify-vpc-flow-logs.sh that:

1. Waits for a configurable period (default 5 minutes) for logs to propagate

2. Uses the LogicMonitor API to query LM Logs:
   - Endpoint: POST /log/ingest/rest/query
   - Query: Search for logs from the last 10 minutes with source containing "vpc" or "flow"

3. Alternatively, provides instructions for manual verification:
   - Navigate to LM Logs in LogicMonitor portal
   - Search for logs from the VPC
   - Verify resource mapping is correct

4. Outputs success/failure status with guidance

Create a separate test script: tests/test-aws-vpc-flow.sh that:
1. Generates test traffic (curl to external endpoint from EC2, if accessible)
2. Runs the verification script
3. Reports pass/fail

Acceptance Criteria:
- Script waits appropriate time for log propagation
- API query or manual verification instructions provided
- Clear success/failure output
```

---

## Phase 2: AWS WAF/Shield/Network Firewall Monitoring

### 2.1 Verify OOB AWS Security DataSources

```text
[Prompt 2.1: Verify AWS WAF/Shield/Network Firewall DataSources]

Context: LogicMonitor may have out-of-box DataSources for AWS WAF, Shield, and Network Firewall. We need to verify what exists and what needs to be custom-built.

Task: Create scripts/aws/verify-security-datasources.sh that:

1. Uses the LogicMonitor API to search for existing DataSources:
   GET /setting/datasources?filter=name~"AWS_WAF"
   GET /setting/datasources?filter=name~"AWS_Shield"  
   GET /setting/datasources?filter=name~"AWS_NetworkFirewall"

2. For each DataSource found, report:
   - DataSource name
   - Number of datapoints
   - AppliesTo criteria

3. Creates a report file: docs/aws-security-datasource-status.md
   - Lists what is available OOB
   - Lists what needs to be custom-built

4. For OOB DataSources, verifies they are applied to discovered resources:
   - Check if AWS resources have instances from these DataSources

Note: If API calls fail due to permissions, provide manual verification steps.

Acceptance Criteria:
- Script queries LM API for DataSource existence
- Report generated documenting OOB vs custom needs
- Clear guidance on next steps
```

### 2.2 Enable WAF Logging to CloudWatch

```text
[Prompt 2.2: Enable AWS WAF Logging to CloudWatch]

Context: AWS WAF can log to CloudWatch Logs, S3, or Kinesis Firehose. We will use CloudWatch Logs for simplicity and reuse the LMLogsForwarder Lambda.

Task: Create scripts/aws/enable-waf-logging.sh that:

1. Accepts parameters:
   - WEB_ACL_ARN (required): The WAF Web ACL to enable logging on
   - LOG_GROUP_NAME (optional, default: aws-waf-logs-kpmg)

2. Creates a CloudWatch Log Group for WAF (name MUST start with "aws-waf-logs-"):
   aws logs create-log-group --log-group-name "aws-waf-logs-kpmg"

3. Sets retention to 7 days:
   aws logs put-retention-policy --log-group-name "aws-waf-logs-kpmg" --retention-in-days 7

4. Enables WAF logging:
   aws wafv2 put-logging-configuration \
     --logging-configuration '{
       "ResourceArn": "'$WEB_ACL_ARN'",
       "LogDestinationConfigs": ["arn:aws:logs:'$AWS_DEFAULT_REGION':'$AWS_ACCOUNT_ID':log-group:aws-waf-logs-kpmg"]
     }'

5. Creates subscription filter to LMLogsForwarder (reuse logic from 1.4):
   - Add Lambda permission
   - Create subscription filter

6. Verifies logging is enabled:
   aws wafv2 get-logging-configuration --resource-arn $WEB_ACL_ARN

Acceptance Criteria:
- CloudWatch Log Group created with correct naming convention
- WAF logging enabled pointing to log group
- Subscription filter connects to LMLogsForwarder
```

### 2.3 Custom WAF CloudWatch DataSource (If Needed)

```text
[Prompt 2.3: Create Custom AWS WAF CloudWatch DataSource]

Context: If LogicMonitor does not have an OOB WAF DataSource, we need to create one that pulls CloudWatch metrics.

Prerequisites: Check docs/aws-security-datasource-status.md from Prompt 2.1. If AWS_WAF DataSource exists, skip this prompt.

Task: Create datasources/AWS_WAF_Custom.xml with:

1. Basic DataSource definition:
   - Name: AWS_WAF_Custom
   - Display Name: AWS WAF - Custom Metrics
   - AppliesTo: system.aws.resourcetype == "wafv2-webacl" || hasCategory("AWS/WAFV2")
   - Collector: AWS CLOUDWATCH
   - Multi-instance: Yes
   - Active Discovery: AWS CLOUDWATCH

2. Active Discovery configuration:
   - Namespace: AWS/WAFV2
   - Metric: AllowedRequests
   - Device Dimension Name: WebACL
   - Device Dimension Value: ##system.aws.resourceid##
   - Instance Dimension Name: Rule

3. Datapoints (Normal, using metric paths):
   - AllowedRequests: AWS/WAFV2>WebACL:##system.aws.resourceid##>Rule:##wildvalue##>AllowedRequests>Sum
   - BlockedRequests: AWS/WAFV2>WebACL:##system.aws.resourceid##>Rule:##wildvalue##>BlockedRequests>Sum
   - CountedRequests: AWS/WAFV2>WebACL:##system.aws.resourceid##>Rule:##wildvalue##>CountedRequests>Sum
   - PassedRequests: AWS/WAFV2>WebACL:##system.aws.resourceid##>Rule:##wildvalue##>PassedRequests>Sum

4. Graph definitions:
   - WAF Request Counts: Line graph with all four metrics

Create scripts/aws/import-waf-datasource.sh to import via API:
   POST /setting/datasources
   Content-Type: application/xml
   Body: <contents of AWS_WAF_Custom.xml>

Acceptance Criteria:
- DataSource XML is valid
- AppliesTo correctly targets WAF resources
- Metric paths follow CloudWatch convention
- Import script handles success/failure
```

### 2.4 Custom Shield CloudWatch DataSource (If Needed)

```text
[Prompt 2.4: Create Custom AWS Shield Advanced CloudWatch DataSource]

Context: AWS Shield Advanced publishes metrics to CloudWatch when attacks are detected. We need a DataSource to collect these.

Prerequisites: Check docs/aws-security-datasource-status.md. If AWS_Shield DataSource exists with required metrics, skip this prompt.

Task: Create datasources/AWS_Shield_Custom.xml with:

1. Basic DataSource definition:
   - Name: AWS_Shield_Custom
   - Display Name: AWS Shield Advanced
   - AppliesTo: system.aws.accountid && isAWSShieldAdvancedSubscribed()
   - Collector: AWS CLOUDWATCH
   - Multi-instance: Yes (by protected resource)
   - Active Discovery: AWS CLOUDWATCH

   Note: Shield metrics use resource ARNs as dimensions. May need script-based discovery.

2. Alternative approach - Script-based collection:
   - Use AWS Shield API: aws shield list-protections
   - For each protection, query CloudWatch for metrics

3. Datapoints:
   - DDoSDetected: AWS/DDoSProtection>ResourceArn:##wildvalue##>DDoSDetected>Maximum
   - DDoSAttackBitsPerSecond: AWS/DDoSProtection>ResourceArn:##wildvalue##>DDoSAttackBitsPerSecond>Maximum
   - DDoSAttackPacketsPerSecond: AWS/DDoSProtection>ResourceArn:##wildvalue##>DDoSAttackPacketsPerSecond>Maximum
   - DDoSAttackRequestsPerSecond: AWS/DDoSProtection>ResourceArn:##wildvalue##>DDoSAttackRequestsPerSecond>Maximum

4. Alert thresholds:
   - DDoSDetected > 0: Warning

Note: Shield Advanced requires subscription. Script should check if subscribed before attempting to collect.

Acceptance Criteria:
- DataSource handles Shield subscription check
- Metrics collected for protected resources
- Alert on DDoS detection
```

### 2.5 Custom Network Firewall DataSource (If Needed)

```text
[Prompt 2.5: Create Custom AWS Network Firewall CloudWatch DataSource]

Context: AWS Network Firewall publishes packet metrics to CloudWatch. We need to collect dropped, passed, and received packet counts.

Prerequisites: Check docs/aws-security-datasource-status.md. If AWS_NetworkFirewall DataSource exists, skip this prompt.

Task: Create datasources/AWS_NetworkFirewall_Custom.xml with:

1. Basic DataSource definition:
   - Name: AWS_NetworkFirewall_Custom
   - Display Name: AWS Network Firewall
   - AppliesTo: system.aws.resourcetype == "network-firewall"
   - Collector: AWS CLOUDWATCH
   - Multi-instance: Yes (by AZ/Endpoint)
   - Active Discovery: AWS CLOUDWATCH

2. Active Discovery:
   - Namespace: AWS/NetworkFirewall
   - Metric: PassedPackets
   - Device Dimension Name: FirewallName
   - Device Dimension Value: ##system.aws.resourceid##
   - Instance Dimension Name: AvailabilityZone

3. Datapoints:
   - DroppedPackets: AWS/NetworkFirewall>FirewallName:##system.aws.resourceid##>AvailabilityZone:##wildvalue##>DroppedPackets>Sum
   - PassedPackets: AWS/NetworkFirewall>FirewallName:##system.aws.resourceid##>AvailabilityZone:##wildvalue##>PassedPackets>Sum
   - ReceivedPackets: AWS/NetworkFirewall>FirewallName:##system.aws.resourceid##>AvailabilityZone:##wildvalue##>ReceivedPackets>Sum

4. Calculated datapoint:
   - DropRate: (DroppedPackets / ReceivedPackets) * 100

5. Graphs:
   - Firewall Packet Flow: Line graph with Dropped, Passed, Received
   - Drop Rate Percentage: Line graph

Acceptance Criteria:
- DataSource targets Network Firewall resources
- Metrics collected per AZ
- Drop rate calculated
```

---

## Phase 3: Azure VNet Flow Logs Pipeline

### 3.1 Create Azure Resource Group and Event Hub

```text
[Prompt 3.1: Create Azure Event Hub for Log Ingestion]

Context: Azure VNet Flow Logs require an Event Hub as a destination for real-time streaming. The Azure Function will consume from this Event Hub and forward to LogicMonitor.

Task: Create scripts/azure/setup-event-hub.sh that:

1. Loads environment variables and validates Azure CLI login

2. Creates a resource group for the log ingestion infrastructure:
   RESOURCE_GROUP="lm-logs-${LM_COMPANY}-${AZURE_REGION}-rg"
   az group create --name $RESOURCE_GROUP --location $AZURE_REGION

3. Creates an Event Hub Namespace:
   NAMESPACE="lm-logs-${LM_COMPANY}-${AZURE_REGION}"
   az eventhubs namespace create \
     --name $NAMESPACE \
     --resource-group $RESOURCE_GROUP \
     --location $AZURE_REGION \
     --sku Standard

4. Creates an Event Hub within the namespace:
   az eventhubs eventhub create \
     --name "log-hub" \
     --namespace-name $NAMESPACE \
     --resource-group $RESOURCE_GROUP \
     --message-retention 1 \
     --partition-count 2

5. Gets the connection string:
   CONNECTION_STRING=$(az eventhubs namespace authorization-rule keys list \
     --resource-group $RESOURCE_GROUP \
     --namespace-name $NAMESPACE \
     --name RootManageSharedAccessKey \
     --query primaryConnectionString -o tsv)

6. Outputs:
   - Resource Group name
   - Event Hub Namespace name
   - Event Hub name
   - Connection string (for Azure Function config)

Store connection string in configs/azure-eventhub-connection.txt (gitignore this file)

Acceptance Criteria:
- Resource group created
- Event Hub Namespace created
- Event Hub "log-hub" created
- Connection string retrieved and stored
```

### 3.2 Deploy Azure Function via Terraform

```text
[Prompt 3.2: Deploy Azure Function for Log Forwarding]

Context: LogicMonitor provides a Terraform configuration in the lm-logs-azure repository to deploy the Azure Function that forwards logs to LM.

Task: Create scripts/azure/deploy-azure-function.sh that:

1. Downloads the Terraform configuration:
   curl -o configs/azure-function/deploy.tf https://raw.githubusercontent.com/logicmonitor/lm-logs-azure/master/deploy.tf

2. Creates a terraform.tfvars file in configs/azure-function/:
   lm_company_name     = "${LM_COMPANY}"
   lm_access_id        = "${LM_ACCESS_ID}"
   lm_access_key       = "${LM_ACCESS_KEY}"
   azure_region        = "${AZURE_REGION}"
   azure_client_id     = "${AZURE_CLIENT_ID}"

3. Initializes and applies Terraform:
   cd configs/azure-function
   terraform init
   terraform plan -var-file=terraform.tfvars -out=tf.plan
   terraform apply tf.plan

4. Handles the known issue where Function doesn't start:
   - After deployment, restart the Function App via Azure CLI:
   FUNCTION_APP_NAME=$(terraform output -raw function_app_name)
   az functionapp restart --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP

5. Verifies Function is running:
   az functionapp show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --query "state"

Alternative: If Terraform not available, create scripts/azure/deploy-azure-function-arm.sh using ARM template from:
https://raw.githubusercontent.com/logicmonitor/lm-logs-azure/master/arm-template-deployment/

Acceptance Criteria:
- Azure Function deployed
- Function App running
- Function connected to Event Hub
```

### 3.3 Enable VNet Flow Logs

```text
[Prompt 3.3: Enable Azure VNet Flow Logs]

Context: Azure VNet Flow Logs are managed through Network Watcher. We need to enable flow logs on the target VNet and configure them to send to our Event Hub.

Task: Create scripts/azure/enable-vnet-flow-logs.sh that:

1. Accepts parameters:
   - VNET_NAME (required): Target VNet name
   - VNET_RESOURCE_GROUP (required): VNet's resource group

2. Ensures Network Watcher exists in the region:
   az network watcher configure --enabled true --resource-group NetworkWatcherRG --locations $AZURE_REGION

3. Creates a Storage Account for flow logs (required by Azure):
   STORAGE_ACCOUNT="lmflowlogs${LM_COMPANY}${RANDOM}"
   az storage account create \
     --name $STORAGE_ACCOUNT \
     --resource-group $RESOURCE_GROUP \
     --location $AZURE_REGION \
     --sku Standard_LRS

4. Gets the VNet resource ID:
   VNET_ID=$(az network vnet show --name $VNET_NAME --resource-group $VNET_RESOURCE_GROUP --query id -o tsv)

5. Enables VNet Flow Logs with Event Hub destination:
   az network watcher flow-log create \
     --name "flowlog-${VNET_NAME}" \
     --nsg $VNET_ID \
     --resource-group NetworkWatcherRG \
     --location $AZURE_REGION \
     --storage-account $STORAGE_ACCOUNT \
     --workspace $LOG_ANALYTICS_WORKSPACE_ID \
     --traffic-analytics true \
     --interval 10

   Note: VNet flow logs may require additional configuration for Event Hub forwarding via Diagnostic Settings.

6. Creates Diagnostic Setting to route to Event Hub:
   az monitor diagnostic-settings create \
     --name "lm-logs-diagnostic" \
     --resource $VNET_ID \
     --event-hub "log-hub" \
     --event-hub-rule "/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.EventHub/namespaces/${NAMESPACE}/authorizationRules/RootManageSharedAccessKey" \
     --logs '[{"category": "VMProtectionAlerts", "enabled": true}]'

Note: VNet flow logs go to Storage Account first, then may need Event Grid to trigger forwarding. Adjust approach based on Azure capabilities.

Acceptance Criteria:
- Network Watcher enabled
- Storage account created
- VNet flow logs enabled
- Logs flowing to destination
```

### 3.4 Verify Azure VNet Flow Logs in LM Logs

```text
[Prompt 3.4: Verify Azure VNet Flow Logs in LogicMonitor]

Context: After configuring the Azure pipeline, we need to verify logs are reaching LogicMonitor.

Task: Create scripts/azure/verify-vnet-flow-logs.sh that:

1. Waits for configurable period (default 10 minutes - Azure can be slower)

2. Checks Azure Function logs for activity:
   az functionapp logs show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP

3. Verifies Event Hub is receiving messages:
   az monitor metrics list \
     --resource "/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.EventHub/namespaces/${NAMESPACE}" \
     --metric "IncomingMessages" \
     --interval PT1M

4. Queries LM Logs API (similar to AWS verification)

5. Provides manual verification steps if API unavailable

Create tests/test-azure-vnet-flow.sh that:
1. Generates test traffic within Azure VNet
2. Runs verification script
3. Reports pass/fail

Acceptance Criteria:
- Azure Function shows activity
- Event Hub receiving messages
- Logs visible in LM Logs (or manual verification documented)
```

---

## Phase 4: Azure DNS/Private Link/Private Endpoint Monitoring

### 4.1 Verify Azure DNS Zone DataSource

```text
[Prompt 4.1: Verify Azure DNS Zone Monitoring]

Context: LogicMonitor should have OOB DataSources for Azure DNS Zones via Azure Monitor integration.

Task: Create scripts/azure/verify-dns-datasources.sh that:

1. Queries LM API for Azure DNS DataSources:
   GET /setting/datasources?filter=name~"Azure_DNS"

2. Checks if DNS Zone resources are discovered:
   GET /device/devices?filter=systemProperties.name:system.azure.resourcetype,systemProperties.value:"Microsoft.Network/dnsZones"

3. Verifies metrics are being collected:
   - Navigate to a DNS Zone resource in LM
   - Check Raw Data tab for metrics

4. Documents findings in docs/azure-dns-status.md:
   - List discovered DNS Zones
   - List available metrics
   - Note any gaps

Acceptance Criteria:
- DNS Zone DataSource exists or documented as gap
- DNS Zone resources discovered
- Metrics collection verified
```

### 4.2 Create Private Endpoint PropertySource

```text
[Prompt 4.2: Create Azure Private Endpoint PropertySource]

Context: Azure Private Endpoints need additional metadata captured as properties for better visibility. This includes connection state, linked resource, and private IP.

Task: Create propertysources/Azure_PrivateEndpoint_Properties.xml with:

1. PropertySource definition:
   - Name: Azure_PrivateEndpoint_Properties
   - AppliesTo: system.azure.resourcetype == "Microsoft.Network/privateEndpoints"
   - Script type: Embedded Groovy
   - Execution: On resource add/update

2. Groovy script that:
   - Uses Azure REST API to get Private Endpoint details
   - Extracts:
     - privateEndpoint.properties.provisioningState
     - privateEndpoint.properties.privateLinkServiceConnections[].privateLinkServiceConnectionState.status
     - privateEndpoint.properties.privateLinkServiceConnections[].privateLinkServiceId (linked resource)
     - privateEndpoint.properties.networkInterfaces[].id
     - privateEndpoint.properties.customDnsConfigs[].ipAddresses
   
3. Outputs properties:
   - auto.privateendpoint.state
   - auto.privateendpoint.connection.status
   - auto.privateendpoint.linked.resource
   - auto.privateendpoint.private.ip

Script skeleton:
```groovy
import com.santaba.agent.groovyapi.http.*
import groovy.json.JsonSlurper

def resourceId = hostProps.get("system.azure.resourceid")
def accessToken = hostProps.get("azure.accesstoken")

def http = HTTP.open("management.azure.com", 443, true)
def getUrl = "${resourceId}?api-version=2023-04-01"

def response = http.get(getUrl, ["Authorization": "Bearer ${accessToken}"])
def json = new JsonSlurper().parseText(response.body)

println "auto.privateendpoint.state=${json.properties.provisioningState}"
// ... additional properties

return 0
```

Create scripts/azure/import-privateendpoint-propertysource.sh to import via API.

Acceptance Criteria:
- PropertySource XML is valid
- AppliesTo targets Private Endpoints
- Script extracts required metadata
- Properties populated on resources
```

### 4.3 Create Private Endpoint Health Dashboard Widget

```text
[Prompt 4.3: Create Azure Private Endpoint Dashboard]

Context: We need a dashboard showing Private Endpoint health and connectivity status.

Task: Create dashboards/azure-private-endpoint-health.json with:

1. Dashboard definition:
   - Name: Azure Private Endpoint Health
   - Group: KPMG Network Monitoring

2. Widgets:
   a. NOC Widget - Private Endpoint Status
      - Show all Private Endpoints
      - Color by connection status property
   
   b. Table Widget - Private Endpoint Details
      - Columns: Name, State, Connection Status, Linked Resource, Private IP
      - Data from device properties

   c. Big Number - Total Private Endpoints
      - Count of devices where system.azure.resourcetype == "Microsoft.Network/privateEndpoints"

   d. Big Number - Connected Endpoints
      - Count where auto.privateendpoint.connection.status == "Approved"

3. Export as JSON for import via LM API

Create scripts/azure/import-privateendpoint-dashboard.sh to import via API:
   POST /dashboard/dashboards
   Content-Type: application/json
   Body: <dashboard JSON>

Acceptance Criteria:
- Dashboard JSON is valid
- Widgets display Private Endpoint data
- Import script works
```

---

## Phase 5: Performance Benchmarking

### 5.1 Configure Website Checks for Azure Endpoints

```text
[Prompt 5.1: Create Website Checks for Azure Performance Baseline]

Context: LogicMonitor Website Checks provide synthetic monitoring from global checkpoints. We'll use these to measure latency to Azure endpoints in different regions.

Task: Create scripts/common/create-website-checks.sh that:

1. Accepts a configuration file (configs/website-checks.json) with format:
   {
     "checks": [
       {
         "name": "Azure East US - KPMG App",
         "url": "https://app-eastus.kpmg.azure.example.com/health",
         "type": "webcheck",
         "checkpoints": ["US - Los Angeles", "US - Washington DC", "EU - Dublin"],
         "frequency": 5
       }
     ]
   }

2. For each check, uses LM API to create:
   POST /website/websites
   {
     "name": "<check name>",
     "type": "webcheck",
     "domain": "<extracted from url>",
     "steps": [{"url": "<url>", "HTTPMethod": "GET"}],
     "testLocation": {"smgIds": [<checkpoint IDs>]},
     "pollingInterval": <frequency>
   }

3. Stores created check IDs in configs/website-check-ids.json

Note: User will need to update configs/website-checks.json with actual endpoints.

Create configs/website-checks-azure.json.example with sample Azure endpoints.
Create configs/website-checks-aws.json.example with sample AWS endpoints.

Acceptance Criteria:
- Script reads configuration file
- Website checks created via API
- Check IDs stored for reference
```

### 5.2 Configure Collector-Based Latency Checks

```text
[Prompt 5.2: Configure Collector Ping DataSource for Hybrid Latency]

Context: For hybrid latency (cloud to on-prem), we need Collectors deployed in cloud regions to ping on-prem targets.

Task: Create documentation and configuration:

1. Create docs/collector-latency-setup.md with:
   - Instructions for deploying Collector in Azure VM
   - Instructions for deploying Collector in AWS EC2
   - How to configure ping targets

2. Create configs/ping-targets.json.example with format:
   {
     "targets": [
       {
         "name": "On-Prem DC Primary",
         "ip": "10.0.0.1",
         "from_collector_groups": ["Azure-EastUS-Collectors", "AWS-UsEast1-Collectors"]
       }
     ]
   }

3. Create scripts/common/configure-ping-targets.sh that:
   - Reads ping-targets.json
   - For each target, adds it as a resource in LM with:
     - Custom properties for collector assignment
     - Ping DataSource will auto-apply
   - Uses API: POST /device/devices

Note: Ping DataSource is built-in to LM. Resources just need to be added with system.hostname set to the IP.

Acceptance Criteria:
- Documentation complete
- Configuration example provided
- Script adds ping targets to LM
```

### 5.3 Create Performance Dashboard

```text
[Prompt 5.3: Create Performance Benchmarking Dashboard]

Context: We need a unified dashboard showing performance metrics across Azure and AWS.

Task: Create dashboards/performance-benchmark.json with:

1. Dashboard definition:
   - Name: Cloud Performance Benchmark
   - Group: KPMG Network Monitoring

2. Azure Performance Section:
   a. Custom Graph - Azure Region Latency
      - Website check response times
      - Group by checkpoint location
   
   b. Big Number - Azure Avg Response Time
      - Average across all Azure website checks

   c. Custom Graph - ExpressRoute/VPN Throughput (if applicable)
      - BitsInPerSecond, BitsOutPerSecond

3. AWS Performance Section:
   a. Custom Graph - AWS Region Latency
      - Website check response times
      - Group by checkpoint location
   
   b. Big Number - AWS Avg Response Time
      - Average across all AWS website checks

   c. Custom Graph - Direct Connect/VPN Throughput (if applicable)

4. Hybrid Performance Section:
   a. Custom Graph - Hybrid Latency Over Time
      - Ping round-trip times from cloud collectors to on-prem
   
   b. Table - Current Latency by Path
      - Source, Destination, Current RTT, Avg RTT

Create scripts/common/import-performance-dashboard.sh to import.

Acceptance Criteria:
- Dashboard covers Azure, AWS, and hybrid
- Latency visualized over time
- Import script works
```

---

## Phase 6: Egress Cost Attribution Dashboards

### 6.1 Create AWS Egress Cost Dashboard

```text
[Prompt 6.1: Create AWS Egress Cost Attribution Dashboard]

Context: Combining VPC Flow Log data with Cost Optimization data to show egress cost attribution.

Task: Create dashboards/aws-egress-cost.json with:

1. Dashboard definition:
   - Name: AWS Egress Cost Attribution
   - Group: KPMG Cost Analysis

2. Cost Section (from Cost Optimization Billing data):
   a. Billing Widget - Data Transfer Costs
      - Filter: UsageType contains "DataTransfer"
      - Group by: Region
   
   b. Billing Widget - Egress by Service
      - Filter: UsageType contains "DataTransfer-Out"
      - Group by: Service

   c. Billing Forecast Widget - Projected Egress Costs
      - Based on current trend

3. Traffic Section (from LM Logs):
   a. Log Query Widget - Top Egress Destinations
      - Query: VPC flow logs, action=ACCEPT, dstaddr not in 10.0.0.0/8
      - Aggregate bytes by dstaddr
   
   b. Log Query Widget - Egress by Protocol
      - Aggregate bytes by protocol for external destinations

4. Correlation Section:
   a. Table Widget - Department Cost Breakdown
      - Show cost allocation tags (if configured)
   
   b. Text Widget - Correlation Notes
      - Explain relationship between flow data and cost data

Create scripts/aws/import-egress-cost-dashboard.sh to import.

Acceptance Criteria:
- Cost data displayed from Cost Optimization
- Flow data displayed from LM Logs
- Dashboard provides actionable insights
```

### 6.2 Create Azure Egress Cost Dashboard

```text
[Prompt 6.2: Create Azure Egress Cost Attribution Dashboard]

Context: Similar to AWS, combining VNet Flow Log data with Azure Cost data.

Task: Create dashboards/azure-egress-cost.json with:

1. Dashboard definition:
   - Name: Azure Egress Cost Attribution  
   - Group: KPMG Cost Analysis

2. Cost Section (from Cost Optimization Billing data):
   a. Billing Widget - Bandwidth Costs
      - Filter: MeterCategory == "Bandwidth"
      - Group by: Region
   
   b. Billing Widget - Egress by Subscription/Tag
      - Group by cost allocation tags (Department, CostCenter)

   c. Billing Forecast Widget - Projected Egress Costs

3. Traffic Section (from LM Logs):
   a. Log Query Widget - Top Egress Destinations
      - Query: VNet flow logs
      - Aggregate bytes by destination
   
   b. Log Query Widget - Traffic by VNet

4. Correlation Section:
   a. Table Widget - Resource Group Cost Breakdown
   
   b. Text Widget - Recommendations

Create scripts/azure/import-egress-cost-dashboard.sh to import.

Acceptance Criteria:
- Azure cost data displayed
- Flow data displayed
- Actionable insights provided
```

### 6.3 Create Unified Multi-Cloud Cost Dashboard

```text
[Prompt 6.3: Create Unified Multi-Cloud Egress Dashboard]

Context: Executive-level view combining AWS and Azure egress costs.

Task: Create dashboards/multicloud-egress-overview.json with:

1. Dashboard definition:
   - Name: Multi-Cloud Egress Overview
   - Group: KPMG Executive

2. Summary Section:
   a. Big Number - Total AWS Egress Cost (MTD)
   b. Big Number - Total Azure Egress Cost (MTD)
   c. Big Number - Combined Total

3. Trend Section:
   a. Custom Graph - Egress Cost Trend
      - AWS and Azure on same chart
      - Last 30 days

4. Breakdown Section:
   a. Pie Chart - Cost by Cloud Provider
   b. Pie Chart - Cost by Region (all clouds)

5. Top Consumers:
   a. Table - Top 10 Egress Consumers
      - Across both clouds
      - By tag/department if available

Create scripts/common/import-multicloud-dashboard.sh to import.

Acceptance Criteria:
- Unified view of both clouds
- Cost trends visible
- Actionable for cost optimization
```

---

## Phase 7: AWS WAF/Shield Dashboard

### 7.1 Create AWS Security Dashboard

```text
[Prompt 7.1: Create AWS WAF/Shield/Network Firewall Dashboard]

Context: Security operations dashboard showing WAF, Shield, and Network Firewall metrics.

Task: Create dashboards/aws-security-operations.json with:

1. Dashboard definition:
   - Name: AWS Security Operations
   - Group: KPMG Security

2. WAF Section:
   a. Custom Graph - WAF Request Flow
      - AllowedRequests, BlockedRequests over time
   
   b. Big Number - Current Block Rate
      - (BlockedRequests / TotalRequests) * 100
   
   c. Table - Top Blocked Rules
      - From WAF logs in LM Logs
      - Query: Group by terminatingRuleId

3. Shield Section:
   a. NOC Widget - DDoS Attack Status
      - Green if DDoSDetected == 0
      - Red if attack detected
   
   b. Custom Graph - Attack Metrics
      - BitsPerSecond, PacketsPerSecond during attacks

4. Network Firewall Section:
   a. Custom Graph - Firewall Packet Flow
      - Dropped, Passed, Received packets
   
   b. Big Number - Current Drop Rate

5. Log Analysis Section:
   a. Log Query Widget - Recent Security Events
      - Combined WAF and firewall logs

Create scripts/aws/import-security-dashboard.sh to import.

Acceptance Criteria:
- All three services represented
- Attack detection visible
- Actionable for security response
```

---

## Phase 8: Final Integration and Testing

### 8.1 End-to-End Test Suite

```text
[Prompt 8.1: Create End-to-End Test Suite]

Context: We need comprehensive tests to validate the entire POC.

Task: Create tests/run-all-tests.sh that:

1. Runs all validation scripts:
   - scripts/common/validate-all.sh

2. Runs AWS tests:
   - tests/test-aws-vpc-flow.sh
   - tests/test-aws-waf-logs.sh
   - tests/test-aws-security-metrics.sh

3. Runs Azure tests:
   - tests/test-azure-vnet-flow.sh
   - tests/test-azure-dns-metrics.sh
   - tests/test-azure-privateendpoint-props.sh

4. Runs dashboard tests:
   - tests/test-dashboard-widgets.sh (verify widgets populate)

5. Generates test report:
   - docs/test-report.md
   - Pass/fail for each test
   - Timestamps
   - Any error messages

Individual test scripts should:
- Be idempotent (can run multiple times)
- Clean up after themselves
- Exit with appropriate codes
- Output clear results

Acceptance Criteria:
- All tests can run independently
- Aggregate test runner works
- Report generated with results
```

### 8.2 Documentation and Handoff

```text
[Prompt 8.2: Create Final Documentation]

Context: Project handoff documentation for KPMG.

Task: Create comprehensive documentation:

1. docs/deployment-guide.md:
   - Prerequisites
   - Step-by-step deployment instructions
   - Environment variable reference
   - Troubleshooting common issues

2. docs/architecture-diagram.md:
   - ASCII or Mermaid diagram of data flow
   - AWS pipeline
   - Azure pipeline
   - LogicMonitor integration points

3. docs/dashboard-guide.md:
   - List of all dashboards
   - Purpose of each
   - How to interpret data
   - Customization options

4. docs/maintenance-guide.md:
   - How to add new VPCs/VNets
   - How to add new website checks
   - How to modify dashboards
   - Log retention considerations

5. Update README.md with:
   - Project overview
   - Quick start
   - Links to detailed docs

Acceptance Criteria:
- All documentation complete
- Clear enough for handoff
- Includes troubleshooting
```

---

## Execution Order Summary

| Phase | Focus | Dependencies |
|-------|-------|--------------|
| 0 | Project Setup | None |
| 1 | AWS VPC Flow Logs | Phase 0 |
| 2 | AWS WAF/Shield/Firewall | Phase 1 (uses same Lambda) |
| 3 | Azure VNet Flow Logs | Phase 0 |
| 4 | Azure DNS/Private Endpoint | Phase 3 |
| 5 | Performance Benchmarking | Phase 1, 3 (endpoints exist) |
| 6 | Egress Cost Dashboards | Phase 1, 3 (flow logs), Cost Optimization |
| 7 | AWS Security Dashboard | Phase 2 |
| 8 | Testing and Documentation | All phases |

---

## Notes

- Each prompt is self-contained but builds on previous work
- Scripts should be idempotent where possible
- Error handling is critical - fail fast with clear messages
- Test at each phase before proceeding
- User must provide environment variables before execution
