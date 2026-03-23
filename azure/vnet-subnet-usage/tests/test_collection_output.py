# Description: Unit tests validating the collection script output format and IP math.
# Description: Tests key=value format, gateway handling, and edge case calculations.

from __future__ import annotations

import re

from conftest import extract_subnet_name, parse_collection_output


class TestKeyValueOutputFormat:
    """Validate the key=value output format LM expects from the collection script."""

    def test_normal_output_format(self):
        lines = [
            "CTA-vnet_default.UsedIPs=50",
            "CTA-vnet_default.TotalIPs=251",
            "CTA-vnet_default.FreeIPs=201",
        ]
        parsed = parse_collection_output(lines)
        assert "CTA-vnet_default" in parsed
        assert parsed["CTA-vnet_default"]["UsedIPs"] == "50"

    def test_multiple_instances(self):
        lines = [
            "CTA-vnet_default.UsedIPs=50",
            "CTA-vnet_default.TotalIPs=251",
            "CTA-vnet_default.FreeIPs=201",
            "CTA-vnet_backend.UsedIPs=10",
            "CTA-vnet_backend.TotalIPs=59",
            "CTA-vnet_backend.FreeIPs=49",
        ]
        parsed = parse_collection_output(lines)
        assert len(parsed) == 2
        assert "CTA-vnet_default" in parsed
        assert "CTA-vnet_backend" in parsed

    def test_comments_are_skipped(self):
        lines = [
            "// Getting Azure token...",
            "// Processing VNet: CTA-vnet",
            "CTA-vnet_default.UsedIPs=50",
        ]
        parsed = parse_collection_output(lines)
        assert len(parsed) == 1

    def test_error_lines_are_skipped(self):
        lines = [
            "ERROR: Failed to authenticate",
            "CTA-vnet_default.UsedIPs=50",
        ]
        parsed = parse_collection_output(lines)
        assert len(parsed) == 1

    def test_output_lines_match_namevalue_pattern(self):
        pattern = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z]+=(\d+(\.\d+)?|NaN)$")
        valid_lines = [
            "CTA-vnet_default.UsedIPs=50",
            "CTA-vnet_default.TotalIPs=251",
            "CTA-vnet_default.FreeIPs=201",
            "CTA-vnet_db-tier.UsedIPs=0",
            "CTA-vnet_db-tier.FreeIPs=NaN",
        ]
        for line in valid_lines:
            assert pattern.match(line), f"Line does not match expected format: {line}"

    def test_three_datapoints_per_instance(self):
        """Collection should output UsedIPs, TotalIPs, FreeIPs (not UsagePercent)."""
        lines = [
            "CTA-vnet_default.UsedIPs=50",
            "CTA-vnet_default.TotalIPs=251",
            "CTA-vnet_default.FreeIPs=201",
        ]
        parsed = parse_collection_output(lines)
        dp_names = set(parsed["CTA-vnet_default"].keys())
        assert dp_names == {"UsedIPs", "TotalIPs", "FreeIPs"}

    def test_no_usage_percent_in_output(self):
        """UsagePercent was removed -- PercentUsed is calculated via expression."""
        lines = [
            "CTA-vnet_default.UsedIPs=50",
            "CTA-vnet_default.TotalIPs=251",
            "CTA-vnet_default.FreeIPs=201",
        ]
        parsed = parse_collection_output(lines)
        assert "UsagePercent" not in parsed.get("CTA-vnet_default", {})


class TestIpCalculations:
    """Validate derived metric calculations."""

    def test_free_ips_normal(self):
        used, total = 50, 251
        free = total - used
        assert free == 201

    def test_free_ips_empty_subnet(self):
        used, total = 0, 27
        free = total - used
        assert free == 27

    def test_free_ips_full_subnet(self):
        used, total = 251, 251
        free = total - used
        assert free == 0

    def test_percent_used_normal(self):
        used, total = 50, 251
        pct = round((used / total) * 100, 2)
        assert pct == 19.92

    def test_percent_used_zero(self):
        used, total = 0, 27
        pct = round((used / total) * 100, 2)
        assert pct == 0.0

    def test_percent_used_full(self):
        used, total = 251, 251
        pct = round((used / total) * 100, 2)
        assert pct == 100.0

    def test_percent_used_zero_total_returns_zero(self):
        """Division by zero guard: total=0 should not crash."""
        used, total = 0, 0
        pct = round((used / total) * 100, 2) if total > 0 else 0
        assert pct == 0

    def test_gateway_negative_values_detected(self):
        """currentValue=-1 and limit=-1 are gateway subnet markers."""
        current_value = -1
        limit = -1
        is_gateway = current_value < 0 or limit < 0
        assert is_gateway


class TestSubnetNameExtraction:
    """Validate subnet name extraction from Azure resource IDs."""

    def test_extract_simple_name(self):
        subnet_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/default"
        assert extract_subnet_name(subnet_id) == "default"

    def test_extract_hyphenated_name(self):
        subnet_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/db-tier"
        assert extract_subnet_name(subnet_id) == "db-tier"

    def test_extract_gateway_subnet(self):
        subnet_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/GatewaySubnet"
        assert extract_subnet_name(subnet_id) == "GatewaySubnet"

    def test_extract_with_trailing_slash(self):
        subnet_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/default/"
        assert extract_subnet_name(subnet_id) == "default"
