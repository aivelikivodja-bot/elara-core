# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Witness manager — stores and queries attestations with SQLite persistence."""

import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from network.types import WitnessAttestation

logger = logging.getLogger("elara.network.witness")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attestations (
    record_id          TEXT NOT NULL,
    witness_identity   TEXT NOT NULL,
    witness_signature  BLOB NOT NULL,
    timestamp          REAL NOT NULL,
    PRIMARY KEY (record_id, witness_identity)
);
CREATE INDEX IF NOT EXISTS idx_attestations_record
    ON attestations(record_id);
"""


class WitnessManager:
    """
    SQLite-backed attestation store.

    Maps record_id → list of WitnessAttestation.
    Falls back to in-memory if no db_path provided.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # In-memory fallback when no db_path
        self._memory: Dict[str, List[WitnessAttestation]] = {}

        if db_path:
            self._conn = sqlite3.connect(str(db_path))
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            logger.info("Witness store opened: %s", db_path)

    def add_attestation(self, attestation: WitnessAttestation) -> None:
        """Store an attestation. Deduplicates by (record_id, witness_identity)."""
        if self._conn:
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO attestations "
                    "(record_id, witness_identity, witness_signature, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        attestation.record_id,
                        attestation.witness_identity_hash,
                        attestation.witness_signature,
                        attestation.timestamp,
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                logger.exception("Failed to persist attestation")
                return
        else:
            # In-memory fallback
            rid = attestation.record_id
            if rid not in self._memory:
                self._memory[rid] = []
            existing = {a.witness_identity_hash for a in self._memory[rid]}
            if attestation.witness_identity_hash in existing:
                return
            self._memory[rid].append(attestation)

        logger.debug(
            "Attestation stored: record=%s witness=%s",
            attestation.record_id[:12],
            attestation.witness_identity_hash[:12],
        )

    def get_attestations(self, record_id: str) -> List[WitnessAttestation]:
        """Get all attestations for a record."""
        if self._conn:
            rows = self._conn.execute(
                "SELECT record_id, witness_identity, witness_signature, timestamp "
                "FROM attestations WHERE record_id = ?",
                (record_id,),
            ).fetchall()
            return [
                WitnessAttestation(
                    record_id=r[0],
                    witness_identity_hash=r[1],
                    witness_signature=r[2],
                    timestamp=r[3],
                )
                for r in rows
            ]
        return self._memory.get(record_id, [])

    def witness_count(self, record_id: str) -> int:
        """Count unique witnesses for a record."""
        if self._conn:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM attestations WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            return row[0] if row else 0
        return len(self._memory.get(record_id, []))

    def stats(self) -> dict:
        """Summary statistics."""
        if self._conn:
            records = self._conn.execute(
                "SELECT COUNT(DISTINCT record_id) FROM attestations"
            ).fetchone()[0]
            total = self._conn.execute(
                "SELECT COUNT(*) FROM attestations"
            ).fetchone()[0]
            return {"records_witnessed": records, "total_attestations": total}
        total = sum(len(v) for v in self._memory.values())
        return {
            "records_witnessed": len(self._memory),
            "total_attestations": total,
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
