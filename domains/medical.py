# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Medical domain adapter — patient records, treatment chains, clinical audit."""

import re
from typing import Any, Dict, List

from domains.base import (
    AuditEntry, Classification, ComplianceResult, DomainAdapter,
)


class MedicalAdapter(DomainAdapter):
    name = "medical"
    description = "Patient records, treatment chains, clinical audit trails"
    compliance_standards = ["HIPAA", "GDPR", "FDA 21 CFR Part 11"]
    record_types = [
        "patient_record", "treatment_plan", "lab_result",
        "prescription", "clinical_note", "anonymized_research",
    ]
    threat_vectors = [
        "unauthorized_access_to_phi",
        "data_exfiltration",
        "record_tampering",
        "insider_threat",
        "ransomware",
    ]

    classification_rules = {
        "patient_record": Classification.SOVEREIGN,
        "treatment_plan": Classification.RESTRICTED,
        "lab_result": Classification.RESTRICTED,
        "prescription": Classification.RESTRICTED,
        "clinical_note": Classification.SOVEREIGN,
        "anonymized_research": Classification.PUBLIC,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})
        record_type = record.get("record_type", "")

        if record_type == "patient_record":
            return bool(content.get("patient_id")) and bool(content.get("name"))
        if record_type == "prescription":
            return bool(content.get("patient_id")) and bool(content.get("medication"))
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []
        content = record.get("content", {})

        # HIPAA check
        violations = []
        if not record.get("record_id"):
            violations.append("Missing unique record identifier")
        patient_id = content.get("patient_id", "")
        if patient_id and not re.match(r'^MRN-\d{8,}$', patient_id):
            violations.append("Patient ID should follow MRN format (MRN-XXXXXXXX)")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="HIPAA",
            violations=violations,
        ))

        # FDA 21 CFR Part 11 check
        violations_fda = []
        if not record.get("validated"):
            violations_fda.append("Record not cryptographically signed")
        results.append(ComplianceResult(
            compliant=len(violations_fda) == 0,
            standard="FDA 21 CFR Part 11",
            violations=violations_fda,
        ))

        return results
