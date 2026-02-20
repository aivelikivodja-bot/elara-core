# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Bootstrap — seed node connection + GitHub peer list fallback.

Discovery priority:
  1. Seed nodes from elara-network.json config
  2. Hardcoded peers from elara-peers.json
  3. GitHub raw peers.json fallback (if mDNS and seeds both fail)
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("elara.network.bootstrap")

# Public peer list URL — fetched as last-resort fallback
GITHUB_PEERS_URL = (
    "https://raw.githubusercontent.com/navigatorbuilds/elara-core/main/peers.json"
)

# Default seed nodes (hardcoded, always tried first)
DEFAULT_SEEDS = [
    {"host": "node.navigatorbuilds.com", "port": 9473, "node_type": "relay"},
]

FETCH_TIMEOUT = 5  # seconds


def load_network_config(config_path: Path) -> dict:
    """Load network config from elara-network.json.

    Returns defaults if file doesn't exist or is invalid.
    """
    defaults = {
        "enabled": True,
        "node_type": "leaf",
        "port": 0,  # 0 = random available port
        "seed_nodes": DEFAULT_SEEDS,
    }

    if not config_path.exists():
        return defaults

    try:
        data = json.loads(config_path.read_text())
        # Merge with defaults (config values override)
        for key in defaults:
            if key not in data:
                data[key] = defaults[key]
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load network config: %s", e)
        return defaults


def save_network_config(config_path: Path, config: dict) -> None:
    """Write network config to elara-network.json."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def resolve_seed_peers(config: dict) -> List[dict]:
    """Extract seed node entries from network config.

    Returns list of peer dicts ready for PeerDiscovery.add_peer().
    """
    seeds = config.get("seed_nodes", DEFAULT_SEEDS)
    result = []
    for seed in seeds:
        host = seed.get("host", "")
        port = seed.get("port", 0)
        if host and port:
            result.append({
                "host": host,
                "port": port,
                "node_type": seed.get("node_type", "relay"),
                "identity_hash": seed.get("identity_hash", f"seed-{host}:{port}"),
            })
    return result


def fetch_github_peers() -> List[dict]:
    """Fetch peer list from GitHub as last-resort fallback.

    Non-blocking-ish: uses urllib with timeout. Returns empty list on failure.
    """
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            GITHUB_PEERS_URL,
            headers={"User-Agent": "elara-core"},
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        peers = []
        for node in data.get("seed_nodes", []):
            host = node.get("host", "")
            port = node.get("port", 0)
            if host and port:
                peers.append({
                    "host": host,
                    "port": port,
                    "node_type": node.get("type", "relay"),
                    "identity_hash": f"github-{host}:{port}",
                })

        logger.info("Fetched %d peers from GitHub fallback", len(peers))
        return peers

    except Exception as e:
        logger.debug("GitHub peer fallback failed (this is fine): %s", e)
        return []


def bootstrap_peers(
    config: dict,
    peers_file: Optional[Path] = None,
) -> List[dict]:
    """Resolve all peers from all sources.

    Priority:
      1. Seed nodes from config
      2. Hardcoded peers from peers file
      3. GitHub fallback (only if no peers found)

    Returns deduplicated list of peer dicts.
    """
    seen: Dict[str, dict] = {}

    # 1. Seeds from config
    for peer in resolve_seed_peers(config):
        key = f"{peer['host']}:{peer['port']}"
        seen[key] = peer

    # 2. Hardcoded peers file
    if peers_file and peers_file.exists():
        try:
            data = json.loads(peers_file.read_text())
            for entry in data.get("peers", []):
                host = entry.get("host", "")
                port = entry.get("port", 0)
                if host and port:
                    key = f"{host}:{port}"
                    if key not in seen:
                        seen[key] = {
                            "host": host,
                            "port": port,
                            "node_type": entry.get("node_type", "leaf"),
                            "identity_hash": entry.get(
                                "identity_hash", f"file-{host}:{port}"
                            ),
                        }
        except (json.JSONDecodeError, OSError):
            pass

    # 3. GitHub fallback (only if we have zero peers)
    if not seen:
        for peer in fetch_github_peers():
            key = f"{peer['host']}:{peer['port']}"
            if key not in seen:
                seen[key] = peer

    return list(seen.values())


def check_version_async() -> Optional[str]:
    """Check PyPI for newer version. Returns upgrade message or None.

    Non-blocking: timeout 3s. Fails silently.
    """
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            "https://pypi.org/pypi/elara-core/json",
            headers={"User-Agent": "elara-core"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())

        latest = data.get("info", {}).get("version", "")
        if not latest:
            return None

        # Compare with current version
        try:
            from importlib.metadata import version as get_version
            current = get_version("elara-core")
        except Exception:
            return None

        if latest != current and _version_newer(latest, current):
            return (
                f"Update available: v{current} -> v{latest}\n"
                f"  pip install --upgrade elara-core"
            )
        return None

    except Exception:
        return None


def _version_newer(latest: str, current: str) -> bool:
    """Simple version comparison (handles x.y.z format)."""
    try:
        def _parts(v: str) -> tuple:
            return tuple(int(p) for p in v.split(".")[:3])
        return _parts(latest) > _parts(current)
    except (ValueError, TypeError):
        return False
