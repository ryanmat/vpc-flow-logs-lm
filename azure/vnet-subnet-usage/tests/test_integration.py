# Description: Integration tests for Azure VNet IP Usage DataSource.
# Description: Tests real Azure ARM API calls. Skipped when AZURE_TENANT_ID is not set.

from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("AZURE_TENANT_ID"),
    reason="AZURE_TENANT_ID not set -- skipping integration tests",
)

TENANT_ID = os.environ.get("AZURE_TENANT_ID", "")
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET", "")
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
API_VERSION = "2024-05-01"


def get_azure_token() -> str:
    """Acquire an OAuth2 token using service principal credentials."""
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://management.azure.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(token_url, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def arm_get(token: str, url: str) -> dict:
    """Make an authenticated GET request to the Azure ARM API."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


class TestAzureTokenAcquisition:
    """Verify service principal auth works against real Azure AD."""

    def test_token_is_returned(self):
        token = get_azure_token()
        assert token
        assert len(token) > 100


class TestVNetUsagesApi:
    """Verify the ARM API returns expected subnet usage data."""

    def test_list_vnets_returns_data(self):
        token = get_azure_token()
        url = f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Network/virtualNetworks?api-version={API_VERSION}"
        data = arm_get(token, url)
        assert "value" in data

    def test_usages_have_expected_fields(self):
        token = get_azure_token()
        vnet_url = f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Network/virtualNetworks?api-version={API_VERSION}"
        vnets = arm_get(token, vnet_url)

        if not vnets.get("value"):
            pytest.skip("No VNets found in subscription")

        vnet = vnets["value"][0]
        rg = vnet["id"].split("/")[4]
        vnet_name = vnet["name"]

        usage_url = f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/usages?api-version={API_VERSION}"
        usage_data = arm_get(token, usage_url)

        assert "value" in usage_data
        if usage_data["value"]:
            entry = usage_data["value"][0]
            assert "currentValue" in entry
            assert "limit" in entry
            assert "id" in entry


class TestSubnetDiscovery:
    """Verify we can discover subnets from real Azure infrastructure."""

    def test_discovers_at_least_one_subnet(self):
        token = get_azure_token()
        vnet_url = f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Network/virtualNetworks?api-version={API_VERSION}"
        vnets = arm_get(token, vnet_url)

        if not vnets.get("value"):
            pytest.skip("No VNets found in subscription")

        total_subnets = 0
        for vnet in vnets["value"]:
            rg = vnet["id"].split("/")[4]
            usage_url = f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet['name']}/usages?api-version={API_VERSION}"
            usage_data = arm_get(token, usage_url)
            total_subnets += len(usage_data.get("value", []))

        assert total_subnets > 0, "Expected at least one subnet across all VNets"
