#!/usr/bin/env bash
# Description: Deploys the VNet Flow Log Forwarder Azure Function and supporting infrastructure.
# Description: Creates Function App, Table Storage, and Event Grid subscription for flow log processing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FUNC_DIR="$PROJECT_ROOT/azure-function/vnet-flow-forwarder"

# Load environment variables from the project .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "ERROR: No .env file found at $PROJECT_ROOT/.env"
    exit 1
fi

# Configuration (override via .env or environment)
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-CTA_Resource_Group}"
LOCATION="${AZURE_REGION:-eastus}"
STORAGE_ACCOUNT="${AZURE_FLOW_LOG_STORAGE:-rmazurestorage}"
FUNC_APP_NAME="${AZURE_FUNC_APP_NAME:-kpmg-vnet-flow-forwarder}"
FUNC_STORAGE="${AZURE_FUNC_STORAGE:-kpmgfuncstore}"
WATERMARK_TABLE="${WATERMARK_TABLE_NAME:-vnetflowwatermarks}"
VNET_NAME="${AZURE_VNET_NAME:-CTA-vnet}"

echo "=== VNet Flow Log Forwarder Deployment ==="
echo "Resource Group: $RESOURCE_GROUP"
echo "Location:       $LOCATION"
echo "Storage:        $STORAGE_ACCOUNT"
echo "Function App:   $FUNC_APP_NAME"
echo ""

# Step 1: Create a storage account for the Function App (if it doesn't exist)
echo "--- Step 1: Function App Storage Account ---"
if az storage account show --name "$FUNC_STORAGE" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    echo "Storage account $FUNC_STORAGE already exists"
else
    echo "Creating storage account $FUNC_STORAGE..."
    az storage account create \
        --name "$FUNC_STORAGE" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --kind StorageV2 \
        --min-tls-version TLS1_2 \
        --output none
    echo "Created."
fi

# Step 2: Create the Function App
echo ""
echo "--- Step 2: Function App ---"
if az functionapp show --name "$FUNC_APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    echo "Function App $FUNC_APP_NAME already exists"
else
    echo "Creating Function App $FUNC_APP_NAME..."
    az functionapp create \
        --name "$FUNC_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --storage-account "$FUNC_STORAGE" \
        --consumption-plan-location "$LOCATION" \
        --runtime python \
        --runtime-version 3.11 \
        --functions-version 4 \
        --os-type Linux \
        --output none
    echo "Created."
fi

# Step 3: Get the flow log storage connection string and VNet resource ID
echo ""
echo "--- Step 3: Configuration ---"
FLOW_STORAGE_CONN=$(az storage account show-connection-string \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query connectionString \
    --output tsv)

VNET_RESOURCE_ID=$(az network vnet show \
    --name "$VNET_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query id \
    --output tsv)

echo "VNet Resource ID retrieved (length: ${#VNET_RESOURCE_ID})"
echo "Storage connection string retrieved"

# Step 4: Configure Function App settings
echo ""
echo "--- Step 4: App Settings ---"
az functionapp config appsettings set \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --settings \
        "LM_COMPANY=${LM_COMPANY}" \
        "LM_ACCESS_ID=${LM_ACCESS_ID}" \
        "LM_ACCESS_KEY=${LM_ACCESS_KEY}" \
        "AZURE_STORAGE_CONNECTION_STRING=${FLOW_STORAGE_CONN}" \
        "WATERMARK_TABLE_NAME=${WATERMARK_TABLE}" \
        "TARGET_VNET_RESOURCE_ID=${VNET_RESOURCE_ID}" \
        "LOG_LEVEL=INFO" \
        "BATCH_SIZE_LIMIT=7340032" \
    --output none
echo "App settings configured."

# Step 5: Deploy the function code
echo ""
echo "--- Step 5: Deploy Function Code ---"
cd "$FUNC_DIR"

# Package and deploy using zip deployment
echo "Packaging function..."
DEPLOY_ZIP="/tmp/vnet-flow-forwarder.zip"
rm -f "$DEPLOY_ZIP"
zip -r "$DEPLOY_ZIP" . -x "__pycache__/*" "*.pyc" "local.settings.json" "local.settings.json.example" &>/dev/null

echo "Deploying to Azure..."
az functionapp deployment source config-zip \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --src "$DEPLOY_ZIP" \
    --output none
rm -f "$DEPLOY_ZIP"
echo "Function code deployed."

# Step 6: Create Event Grid subscription on the storage account
echo ""
echo "--- Step 6: Event Grid Subscription ---"
STORAGE_ID=$(az storage account show \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query id \
    --output tsv)

FUNC_RESOURCE_ID=$(az functionapp show \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query id \
    --output tsv)

EG_SUB_NAME="vnet-flow-log-events"

# Check if subscription already exists
if az eventgrid event-subscription show \
    --name "$EG_SUB_NAME" \
    --source-resource-id "$STORAGE_ID" &>/dev/null; then
    echo "Event Grid subscription $EG_SUB_NAME already exists"
else
    echo "Creating Event Grid subscription..."
    az eventgrid event-subscription create \
        --name "$EG_SUB_NAME" \
        --source-resource-id "$STORAGE_ID" \
        --endpoint "${FUNC_RESOURCE_ID}/functions/vnet_flow_processor" \
        --endpoint-type azurefunction \
        --included-event-types "Microsoft.Storage.BlobCreated" \
        --subject-begins-with "/blobServices/default/containers/insights-logs-flowlogflowevent" \
        --advanced-filter data.api StringIn PutBlockList \
        --output none
    echo "Created."
fi

# Step 7: Create watermark table
echo ""
echo "--- Step 7: Watermark Table ---"
FLOW_STORAGE_KEY=$(az storage account keys list \
    --account-name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].value" \
    --output tsv)

az storage table create \
    --name "$WATERMARK_TABLE" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$FLOW_STORAGE_KEY" \
    --output none 2>/dev/null || echo "Table $WATERMARK_TABLE already exists"
echo "Watermark table ready."

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Function App:        $FUNC_APP_NAME"
echo "Event Grid Sub:      $EG_SUB_NAME"
echo "Watermark Table:     $WATERMARK_TABLE (in $STORAGE_ACCOUNT)"
echo "VNet Flow Log:       kpmg-cta-vnet-flow-log"
echo ""
echo "Verify with: az functionapp show --name $FUNC_APP_NAME --resource-group $RESOURCE_GROUP --query state"
echo "Logs:        az monitor app-insights query --app $FUNC_APP_NAME --analytics-query 'traces | order by timestamp desc | take 20'"
