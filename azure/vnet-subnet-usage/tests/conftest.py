# Description: Shared pytest fixtures for Azure VNet Subnet IP Usage DataSource tests.
# Description: Loads sample Azure ARM API responses and provides helper functions.

from __future__ import annotations

import json
from pathlib import Path

import pytest

SAMPLE_DATA_DIR = Path(__file__).parent / "sample_data"
DATASOURCES_DIR = Path(__file__).parent.parent / "datasources"


@pytest.fixture
def vnet_usage_normal() -> dict:
    """Normal VNet with 3 subnets at various utilization levels."""
    return json.loads((SAMPLE_DATA_DIR / "vnet_usage_normal.json").read_text())


@pytest.fixture
def vnet_usage_gateway() -> dict:
    """VNet with a GatewaySubnet that returns -1 for both currentValue and limit."""
    return json.loads((SAMPLE_DATA_DIR / "vnet_usage_gateway.json").read_text())


@pytest.fixture
def vnet_usage_empty() -> dict:
    """VNet with no subnets (empty value array)."""
    return json.loads((SAMPLE_DATA_DIR / "vnet_usage_empty.json").read_text())


@pytest.fixture
def datasource_json() -> dict:
    """Loaded DataSource JSON definition."""
    return json.loads((DATASOURCES_DIR / "Azure_VNet_IPUsage.json").read_text())


def extract_subnet_name(subnet_id: str) -> str:
    """Extract subnet name from a full Azure resource ID."""
    return subnet_id.rstrip("/").split("/")[-1]


def parse_collection_output(lines: list[str]) -> dict[str, dict[str, str]]:
    """Parse key=value collection output lines into {instance: {datapoint: value}}.

    Expected format: instanceId.DatapointName=value
    Lines starting with // are comments and are skipped.
    """
    results: dict[str, dict[str, str]] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("ERROR"):
            continue
        if "=" not in line or "." not in line.split("=")[0]:
            continue
        key, value = line.split("=", 1)
        instance_id, datapoint = key.rsplit(".", 1)
        if instance_id not in results:
            results[instance_id] = {}
        results[instance_id][datapoint] = value
    return results


def parse_ad_output(lines: list[str]) -> list[dict[str, str]]:
    """Parse AD ILP output lines into structured dicts.

    Expected format: WILDVALUE##DisplayName####Description##ILPString
    Lines starting with // are comments and are skipped.
    """
    instances = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("ERROR"):
            continue
        parts = line.split("##")
        if len(parts) < 5:
            continue
        instances.append({
            "wildvalue": parts[0],
            "display_name": parts[1],
            "description": parts[3],
            "ilp": parts[4],
        })
    return instances
