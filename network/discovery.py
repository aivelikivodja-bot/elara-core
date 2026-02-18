# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Peer discovery — mDNS (LAN) + hardcoded peers (WAN)."""

import json
import logging
import socket
import time
from pathlib import Path
from typing import Dict, List, Optional

from network.types import NodeType, PeerInfo, PeerState

logger = logging.getLogger("elara.network.discovery")

SERVICE_TYPE = "_elara._tcp.local."
STALE_TIMEOUT = 120.0  # seconds before peer is marked stale


class PeerDiscovery:
    """
    Discovers Elara peers via mDNS and hardcoded peer lists.

    mDNS provides zero-config LAN discovery. Hardcoded peers support
    WAN/cloud deployments.
    """

    def __init__(self, identity_hash: str, port: int, peers_file: Optional[Path] = None):
        self._identity_hash = identity_hash
        self._port = port
        self._peers: Dict[str, PeerInfo] = {}
        self._peers_file = peers_file
        self._zeroconf = None
        self._browser = None
        self._service_info = None
        self._running = False

    @property
    def peers(self) -> List[PeerInfo]:
        """All known peers (excluding self), freshness-checked."""
        now = time.time()
        result = []
        for peer in self._peers.values():
            if now - peer.last_seen > STALE_TIMEOUT:
                peer.state = PeerState.STALE
            result.append(peer)
        return result

    @property
    def connected_peers(self) -> List[PeerInfo]:
        """Only peers in CONNECTED state."""
        return [p for p in self.peers if p.state == PeerState.CONNECTED]

    def start(self) -> None:
        """Start mDNS registration and browsing."""
        if self._running:
            return

        # Load hardcoded peers
        self._load_hardcoded_peers()

        # Try mDNS (optional dependency)
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo
            import socket as _sock

            self._zeroconf = Zeroconf()

            # Register our service
            hostname = _sock.gethostname()
            self._service_info = ServiceInfo(
                SERVICE_TYPE,
                f"elara-{self._identity_hash[:8]}.{SERVICE_TYPE}",
                addresses=[_sock.inet_aton(_sock.gethostbyname(hostname))],
                port=self._port,
                properties={
                    b"identity": self._identity_hash.encode(),
                    b"node_type": b"leaf",
                },
            )
            self._zeroconf.register_service(self._service_info)

            # Browse for peers
            self._browser = ServiceBrowser(
                self._zeroconf,
                SERVICE_TYPE,
                handlers=[self._on_service_state_change],
            )

            logger.info("mDNS discovery started on port %d", self._port)

        except ImportError:
            logger.info("zeroconf not installed — mDNS disabled, using hardcoded peers only")
        except Exception:
            logger.exception("mDNS setup failed — using hardcoded peers only")

        self._running = True

        # Emit event
        try:
            from daemon.events import bus, Events
            bus.emit(Events.NETWORK_STARTED, {
                "port": self._port,
                "hardcoded_peers": len(self._peers),
            }, source="network.discovery")
        except Exception:
            pass

    def stop(self) -> None:
        """Stop mDNS and clean up."""
        if not self._running:
            return

        if self._zeroconf and self._service_info:
            try:
                self._zeroconf.unregister_service(self._service_info)
            except Exception:
                pass
        if self._zeroconf:
            try:
                self._zeroconf.close()
            except Exception:
                pass

        self._zeroconf = None
        self._browser = None
        self._service_info = None
        self._running = False

        try:
            from daemon.events import bus, Events
            bus.emit(Events.NETWORK_STOPPED, {}, source="network.discovery")
        except Exception:
            pass

        logger.info("Discovery stopped")

    def _load_hardcoded_peers(self) -> None:
        """Load peers from JSON file."""
        if not self._peers_file or not self._peers_file.exists():
            return

        try:
            data = json.loads(self._peers_file.read_text())
            for entry in data.get("peers", []):
                host = entry.get("host", "")
                port = entry.get("port", 0)
                identity = entry.get("identity_hash", f"unknown-{host}:{port}")
                if host and port:
                    peer = PeerInfo(
                        identity_hash=identity,
                        host=host,
                        port=port,
                        node_type=NodeType(entry.get("node_type", "leaf")),
                        state=PeerState.DISCOVERED,
                        last_seen=time.time(),
                    )
                    self._peers[identity] = peer
            logger.info("Loaded %d hardcoded peers", len(self._peers))
        except Exception:
            logger.exception("Failed to load peers file")

    def _on_service_state_change(self, zeroconf, service_type, name, state_change) -> None:
        """mDNS callback: peer appeared or disappeared."""
        try:
            from zeroconf import ServiceStateChange

            if state_change == ServiceStateChange.Added:
                info = zeroconf.get_service_info(service_type, name)
                if info and info.properties:
                    identity = info.properties.get(b"identity", b"").decode()
                    if identity and identity != self._identity_hash:
                        addresses = info.parsed_addresses()
                        host = addresses[0] if addresses else ""
                        peer = PeerInfo(
                            identity_hash=identity,
                            host=host,
                            port=info.port,
                            state=PeerState.DISCOVERED,
                            last_seen=time.time(),
                        )
                        self._peers[identity] = peer
                        logger.info("Discovered peer: %s at %s:%d", identity[:12], host, info.port)

                        from daemon.events import bus, Events
                        bus.emit(Events.PEER_DISCOVERED, peer.to_dict(), source="network.discovery")

            elif state_change == ServiceStateChange.Removed:
                # Find and mark stale
                for pid, peer in self._peers.items():
                    if name.startswith(f"elara-{pid[:8]}"):
                        peer.state = PeerState.STALE
                        logger.info("Peer lost: %s", pid[:12])

                        from daemon.events import bus, Events
                        bus.emit(Events.PEER_LOST, {"identity_hash": pid}, source="network.discovery")
                        break
        except Exception:
            logger.exception("mDNS callback error")

    def add_peer(self, host: str, port: int, identity_hash: str = "") -> PeerInfo:
        """Manually add a peer."""
        identity = identity_hash or f"manual-{host}:{port}"
        peer = PeerInfo(
            identity_hash=identity,
            host=host,
            port=port,
            state=PeerState.DISCOVERED,
            last_seen=time.time(),
        )
        self._peers[identity] = peer
        return peer

    def stats(self) -> dict:
        return {
            "running": self._running,
            "mdns": self._zeroconf is not None,
            "total_peers": len(self._peers),
            "connected": len(self.connected_peers),
            "stale": len([p for p in self.peers if p.state == PeerState.STALE]),
        }
