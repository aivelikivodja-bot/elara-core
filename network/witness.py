# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Witness manager — stores and queries attestations."""

import logging
from typing import Dict, List

from network.types import WitnessAttestation

logger = logging.getLogger("elara.network.witness")


class WitnessManager:
    """
    In-memory attestation store.

    Maps record_id → list of WitnessAttestation.
    MVP: memory-only. Production: SQLite persistence.
    """

    def __init__(self):
        self._attestations: Dict[str, List[WitnessAttestation]] = {}

    def add_attestation(self, attestation: WitnessAttestation) -> None:
        """Store an attestation. Deduplicates by witness identity."""
        record_id = attestation.record_id
        if record_id not in self._attestations:
            self._attestations[record_id] = []

        # Dedup — one attestation per witness per record
        existing = {a.witness_identity_hash for a in self._attestations[record_id]}
        if attestation.witness_identity_hash not in existing:
            self._attestations[record_id].append(attestation)
            logger.debug(
                "Attestation stored: record=%s witness=%s",
                record_id[:12],
                attestation.witness_identity_hash[:12],
            )

    def get_attestations(self, record_id: str) -> List[WitnessAttestation]:
        """Get all attestations for a record."""
        return self._attestations.get(record_id, [])

    def witness_count(self, record_id: str) -> int:
        """Count unique witnesses for a record."""
        return len(self._attestations.get(record_id, []))

    def stats(self) -> dict:
        """Summary statistics."""
        total_attestations = sum(len(v) for v in self._attestations.values())
        return {
            "records_witnessed": len(self._attestations),
            "total_attestations": total_attestations,
        }
