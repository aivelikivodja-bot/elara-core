# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""
Layer 1 Bridge — cryptographic validation of cognitive artifacts.

Subscribes to Layer 3 event bus, creates signed Layer 1 validation records
for significant cognitive events. Optional dependency on elara-layer1.

If elara_protocol is not installed, bridge is dormant — zero impact.

Every prediction, correction, and crystallized principle gets a cryptographic
proof — what was thought, when, signed by whom. Records chain via parent
references into a local DAG, producing a verifiable causal history.
"""

import hashlib
import json
import logging
import os
from typing import Optional

logger = logging.getLogger("elara.layer1_bridge")


def is_available() -> bool:
    """Check if elara_protocol (Layer 1) is installed."""
    try:
        import elara_protocol  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Event types that get validated (creation events only)
# ---------------------------------------------------------------------------

_VALIDATED_EVENTS = None  # Lazy — Events might not be imported yet


def _get_validated_events() -> dict:
    """Map of event type -> artifact type string. Lazy-loaded."""
    global _VALIDATED_EVENTS
    if _VALIDATED_EVENTS is None:
        from daemon.events import Events
        _VALIDATED_EVENTS = {
            Events.MODEL_CREATED: "model",
            Events.PREDICTION_MADE: "prediction",
            Events.PRINCIPLE_CRYSTALLIZED: "principle",
            Events.WORKFLOW_CREATED: "workflow",
            Events.CORRECTION_ADDED: "correction",
            Events.DREAM_COMPLETED: "dream",
            Events.EPISODE_ENDED: "episode",
            Events.HANDOFF_SAVED: "handoff",
            Events.SYNTHESIS_CREATED: "synthesis",
            Events.OUTCOME_RECORDED: "outcome",
        }
    return _VALIDATED_EVENTS


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class L1Bridge:
    """
    Bridges Layer 3 cognitive events to Layer 1 cryptographic validation.

    - Manages a persistent AI identity (Dilithium3 + SPHINCS+ dual-sign)
    - Subscribes to 10 creation events on the event bus
    - Creates signed ValidationRecords per cognitive artifact
    - Stores records in a local DAG (SQLite)
    - Chains records via parent references
    """

    def __init__(self):
        from elara_protocol.identity import Identity, EntityType, CryptoProfile
        from elara_protocol.dag import LocalDAG
        from elara_protocol.record import Classification
        from core.paths import get_paths

        self._paths = get_paths()
        self._Classification = Classification
        self._Identity = Identity
        self._EntityType = EntityType
        self._CryptoProfile = CryptoProfile

        # Load or generate identity
        self._identity = self._load_or_create_identity()

        # Open DAG
        self._dag = LocalDAG(self._paths.dag_file)

        # Track last validated hash for parent chaining
        self._last_validated_hash: Optional[str] = None
        self._init_last_hash()

        self._version = self._get_version()

        logger.info(
            "Layer 1 bridge initialized — identity=%s, dag_records=%d",
            self._identity.identity_hash[:12],
            len(self._dag),
        )

    def _load_or_create_identity(self):
        """Load existing identity or generate a new one."""
        identity_path = self._paths.identity_file
        if identity_path.exists():
            identity = self._Identity.load(identity_path)
            logger.info("Loaded identity: %s", identity.identity_hash[:12])
            return identity

        identity = self._Identity.generate(
            entity_type=self._EntityType.AI,
            profile=self._CryptoProfile.PROFILE_A,
        )
        identity.save(identity_path)
        # Restrict permissions — contains private keys
        os.chmod(identity_path, 0o600)
        logger.info("Generated new AI identity: %s", identity.identity_hash[:12])
        return identity

    def _init_last_hash(self):
        """Recover last_validated_hash from DAG tips."""
        tips = self._dag.tips()
        if tips:
            # Use the most recent tip as parent for next record
            self._last_validated_hash = tips[-1]

    def _get_version(self) -> str:
        """Get elara-core version for metadata."""
        try:
            from importlib.metadata import version
            return version("elara-core")
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def setup(self):
        """Subscribe to creation events on the event bus."""
        from daemon.events import bus

        for event_type in _get_validated_events():
            bus.on(
                event_type,
                self._handle_event,
                priority=50,
                source="layer1_bridge",
            )
        logger.info("Subscribed to %d event types", len(_get_validated_events()))

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle_event(self, event):
        """Route creation events to validation."""
        try:
            artifact_type = _get_validated_events().get(event.type)
            if artifact_type is None:
                return

            content = self._build_artifact_content(event.type, event.data)
            metadata = self._build_metadata(artifact_type, event.data)
            record_hash = self._validate(content, metadata)

            if record_hash:
                logger.debug(
                    "Validated %s artifact: %s -> %s",
                    artifact_type,
                    metadata.get("artifact_id", "?")[:12],
                    record_hash[:12],
                )
        except Exception:
            logger.exception("Bridge error handling %s", event.type)

    # ------------------------------------------------------------------
    # Content & metadata builders
    # ------------------------------------------------------------------

    def _build_artifact_content(self, event_type: str, event_data: dict) -> bytes:
        """Build deterministic content bytes from event data."""
        payload = {
            "event_type": event_type,
            "data": event_data,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")

    def _build_metadata(self, artifact_type: str, event_data: dict) -> dict:
        """Build metadata dict for the validation record."""
        # Extract artifact ID — events use various key names
        artifact_id = (
            event_data.get("id")
            or event_data.get("artifact_id")
            or event_data.get("model_id")
            or event_data.get("prediction_id")
            or event_data.get("principle_id")
            or event_data.get("workflow_id")
            or event_data.get("correction_id")
            or event_data.get("synthesis_id")
            or event_data.get("outcome_id")
            or event_data.get("episode_id")
            or ""
        )

        # Content summary — first 200 chars of the most descriptive field
        summary_source = (
            event_data.get("summary")
            or event_data.get("statement")
            or event_data.get("description")
            or event_data.get("title")
            or event_data.get("task")
            or event_data.get("concept")
            or ""
        )
        content_summary = str(summary_source)[:200]

        return {
            "artifact_type": artifact_type,
            "artifact_id": str(artifact_id),
            "domain": event_data.get("domain", "general"),
            "layer3_version": self._version,
            "content_summary": content_summary,
            "confidence": event_data.get("confidence", 1.0),
            "zone": "local",
            "witness_count": 0,
        }

    # ------------------------------------------------------------------
    # Core validation
    # ------------------------------------------------------------------

    def _validate(self, content: bytes, metadata: dict) -> Optional[str]:
        """
        Create, sign, and store a validation record.

        Returns the record hash on success, None on error.
        """
        from elara_protocol.record import ValidationRecord

        # Build parent list
        parents = [self._last_validated_hash] if self._last_validated_hash else []

        # Create record from content
        record = ValidationRecord.create(
            content=content,
            creator_public_key=self._identity.public_key,
            parents=parents,
            classification=self._Classification.SOVEREIGN,
            metadata=metadata,
        )

        # Sign — dual signature (Dilithium3 + SPHINCS+)
        signable = record.signable_bytes()
        record.signature = self._identity.sign(signable)
        if self._identity.profile == self._CryptoProfile.PROFILE_A:
            record.sphincs_signature = self._identity.sign_sphincs(signable)

        # Insert into DAG
        record_hash = self._dag.insert(record, verify_signature=True)

        # Update chain pointer
        self._last_validated_hash = record.id

        # Emit validation event
        from daemon.events import bus, Events
        bus.emit(
            Events.ARTIFACT_VALIDATED,
            {
                "record_id": record.id,
                "record_hash": record_hash,
                "artifact_type": metadata.get("artifact_type"),
                "artifact_id": metadata.get("artifact_id"),
            },
            source="layer1_bridge",
        )

        return record_hash

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """DAG statistics with artifact type breakdown."""
        base = self._dag.stats()
        base["identity"] = self._identity.identity_hash[:16] + "..."
        base["identity_entity"] = self._identity.entity_type.name
        return base

    def provenance(self, artifact_id: str) -> list:
        """Find all validation records for a given artifact ID."""
        all_records = self._dag.query(
            creator_key=self._identity.public_key,
            limit=10000,
        )
        return [
            {
                "record_id": r.id,
                "timestamp": r.timestamp,
                "artifact_type": r.metadata.get("artifact_type"),
                "content_summary": r.metadata.get("content_summary", ""),
            }
            for r in all_records
            if r.metadata.get("artifact_id") == artifact_id
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def teardown(self):
        """Close DAG connection."""
        try:
            self._dag.close()
            logger.info("Layer 1 bridge shut down")
        except Exception:
            logger.exception("Error closing DAG")


# ===========================================================================
# Module-level singleton
# ===========================================================================

_bridge: Optional[L1Bridge] = None


def get_bridge() -> Optional[L1Bridge]:
    """Return the bridge singleton, or None if not initialized."""
    return _bridge


def setup():
    """
    Initialize the Layer 1 bridge if elara_protocol is available.

    Called at MCP server startup. Silent no-op if Layer 1 not installed.
    """
    global _bridge
    if not is_available():
        logger.info("Layer 1 not installed — bridge dormant")
        return

    _bridge = L1Bridge()
    _bridge.setup()
