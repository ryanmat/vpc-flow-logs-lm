# Description: Shared pytest fixtures for VPC Flow Log test data.
# Description: Loads JSON sample files and provides CloudEvent builder helpers.
import base64
import json
from pathlib import Path

import pytest

SAMPLE_DATA_DIR = Path(__file__).parent / "sample_data"


def _load_json(filename: str) -> dict:
    """Load and parse a JSON file from the sample_data directory."""
    filepath = SAMPLE_DATA_DIR / filename
    with open(filepath) as f:
        return json.load(f)


@pytest.fixture
def flow_log_src_vm() -> dict:
    """VM-to-VM flow log with both src and dest instances."""
    return _load_json("flow_log_src_vm.json")


@pytest.fixture
def flow_log_external() -> dict:
    """External-to-internal flow log with no src_instance."""
    return _load_json("flow_log_external.json")


@pytest.fixture
def flow_log_gke() -> dict:
    """GKE pod-to-pod flow log with cluster, pod, and service details."""
    return _load_json("flow_log_gke.json")


@pytest.fixture
def cloud_event_vm() -> dict:
    """Full CloudEvent envelope wrapping a VM-to-VM flow log."""
    return _load_json("pubsub_cloud_event.json")


@pytest.fixture
def cloud_event_external() -> dict:
    """Full CloudEvent envelope wrapping an external traffic flow log."""
    return _load_json("pubsub_cloud_event_external.json")


def build_cloud_event(flow_log: dict, insert_id: str = "test-insert-id") -> dict:
    """Build a CloudEvent dict from a raw flow log payload.

    Wraps the flow log in a Cloud Logging LogEntry, base64-encodes it,
    and places it in a CloudEvent structure matching Eventarc delivery format.
    """
    log_entry = {
        "insertId": insert_id,
        "logName": "projects/test-project/logs/compute.googleapis.com%2Fvpc_flows",
        "resource": {
            "type": "gce_subnetwork",
            "labels": {
                "project_id": "test-project",
                "subnetwork_id": "1234567890",
                "subnetwork_name": "test-subnet",
                "location": "us-central1-a",
            },
        },
        "timestamp": "2026-02-26T12:00:00.000000Z",
        "receiveTimestamp": "2026-02-26T12:00:01.000000Z",
        "severity": "DEFAULT",
        "jsonPayload": flow_log,
    }

    encoded = base64.b64encode(json.dumps(log_entry).encode("utf-8")).decode("utf-8")

    return {
        "specversion": "1.0",
        "id": f"evt-{insert_id}",
        "source": "//pubsub.googleapis.com/projects/test-project/topics/vpc-flowlogs-lm",
        "type": "google.cloud.pubsub.topic.v1.messagePublished",
        "datacontenttype": "application/json",
        "time": "2026-02-26T12:00:01.000000Z",
        "data": {
            "message": {
                "data": encoded,
                "attributes": {
                    "logging.googleapis.com/timestamp": "2026-02-26T12:00:00.000000Z"
                },
                "messageId": "9999999999",
                "publishTime": "2026-02-26T12:00:01.000000Z",
            },
            "subscription": "projects/test-project/subscriptions/eventarc-test-sub",
        },
    }
