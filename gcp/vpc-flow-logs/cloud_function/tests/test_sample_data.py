# Description: Smoke tests validating all sample data fixtures.
# Description: Ensures JSON files are well-formed and have the expected structure.
import base64
import json

import pytest

from cloud_function.tests.conftest import build_cloud_event


class TestFlowLogSrcVm:
    """Validate the VM-to-VM flow log fixture."""

    def test_has_connection_fields(self, flow_log_src_vm):
        conn = flow_log_src_vm["connection"]
        assert "src_ip" in conn
        assert "dest_ip" in conn
        assert "src_port" in conn
        assert "dest_port" in conn
        assert "protocol" in conn

    def test_has_both_instances(self, flow_log_src_vm):
        assert "src_instance" in flow_log_src_vm
        assert "dest_instance" in flow_log_src_vm
        assert "vm_name" in flow_log_src_vm["src_instance"]
        assert "vm_name" in flow_log_src_vm["dest_instance"]

    def test_has_both_vpcs(self, flow_log_src_vm):
        assert "src_vpc" in flow_log_src_vm
        assert "dest_vpc" in flow_log_src_vm

    def test_has_traffic_fields(self, flow_log_src_vm):
        assert "bytes_sent" in flow_log_src_vm
        assert "packets_sent" in flow_log_src_vm
        assert "reporter" in flow_log_src_vm
        assert "start_time" in flow_log_src_vm
        assert "end_time" in flow_log_src_vm

    def test_bytes_and_packets_are_strings(self, flow_log_src_vm):
        """VPC Flow Logs encode int64 values as strings."""
        assert isinstance(flow_log_src_vm["bytes_sent"], str)
        assert isinstance(flow_log_src_vm["packets_sent"], str)

    def test_protocol_is_integer(self, flow_log_src_vm):
        assert isinstance(flow_log_src_vm["connection"]["protocol"], int)


class TestFlowLogExternal:
    """Validate the external-to-internal flow log fixture."""

    def test_has_no_src_instance(self, flow_log_external):
        assert "src_instance" not in flow_log_external

    def test_has_dest_instance(self, flow_log_external):
        assert "dest_instance" in flow_log_external
        assert "vm_name" in flow_log_external["dest_instance"]

    def test_has_src_location(self, flow_log_external):
        loc = flow_log_external["src_location"]
        assert "continent" in loc
        assert "country" in loc
        assert "asn" in loc

    def test_has_no_src_vpc(self, flow_log_external):
        assert "src_vpc" not in flow_log_external

    def test_has_dest_vpc(self, flow_log_external):
        assert "dest_vpc" in flow_log_external

    def test_has_traffic_fields(self, flow_log_external):
        assert "bytes_sent" in flow_log_external
        assert "packets_sent" in flow_log_external
        assert "reporter" in flow_log_external


class TestFlowLogGke:
    """Validate the GKE flow log fixture."""

    def test_has_src_gke_details(self, flow_log_gke):
        gke = flow_log_gke["src_gke_details"]
        assert "cluster" in gke
        assert "cluster_name" in gke["cluster"]
        assert "cluster_location" in gke["cluster"]
        assert "pod" in gke
        assert "pod_name" in gke["pod"]
        assert "pod_namespace" in gke["pod"]

    def test_has_dest_gke_details(self, flow_log_gke):
        gke = flow_log_gke["dest_gke_details"]
        assert "cluster" in gke
        assert "pod" in gke

    def test_gke_service_is_array(self, flow_log_gke):
        src_services = flow_log_gke["src_gke_details"]["service"]
        assert isinstance(src_services, list)
        assert len(src_services) >= 1

    def test_dest_has_multiple_services(self, flow_log_gke):
        """Dest pod backs two K8s services in this fixture."""
        dest_services = flow_log_gke["dest_gke_details"]["service"]
        assert len(dest_services) == 2

    def test_has_both_instances(self, flow_log_gke):
        """GKE nodes are still VMs with instance metadata."""
        assert "src_instance" in flow_log_gke
        assert "dest_instance" in flow_log_gke


