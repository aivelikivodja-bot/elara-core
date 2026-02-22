# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""
Domain Adapter base class — the universal pattern for all 7 domains.

Each domain adapter defines:
  - Record schemas and types
  - Classification rules (sovereign, restricted, shared, public)
  - Compliance requirements
  - Validation logic
  - Threat model additions
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Classification(Enum):
    """Data classification levels."""
    SOVEREIGN = "sovereign"    # Never leaves origin node
    RESTRICTED = "restricted"  # Shared only with explicit consent
    SHARED = "shared"          # Available to authorized network peers
    PUBLIC = "public"          # Freely distributable


@dataclass
class ComplianceResult:
    """Result of a compliance check."""
    compliant: bool
    standard: str
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class AuditEntry:
    """Single entry in an audit trail."""
    timestamp: str
    action: str
    actor: str
    record_id: str
    details: Dict[str, Any] = field(default_factory=dict)


class DomainAdapter:
    """
    Base class for domain adapters. Each domain overrides these.

    The adapter pattern allows one protocol to serve all domains.
    Each adapter is thin — schema + classify + validate + compliance.
    """
    name: str = "base"
    description: str = ""
    classification_rules: Dict[str, Classification] = {}
    compliance_standards: List[str] = []
    record_types: List[str] = []
    threat_vectors: List[str] = []

    def classify(self, record: Dict[str, Any]) -> Classification:
        """Classify a record based on domain rules."""
        record_type = record.get("record_type", "")
        return self.classification_rules.get(record_type, Classification.SOVEREIGN)

    def validate(self, record: Dict[str, Any]) -> bool:
        """Validate a record against domain schema."""
        required = ["record_id", "record_type", "content"]
        return all(record.get(k) for k in required)

    def compliance_check(self, record: Dict[str, Any]) -> List[ComplianceResult]:
        """Check record against all applicable compliance standards."""
        return []

    def audit_trail(self, record_id: str, records: List[Dict]) -> List[AuditEntry]:
        """Build audit trail for a record from DAG history."""
        return []

    def get_record_schema(self, record_type: str) -> Dict[str, Any]:
        """Return the expected schema for a record type."""
        return {"record_id": "str", "record_type": "str", "content": "dict"}

    def info(self) -> Dict[str, Any]:
        """Return adapter metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "compliance_standards": self.compliance_standards,
            "record_types": self.record_types,
            "threat_vectors": self.threat_vectors,
        }
