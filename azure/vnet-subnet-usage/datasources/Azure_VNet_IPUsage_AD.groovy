// Description: Active Discovery script for Azure VNet subnet IP usage instances.
// Description: Discovers VNet+Subnet pairs via ARM REST API, outputs ILP lines for each subnet.

// groovy_version=4
import com.santaba.agent.groovyapi.http.*
import groovy.json.*

// Get Azure credentials from device properties
def tenantId = hostProps.get("azure.tenantid")
def clientId = hostProps.get("azure.clientid")
def clientSecret = hostProps.get("azure.secretkey")
def subscriptions = hostProps.get("azure.subscriptionids")

if (!tenantId || !clientId || !clientSecret || !subscriptions) {
    println "ERROR: Missing required Azure credentials (azure.tenantid, azure.clientid, azure.secretkey, azure.subscriptionids)"
    return 1
}

// LM HTTP module may include raw HTTP headers in response body. Strip them.
def stripHttpHeaders = { response ->
    if (!response) return null
    if (response.contains("\r\n\r\n")) {
        def parts = response.split("\r\n\r\n", 2)
        return parts.length > 1 ? parts[1] : response
    } else if (response.contains("\n\n")) {
        def parts = response.split("\n\n", 2)
        return parts.length > 1 ? parts[1] : response
    }
    return response
}

def getAzureToken = { tenant, client, secret ->
    try {
        def tokenUrl = "https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token"
        def postBody = "client_id=${URLEncoder.encode(client, 'UTF-8')}" +
                      "&client_secret=${URLEncoder.encode(secret, 'UTF-8')}" +
                      "&scope=${URLEncoder.encode('https://management.azure.com/.default', 'UTF-8')}" +
                      "&grant_type=client_credentials"
        def headers = ["Content-Type": "application/x-www-form-urlencoded"]
        def response = HTTP.post(tokenUrl, postBody, headers)
        def jsonBody = stripHttpHeaders(response)
        return new JsonSlurper().parseText(jsonBody).access_token
    } catch (Exception e) {
        println "ERROR: Failed to get Azure token: ${e.message}"
        return null
    }
}

def apiVersion = "2024-05-01"
def slurper = new JsonSlurper()

try {
    def token = getAzureToken(tenantId, clientId, clientSecret)
    if (!token) {
        println "ERROR: Failed to authenticate with Azure"
        return 1
    }

    def subscriptionList = subscriptions.split(',').collect { it.trim() }

    subscriptionList.each { subscriptionId ->
        // List all VNets in this subscription
        def vnetUrl = "https://management.azure.com/subscriptions/${subscriptionId}/providers/Microsoft.Network/virtualNetworks?api-version=${apiVersion}"
        def authHeaders = ["Authorization": "Bearer ${token}", "Content-Type": "application/json"]

        def vnetResponse = HTTP.get(vnetUrl, authHeaders)
        def vnetData = slurper.parseText(stripHttpHeaders(vnetResponse))

        if (!vnetData?.value) return

        vnetData.value.each { vnet ->
            def vnetName = vnet.name
            def resourceGroup = vnet.id.split('/')[4]
            def location = vnet.location

            // Build a map of subnet address prefixes from the VNet definition
            def subnetPrefixes = [:]
            vnet.properties?.subnets?.each { s ->
                subnetPrefixes[s.name] = s.properties?.addressPrefix ?: ""
            }

            // Get subnet usage data
            def usageUrl = "https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${resourceGroup}/providers/Microsoft.Network/virtualNetworks/${vnetName}/usages?api-version=${apiVersion}"
            def usageResponse = HTTP.get(usageUrl, authHeaders)
            def usageData = slurper.parseText(stripHttpHeaders(usageResponse))

            if (!usageData?.value) return

            usageData.value.each { subnet ->
                def subnetName = subnet.id.tokenize('/')[-1]
                def currentUsed = subnet.currentValue as Integer
                def totalAvailable = subnet.limit as Integer

                // Skip gateway subnets (API returns -1 for both values)
                if (currentUsed < 0 || totalAvailable < 0) return

                def instanceId = "${vnetName}_${subnetName}"
                def displayName = "${vnetName} / ${subnetName}"
                def prefix = subnetPrefixes[subnetName] ?: "unknown"
                def description = "Subnet: ${subnetName} in ${vnetName} (${prefix})"

                def properties = [
                    "auto.azure.subscriptionid=${subscriptionId}",
                    "auto.azure.resourcegroup=${resourceGroup}",
                    "auto.azure.vnetname=${vnetName}",
                    "auto.azure.subnetname=${subnetName}",
                    "auto.azure.location=${location}",
                    "auto.azure.addressprefix=${prefix}",
                ].join('&')

                println "${instanceId}##${displayName}####${description}##${properties}"
            }
        }
    }

    return 0

} catch (Exception e) {
    println "ERROR: Discovery failed: ${e.message}"
    return 1
}
