# Description: Unit tests validating the Azure VNet IP Usage DataSource JSON definition.
# Description: Checks structure, datapoints, alert thresholds, and device requirements.

from __future__ import annotations


class TestDataSourceJsonStructure:
    """Validate top-level DataSource JSON structure and required fields."""

    def test_required_top_level_fields(self, datasource_json):
        required = [
            "name", "displayName", "description", "appliesTo",
            "collectMethod", "collectInterval", "hasMultiInstances",
            "collectorAttribute", "autoDiscoveryConfig", "dataPoints",
        ]
        for field in required:
            assert field in datasource_json, f"Missing required field: {field}"

    def test_name_is_correct(self, datasource_json):
        assert datasource_json["name"] == "Azure_VNet_IPUsage"

    def test_display_name_is_human_readable(self, datasource_json):
        assert datasource_json["displayName"] == "Azure VNet IP Usage"
        assert datasource_json["displayName"] != datasource_json["name"]

    def test_collect_method_is_batchscript(self, datasource_json):
        assert datasource_json["collectMethod"] == "batchscript"

    def test_collect_interval_is_300(self, datasource_json):
        assert datasource_json["collectInterval"] == 300

    def test_has_multi_instances(self, datasource_json):
        assert datasource_json["hasMultiInstances"] is True

    def test_applies_to_uses_credential_properties(self, datasource_json):
        """appliesTo targets devices with Azure service principal credentials set."""
        applies_to = datasource_json["appliesTo"]
        assert "azure.tenantid" in applies_to
        assert "azure.subscriptionids" in applies_to

    def test_applies_to_not_hardcoded(self, datasource_json):
        assert "system.displayname ==" not in datasource_json["appliesTo"]

    def test_group_is_set(self, datasource_json):
        assert datasource_json.get("group") == "Azure"

    def test_tags_are_set(self, datasource_json):
        tags = datasource_json.get("tags", "")
        assert "azure" in tags
        assert "vnet" in tags

    def test_collector_attribute_has_groovy_ref(self, datasource_json):
        attr = datasource_json["collectorAttribute"]
        assert attr["scriptType"] == "embed"
        assert "groovyScript" in attr

    def test_autodiscovery_configured(self, datasource_json):
        ad = datasource_json["autoDiscoveryConfig"]
        assert ad["method"] == "ad_script"
        assert ad["scheduleInterval"] == 15


class TestDataPointDefinitions:
    """Validate datapoint names, types, and configuration."""

    def test_has_four_datapoints(self, datasource_json):
        dp_names = [dp["name"] for dp in datasource_json["dataPoints"]]
        assert sorted(dp_names) == ["FreeIPs", "PercentUsed", "TotalIPs", "UsedIPs"]

    def test_no_usage_percent_datapoint(self, datasource_json):
        """UsagePercent was redundant with PercentUsed -- should be removed."""
        dp_names = [dp["name"] for dp in datasource_json["dataPoints"]]
        assert "UsagePercent" not in dp_names

    def test_all_datapoints_have_descriptions(self, datasource_json):
        for dp in datasource_json["dataPoints"]:
            assert dp.get("description"), f"Datapoint {dp['name']} has no description"

    def test_all_datapoints_are_numeric_gauge(self, datasource_json):
        for dp in datasource_json["dataPoints"]:
            assert dp["dataType"] == 7, f"{dp['name']} should be dataType 7 (gauge)"

    def test_namevalue_datapoints_use_wildvalue(self, datasource_json):
        for dp in datasource_json["dataPoints"]:
            if dp["postProcessorMethod"] == "namevalue":
                param = dp["postProcessorParam"]
                assert param.startswith("##WILDVALUE##."), (
                    f"{dp['name']} param should start with ##WILDVALUE##."
                )

    def test_percent_used_is_expression(self, datasource_json):
        dp = next(d for d in datasource_json["dataPoints"] if d["name"] == "PercentUsed")
        assert dp["postProcessorMethod"] == "expression"

    def test_percent_used_expression_references_datapoints(self, datasource_json):
        dp = next(d for d in datasource_json["dataPoints"] if d["name"] == "PercentUsed")
        expr = dp["postProcessorParam"]
        assert "UsedIPs" in expr
        assert "TotalIPs" in expr

    def test_percent_used_has_alert_thresholds(self, datasource_json):
        dp = next(d for d in datasource_json["dataPoints"] if d["name"] == "PercentUsed")
        assert dp.get("alertExpr"), "PercentUsed must have alertExpr"
        assert "80" in dp["alertExpr"]
        assert "90" in dp["alertExpr"]
        assert "95" in dp["alertExpr"]

    def test_percent_used_has_alert_body(self, datasource_json):
        dp = next(d for d in datasource_json["dataPoints"] if d["name"] == "PercentUsed")
        assert dp.get("alertBody"), "PercentUsed must have alertBody"
        assert "##INSTANCE##" in dp["alertBody"]

    def test_percent_used_has_alert_subject(self, datasource_json):
        dp = next(d for d in datasource_json["dataPoints"] if d["name"] == "PercentUsed")
        assert dp.get("alertSubject"), "PercentUsed must have alertSubject"


class TestDeviceRequirements:
    """Validate documented device requirements."""

    def test_custom_properties_documented(self, datasource_json):
        reqs = datasource_json.get("deviceRequirements", {})
        props = reqs.get("customProperties", {})
        assert "azure.tenantid" in props
        assert "azure.clientid" in props
        assert "azure.secretkey" in props
        assert "azure.subscriptionids" in props

    def test_collector_requirements_documented(self, datasource_json):
        reqs = datasource_json.get("deviceRequirements", {})
        assert reqs.get("collectorRequirements"), "Missing collectorRequirements"
