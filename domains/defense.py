# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Defense domain adapter — secure comms, classified data chains."""

from typing import Any, Dict, List

from domains.base import (
    Classification, ComplianceResult, DomainAdapter,
)


class DefenseAdapter(DomainAdapter):
    name = "defense"
    description = "Secure communications, classified data chains"
    compliance_standards = ["NIST 800-171", "CMMC"]
    record_types = [
        "secure_message", "classified_document", "field_report",
        "intelligence_brief", "operation_log",
    ]
    threat_vectors = [
        "signal_interception",
        "insider_threat",
        "supply_chain_compromise",
        "advanced_persistent_threat",
        "quantum_cryptanalysis",
    ]

    classification_rules = {
        "secure_message": Classification.SOVEREIGN,
        "classified_document": Classification.SOVEREIGN,
        "field_report": Classification.RESTRICTED,
        "intelligence_brief": Classification.SOVEREIGN,
        "operation_log": Classification.RESTRICTED,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})

        # All defense records require cryptographic validation
        if not record.get("validated"):
            return False
        if not content.get("clearance_level"):
            return False
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []
        content = record.get("content", {})

        # NIST 800-171 check
        violations = []
        if not record.get("validated"):
            violations.append("CUI requires cryptographic protection")
        classification = self.classify(record)
        if classification not in (Classification.SOVEREIGN, Classification.RESTRICTED):
            violations.append("Defense records must not be PUBLIC or SHARED")
        if not content.get("clearance_level"):
            violations.append("Missing clearance level designation")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="NIST 800-171",
            violations=violations,
        ))

        return results
