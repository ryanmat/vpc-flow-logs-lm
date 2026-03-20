# AWS Security DataSource Status Report

Generated: 2026-01-30 01:23:29 UTC
Updated: 2026-02-04 (corrected OOB WAF findings)
Portal: lmryanmatuszewski.logicmonitor.com

## Summary

- AWS WAF: OOB DataSources exist (ids: 810, 948) -- apply to cloud account device via CloudWatch. Custom DataSource also built for per-device Groovy collection.
- AWS Shield: No OOB DataSource -- custom build required (blocked: $3k/mo)
- AWS Network Firewall: No OOB DataSource -- custom build required (blocked: no infra)

## OOB DataSources Found: 2

### AWS_WAFv2_WebACL (id: 810)
- Display Name: WAF Web ACL
- AppliesTo: hasCategory("AWS/LMAccount")
- Collect Method: awscloudwatch
- Metrics: AllowedRequests, BlockedRequests, CountedRequests, PassedRequests (Regional + Global variants)
- Metric paths: AWS/WAFV2>WebACL:##WILDVALUE##>Region:##auto.aws.region##>Rule:ALL>*>Sum
- Note: Collects at cloud account level, not per-WAF-device

### AWS_WAF_GlobalWebACL (id: 948)
- Display Name: WAF Global Web ACL
- AppliesTo: hasCategory("AWS/LMAccount")
- Collect Method: awscloudwatch
- Note: Covers CloudFront-scoped WAF Web ACLs

## Custom DataSources Built: 1

### AWS WAF Metrics (id: 11442196, Locator: AC26ZY)
- Display Name: AWS WAF Metrics
- AppliesTo: hasCategory("AWS_WAF")
- Collect Method: script (Groovy via AWS CLI on traditional collector)
- Group: AWS WAF
- Metrics: AllowedRequests, BlockedRequests, CountedRequests, PassedRequests per rule
- Active Discovery: discovers individual WAF rules via CloudWatch list-metrics
- Requires: aws.webacl.name and aws.region device properties, AWS CLI on collector
- Status: Applied to device 279643 (WAF WebACL), pending AD cycle

## Custom DataSources Needed (Blocked)

### AWS Shield Advanced (datasources/AWS_Shield_Custom.json)
- Namespace: AWS/DDoSProtection
- Metrics: DDoSDetected, DDoSAttackBitsPerSecond, DDoSAttackPacketsPerSecond, DDoSAttackRequestsPerSecond
- AppliesTo: Shield Advanced subscription required
- Status: Blocked ($3k/mo + 1yr commit), JSON spec exists as reference

### AWS Network Firewall (datasources/AWS_NetworkFirewall_Custom.json)
- Namespace: AWS/NetworkFirewall
- Metrics: DroppedPackets, PassedPackets, ReceivedPackets
- AppliesTo: system.aws.resourcetype == "network-firewall"
- Status: Blocked (no infra deployed, ~$285/mo), JSON spec exists as reference
