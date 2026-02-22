# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Industrial domain adapter — sensors, supply chain, manufacturing QC."""

from typing import Any, Dict, List

from domains.base import (
    Classification, ComplianceResult, DomainAdapter,
)


class IndustrialAdapter(DomainAdapter):
    name = "industrial"
    description = "Sensors, supply chain, manufacturing quality control"
    compliance_standards = ["ISO 9001", "ISO 13485", "IEC 62443"]
    record_types = [
        "sensor_reading", "quality_report", "supply_chain_event",
        "maintenance_log", "calibration_record", "incident_report",
    ]
    threat_vectors = [
        "sensor_spoofing",
        "supply_chain_injection",
        "firmware_tampering",
        "industrial_espionage",
        "scada_compromise",
    ]

    classification_rules = {
        "sensor_reading": Classification.SHARED,
        "quality_report": Classification.RESTRICTED,
        "supply_chain_event": Classification.SHARED,
        "maintenance_log": Classification.RESTRICTED,
        "calibration_record": Classification.RESTRICTED,
        "incident_report": Classification.SOVEREIGN,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})
        record_type = record.get("record_type", "")

        if record_type == "sensor_reading":
            return bool(content.get("sensor_id")) and "value" in content
        if record_type == "quality_report":
            return bool(content.get("batch_id"))
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []
        content = record.get("content", {})

        # ISO 9001 check
        violations = []
        if not record.get("record_id"):
            violations.append("Missing traceability identifier")
        if not content.get("timestamp"):
            violations.append("Missing timestamp for audit trail")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="ISO 9001",
            violations=violations,
        ))

        # IEC 62443 check (industrial cybersecurity)
        violations_iec = []
        record_type = record.get("record_type", "")
        if record_type == "sensor_reading" and not record.get("validated"):
            violations_iec.append("Sensor data not cryptographically validated")
        results.append(ComplianceResult(
            compliant=len(violations_iec) == 0,
            standard="IEC 62443",
            violations=violations_iec,
        ))

        return results
