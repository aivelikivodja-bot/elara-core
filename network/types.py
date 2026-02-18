# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Layer 2 types — nodes, peers, attestations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class NodeType(Enum):
    """Role of a node in the network."""
    LEAF = "leaf"           # End-user node, stores own records
    RELAY = "relay"         # Forwards records, doesn't witness
    WITNESS = "witness"     # Can counter-sign records


class PeerState(Enum):
    """Lifecycle state of a discovered peer."""
    DISCOVERED = "discovered"
    CONNECTED = "connected"
    STALE = "stale"


@dataclass
class PeerInfo:
    """A known peer on the network."""
    identity_hash: str
    host: str
    port: int
    node_type: NodeType = NodeType.LEAF
    state: PeerState = PeerState.DISCOVERED
    last_seen: float = 0.0
    records_exchanged: int = 0

    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return {
            "identity_hash": self.identity_hash,
            "host": self.host,
            "port": self.port,
            "node_type": self.node_type.value,
            "state": self.state.value,
            "last_seen": self.last_seen,
            "records_exchanged": self.records_exchanged,
        }


@dataclass
class WitnessAttestation:
    """A witness counter-signature on a record."""
    record_id: str
    witness_identity_hash: str
    witness_signature: bytes
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "witness_identity_hash": self.witness_identity_hash,
            "witness_signature": self.witness_signature.hex(),
            "timestamp": self.timestamp,
        }