class TestCloudEventVm:
    """Validate the VM-to-VM CloudEvent envelope."""

    def test_has_cloud_event_fields(self, cloud_event_vm):
        assert cloud_event_vm["specversion"] == "1.0"
        assert cloud_event_vm["type"] == "google.cloud.pubsub.topic.v1.messagePublished"
        assert "data" in cloud_event_vm

    def test_has_pubsub_message(self, cloud_event_vm):
        msg = cloud_event_vm["data"]["message"]
        assert "data" in msg
        assert "messageId" in msg
        assert "publishTime" in msg

    def test_base64_decodes_to_valid_json(self, cloud_event_vm):
        encoded = cloud_event_vm["data"]["message"]["data"]
        decoded = base64.b64decode(encoded).decode("utf-8")
        log_entry = json.loads(decoded)
        assert isinstance(log_entry, dict)

    def test_decoded_log_entry_has_expected_structure(self, cloud_event_vm):
        encoded = cloud_event_vm["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        assert "insertId" in log_entry
        assert "logName" in log_entry
        assert "resource" in log_entry
        assert "timestamp" in log_entry
        assert "jsonPayload" in log_entry

    def test_decoded_log_entry_resource_type(self, cloud_event_vm):
        encoded = cloud_event_vm["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        assert log_entry["resource"]["type"] == "gce_subnetwork"

    def test_decoded_json_payload_has_connection(self, cloud_event_vm):
        encoded = cloud_event_vm["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        flow_log = log_entry["jsonPayload"]
        assert "connection" in flow_log
        assert "src_ip" in flow_log["connection"]

    def test_decoded_json_payload_has_src_instance(self, cloud_event_vm):
        encoded = cloud_event_vm["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        flow_log = log_entry["jsonPayload"]
        assert "src_instance" in flow_log
        assert flow_log["src_instance"]["vm_name"] == "web-frontend-01"


class TestCloudEventExternal:
    """Validate the external traffic CloudEvent envelope."""

    def test_base64_decodes_to_valid_log_entry(self, cloud_event_external):
        encoded = cloud_event_external["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        assert "jsonPayload" in log_entry

    def test_decoded_payload_has_no_src_instance(self, cloud_event_external):
        encoded = cloud_event_external["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        flow_log = log_entry["jsonPayload"]
        assert "src_instance" not in flow_log

    def test_decoded_payload_has_dest_instance(self, cloud_event_external):
        encoded = cloud_event_external["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        flow_log = log_entry["jsonPayload"]
        assert "dest_instance" in flow_log
        assert flow_log["dest_instance"]["vm_name"] == "api-backend-02"

    def test_decoded_payload_has_src_location(self, cloud_event_external):
        encoded = cloud_event_external["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        flow_log = log_entry["jsonPayload"]
        assert "src_location" in flow_log


class TestBuildCloudEventHelper:
    """Validate the conftest build_cloud_event helper function."""

    def test_builds_valid_cloud_event(self, flow_log_src_vm):
        event = build_cloud_event(flow_log_src_vm)
        assert event["type"] == "google.cloud.pubsub.topic.v1.messagePublished"

    def test_round_trips_flow_log(self, flow_log_src_vm):
        """Flow log survives encode -> decode through build_cloud_event."""
        event = build_cloud_event(flow_log_src_vm)
        encoded = event["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        assert log_entry["jsonPayload"] == flow_log_src_vm

    def test_round_trips_gke_flow_log(self, flow_log_gke):
        event = build_cloud_event(flow_log_gke)
        encoded = event["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        assert log_entry["jsonPayload"] == flow_log_gke

    def test_custom_insert_id(self, flow_log_external):
        event = build_cloud_event(flow_log_external, insert_id="custom-id-999")
        encoded = event["data"]["message"]["data"]
        log_entry = json.loads(base64.b64decode(encoded))
        assert log_entry["insertId"] == "custom-id-999"
