# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Agriculture domain adapter — farm sensors, food supply chain provenance."""

from typing import Any, Dict, List

from domains.base import (
    Classification, ComplianceResult, DomainAdapter,
)


class AgricultureAdapter(DomainAdapter):
    name = "agriculture"
    description = "Farm sensors, food supply chain, environmental monitoring"
    compliance_standards = ["FDA FSMA", "GlobalG.A.P."]
    record_types = [
        "sensor_reading", "harvest_record", "supply_chain_event",
        "inspection_report", "pesticide_application", "soil_analysis",
    ]
    threat_vectors = [
        "sensor_spoofing",
        "provenance_fraud",
        "supply_chain_contamination",
        "label_fraud",
    ]

    classification_rules = {
        "sensor_reading": Classification.SHARED,
        "harvest_record": Classification.SHARED,
        "supply_chain_event": Classification.SHARED,
        "inspection_report": Classification.RESTRICTED,
        "pesticide_application": Classification.RESTRICTED,
        "soil_analysis": Classification.SHARED,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})
        record_type = record.get("record_type", "")

        if record_type == "sensor_reading":
            return bool(content.get("sensor_id")) and "value" in content
        if record_type == "harvest_record":
            return bool(content.get("crop")) and bool(content.get("field_id"))
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []
        content = record.get("content", {})

        # FDA FSMA check
        violations = []
        if not record.get("record_id"):
            violations.append("Missing traceability identifier")
        record_type = record.get("record_type", "")
        if record_type == "supply_chain_event":
            if not content.get("origin"):
                violations.append("Supply chain event missing origin")
            if not content.get("destination"):
                violations.append("Supply chain event missing destination")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="FDA FSMA",
            violations=violations,
        ))

        return results
