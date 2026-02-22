# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Education domain adapter — academic records, research integrity."""

from typing import Any, Dict, List

from domains.base import (
    Classification, ComplianceResult, DomainAdapter,
)


class EducationAdapter(DomainAdapter):
    name = "education"
    description = "Academic records, research data integrity, credentials"
    compliance_standards = ["FERPA", "Research Integrity"]
    record_types = [
        "student_record", "research_data", "credential",
        "publication", "peer_review",
    ]
    threat_vectors = [
        "grade_tampering",
        "research_fraud",
        "credential_forgery",
        "data_fabrication",
    ]

    classification_rules = {
        "student_record": Classification.SOVEREIGN,
        "research_data": Classification.RESTRICTED,
        "credential": Classification.SHARED,
        "publication": Classification.PUBLIC,
        "peer_review": Classification.RESTRICTED,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})
        record_type = record.get("record_type", "")

        if record_type == "student_record":
            return bool(content.get("student_id"))
        if record_type == "research_data":
            return bool(content.get("dataset_id"))
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []

        violations = []
        record_type = record.get("record_type", "")
        if record_type == "student_record":
            classification = self.classify(record)
            if classification != Classification.SOVEREIGN:
                violations.append("Student records must be SOVEREIGN under FERPA")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="FERPA",
            violations=violations,
        ))

        return results
