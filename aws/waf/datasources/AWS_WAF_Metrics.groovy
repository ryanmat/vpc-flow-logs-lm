// Description: Collection script for AWS WAF CloudWatch metrics per rule instance.
// Description: Runs per-instance using WILDVALUE as the Rule dimension, outputs key=value pairs.

import groovy.json.JsonSlurper

def region = hostProps.get("aws.region") ?: "us-west-2"
def webAclName = hostProps.get("aws.webacl.name")
def ruleName = instanceProps.get("wildvalue")

if (!webAclName) {
    System.err.println "ERROR: Missing aws.webacl.name property"
    return 1
}

if (!ruleName) {
    System.err.println "ERROR: Missing wildvalue (rule name) in instanceProps"
    return 1
}

def metricNames = ["AllowedRequests", "BlockedRequests", "CountedRequests", "PassedRequests"]
def slurper = new JsonSlurper()

// Calculate time window: last 10 minutes
def endTime = new Date()
def startTime = new Date(endTime.getTime() - 600000)
def fmt = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'")
fmt.setTimeZone(TimeZone.getTimeZone("UTC"))
def startStr = fmt.format(startTime)
def endStr = fmt.format(endTime)

// Collect each metric for this rule instance
metricNames.each { metricName ->
    try {
        def cmd = ["/usr/local/bin/aws", "cloudwatch", "get-metric-statistics",
                   "--namespace", "AWS/WAFV2",
                   "--metric-name", metricName,
                   "--dimensions", "Name=WebACL,Value=${webAclName}", "Name=Region,Value=${region}", "Name=Rule,Value=${ruleName}",
                   "--start-time", startStr,
                   "--end-time", endStr,
                   "--period", "300",
                   "--statistics", "Sum",
                   "--region", region,
                   "--output", "json"]

        def proc = cmd.execute()
        proc.waitForOrKill(30000)

        if (proc.exitValue() == 0) {
            def result = slurper.parseText(proc.text)
            def datapoints = result?.Datapoints

            if (datapoints && datapoints.size() > 0) {
                def latest = datapoints.sort { a, b -> b.Timestamp <=> a.Timestamp }.first()
                println "${metricName}=${latest.Sum.toLong()}"
            } else {
                println "${metricName}=0"
            }
        } else {
            println "${metricName}=NaN"
        }
    } catch (Exception e) {
        println "${metricName}=NaN"
    }
}

return 0
