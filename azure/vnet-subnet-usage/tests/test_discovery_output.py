# Description: Unit tests validating the Active Discovery script output format.
# Description: Tests ILP line format, gateway subnet exclusion, and instance properties.

from __future__ import annotations

from conftest import parse_ad_output


class TestAdOutputFormat:
    """Validate Active Discovery ILP output line format."""

    def test_normal_subnet_ilp_format(self):
        lines = [
            "CTA-vnet_default##CTA-vnet / default####Subnet: default in CTA-vnet (10.0.0.0/24)##auto.azure.subscriptionid=sub1&auto.azure.resourcegroup=RG1&auto.azure.vnetname=CTA-vnet&auto.azure.subnetname=default&auto.azure.location=eastus",
        ]
        instances = parse_ad_output(lines)
        assert len(instances) == 1
        inst = instances[0]
        assert inst["wildvalue"] == "CTA-vnet_default"
        assert "CTA-vnet" in inst["display_name"]
        assert "default" in inst["display_name"]

    def test_multiple_subnets_produce_multiple_lines(self):
        lines = [
            "CTA-vnet_default##CTA-vnet / default####Subnet: default##auto.azure.subnetname=default",
            "CTA-vnet_backend##CTA-vnet / backend####Subnet: backend##auto.azure.subnetname=backend",
            "CTA-vnet_db-tier##CTA-vnet / db-tier####Subnet: db-tier##auto.azure.subnetname=db-tier",
        ]
        instances = parse_ad_output(lines)
        assert len(instances) == 3

    def test_wildvalue_matches_instance_id_pattern(self):
        """WILDVALUE should be {vnetName}_{subnetName} to match collection script."""
        lines = [
            "CTA-vnet_default##CTA-vnet / default####Subnet: default##auto.azure.subnetname=default",
        ]
        instances = parse_ad_output(lines)
        wv = instances[0]["wildvalue"]
        assert "_" in wv
        parts = wv.split("_", 1)
        assert len(parts) == 2
        assert parts[0] == "CTA-vnet"
        assert parts[1] == "default"

    def test_ilp_contains_required_properties(self):
        ilp = "auto.azure.subscriptionid=sub1&auto.azure.resourcegroup=RG1&auto.azure.vnetname=CTA-vnet&auto.azure.subnetname=default&auto.azure.location=eastus"
        lines = [f"CTA-vnet_default##CTA-vnet / default####Subnet: default##{ilp}"]
        instances = parse_ad_output(lines)
        ilp_str = instances[0]["ilp"]
        required_props = [
            "auto.azure.subscriptionid",
            "auto.azure.resourcegroup",
            "auto.azure.vnetname",
            "auto.azure.subnetname",
            "auto.azure.location",
        ]
        for prop in required_props:
            assert prop in ilp_str, f"Missing required ILP property: {prop}"

    def test_comments_are_skipped(self):
        lines = [
            "// Getting Azure token...",
            "// Processing VNet: CTA-vnet",
            "CTA-vnet_default##CTA-vnet / default####Subnet: default##auto.azure.subnetname=default",
            "// Discovery complete. Found 1 VNet(s) with 1 subnet(s)",
        ]
        instances = parse_ad_output(lines)
        assert len(instances) == 1

    def test_empty_vnet_produces_no_instances(self):
        lines = [
            "// No VNets found in subscription sub1",
        ]
        instances = parse_ad_output(lines)
        assert len(instances) == 0

    def test_gateway_subnet_excluded(self):
        """GatewaySubnet should not appear in AD output (limit=-1, no useful data)."""
        lines = [
            "CTA-vnet_default##CTA-vnet / default####Subnet: default##auto.azure.subnetname=default",
        ]
        instances = parse_ad_output(lines)
        wildvalues = [i["wildvalue"] for i in instances]
        assert not any("GatewaySubnet" in wv for wv in wildvalues)

    def test_hyphenated_subnet_name(self):
        lines = [
            "CTA-vnet_db-tier##CTA-vnet / db-tier####Subnet: db-tier##auto.azure.subnetname=db-tier",
        ]
        instances = parse_ad_output(lines)
        assert instances[0]["wildvalue"] == "CTA-vnet_db-tier"


class TestAdAutoGrouping:
    """Validate that instance auto-grouping is configured correctly."""

    def test_ilp_includes_resource_group(self):
        """Instances should group by resource group."""
        ilp = "auto.azure.subscriptionid=sub1&auto.azure.resourcegroup=CTA_Resource_Group&auto.azure.vnetname=CTA-vnet&auto.azure.subnetname=default&auto.azure.location=eastus"
        assert "auto.azure.resourcegroup=CTA_Resource_Group" in ilp
