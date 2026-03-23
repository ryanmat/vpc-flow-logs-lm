// Description: Collection script for Azure VNet subnet IP usage metrics.
// Description: Outputs UsedIPs, TotalIPs, FreeIPs per subnet as key=value pairs for LM batchscript.

// groovy_version=4
import com.santaba.agent.groovyapi.http.*
import groovy.json.*

// Get Azure credentials from device properties
def tenantId = hostProps.get("azure.tenantid")
def clientId = hostProps.get("azure.clientid")
def clientSecret = hostProps.get("azure.secretkey")
def subscriptions = hostProps.get("azure.subscriptionids")

if (!tenantId || !clientId || !clientSecret || !subscriptions) {
    println "ERROR: Missing required Azure credentials"
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
                if (currentUsed < 0 || totalAvailable < 0) {
                    def instanceId = "${vnetName}_${subnetName}"
                    println "${instanceId}.UsedIPs=NaN"
                    println "${instanceId}.TotalIPs=NaN"
                    println "${instanceId}.FreeIPs=NaN"
                    return
                }

                def freeIPs = totalAvailable - currentUsed
                def instanceId = "${vnetName}_${subnetName}"

                println "${instanceId}.UsedIPs=${currentUsed}"
                println "${instanceId}.TotalIPs=${totalAvailable}"
                println "${instanceId}.FreeIPs=${freeIPs}"
            }
        }
    }

    return 0

} catch (Exception e) {
    println "ERROR: Collection failed: ${e.message}"
    return 1
}
