# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Finance domain adapter — banking transactions, regulatory compliance."""

from typing import Any, Dict, List

from domains.base import (
    Classification, ComplianceResult, DomainAdapter,
)


class FinanceAdapter(DomainAdapter):
    name = "finance"
    description = "Banking transactions, regulatory compliance, public records"
    compliance_standards = ["SOX", "PCI-DSS", "AML/KYC"]
    record_types = [
        "transaction", "account_record", "regulatory_filing",
        "audit_log", "kyc_verification", "public_disclosure",
    ]
    threat_vectors = [
        "transaction_fraud",
        "money_laundering",
        "insider_trading",
        "data_breach",
        "regulatory_evasion",
    ]

    classification_rules = {
        "transaction": Classification.RESTRICTED,
        "account_record": Classification.SOVEREIGN,
        "regulatory_filing": Classification.RESTRICTED,
        "audit_log": Classification.SOVEREIGN,
        "kyc_verification": Classification.SOVEREIGN,
        "public_disclosure": Classification.PUBLIC,
    }

    def validate(self, record: Dict[str, Any]) -> bool:
        if not super().validate(record):
            return False
        content = record.get("content", {})
        record_type = record.get("record_type", "")

        if record_type == "transaction":
            return bool(content.get("amount")) and bool(content.get("currency"))
        if record_type == "kyc_verification":
            return bool(content.get("entity_id"))
        return True

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        results = []
        content = record.get("content", {})

        # SOX check
        violations = []
        if not record.get("validated"):
            violations.append("Financial record requires cryptographic validation")
        if not record.get("record_id"):
            violations.append("Missing audit trail identifier")
        results.append(ComplianceResult(
            compliant=len(violations) == 0,
            standard="SOX",
            violations=violations,
        ))

        # AML/KYC check
        violations_aml = []
        record_type = record.get("record_type", "")
        if record_type == "transaction":
            amount = content.get("amount", 0)
            if isinstance(amount, (int, float)) and amount > 10000:
                if not content.get("kyc_reference"):
                    violations_aml.append("Transaction >$10,000 requires KYC reference")
        results.append(ComplianceResult(
            compliant=len(violations_aml) == 0,
            standard="AML/KYC",
            violations=violations_aml,
        ))

        return results
