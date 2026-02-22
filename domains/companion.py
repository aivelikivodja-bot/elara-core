# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Companion domain adapter — AI memory, corrections, session continuity."""

from typing import Any, Dict, List

from domains.base import (
    Classification, ComplianceResult, DomainAdapter,
)


class CompanionAdapter(DomainAdapter):
    name = "companion"
    description = "AI memory, session continuity, corrections"
    compliance_standards = ["AI Transparency", "Data Sovereignty"]
    record_types = [
        "memory", "correction", "handoff", "session_state",
    ]
    threat_vectors = [
        "memory_injection",
        "personality_drift",
        "context_poisoning",
        "session_hijacking",
    ]

    classification_rules = {
        "memory": Classification.SOVEREIGN,
        "correction": Classification.SOVEREIGN,
        "handoff": Classification.SOVEREIGN,
        "session_state": Classification.SOVEREIGN,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})
        record_type = record.get("record_type", "")

        if record_type == "memory":
            return bool(content.get("text"))
        if record_type == "correction":
            return bool(content.get("mistake")) and bool(content.get("correction"))
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []

        violations = []
        classification = self.classify(record)
        if classification != Classification.SOVEREIGN:
            violations.append("AI companion data must be SOVEREIGN classification")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="Data Sovereignty",
            violations=violations,
        ))

        return results
