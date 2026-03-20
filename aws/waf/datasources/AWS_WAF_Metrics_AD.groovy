// Description: Active Discovery script for AWS WAF WebACL metrics.
// Description: Outputs WAF rule instances using device properties and AWS CLI via process execution.

def webAclName = hostProps.get("aws.webacl.name")
def region = hostProps.get("aws.region") ?: "us-west-2"

if (!webAclName) {
    println "ERROR: Missing aws.webacl.name property"
    return 1
}

// Always output the ALL aggregate instance
def ilpAll = "auto.waf.rule=ALL&auto.waf.webacl=${webAclName}"
println "ALL##All Rules (Aggregate)####Aggregate WAF metrics##${ilpAll}"

// Try to discover individual rules via AWS CLI on the collector
try {
    def cmd = ["/usr/local/bin/aws", "cloudwatch", "list-metrics",
               "--namespace", "AWS/WAFV2",
               "--metric-name", "AllowedRequests",
               "--region", region,
               "--output", "json"]

    def proc = cmd.execute()
    proc.waitForOrKill(30000)
    def output = proc.text

    if (proc.exitValue() == 0 && output) {
        def slurper = new groovy.json.JsonSlurper()
        def result = slurper.parseText(output)
        def ruleNames = new LinkedHashSet()

        result?.Metrics?.each { metric ->
            metric?.Dimensions?.each { dim ->
                if (dim?.Name == "Rule" && dim?.Value != "ALL") {
                    ruleNames.add(dim.Value)
                }
            }
        }

        ruleNames.each { ruleName ->
            def ilp = "auto.waf.rule=${ruleName}&auto.waf.webacl=${webAclName}"
            println "${ruleName}##${ruleName}####WAF Rule: ${ruleName}##${ilp}"
        }
    }
} catch (Exception e) {
    // Non-fatal, ALL instance is already output
}

return 0
