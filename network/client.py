# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Network client — talk to remote Elara nodes."""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger("elara.network.client")

DEFAULT_TIMEOUT = 10.0


class NetworkClient:
    """HTTP client for talking to remote Elara network nodes."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self._timeout = timeout
        self._session = None

    async def _get_session(self):
        if self._session is None:
            from aiohttp import ClientSession, ClientTimeout
            self._session = ClientSession(
                timeout=ClientTimeout(total=self._timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def submit_record(self, host: str, port: int, wire_bytes: bytes) -> dict:
        """Submit a record's wire bytes to a remote node."""
        session = await self._get_session()
        url = f"http://{host}:{port}/records"
        try:
            async with session.post(url, data=wire_bytes) as resp:
                return await resp.json()
        except Exception as e:
            logger.error("Failed to submit record to %s:%d — %s", host, port, e)
            return {"error": str(e)}

    async def query_records(
        self, host: str, port: int, since: float = 0, limit: int = 20
    ) -> List[dict]:
        """Query recent records from a remote node."""
        session = await self._get_session()
        url = f"http://{host}:{port}/records"
        params = {"since": str(since), "limit": str(limit)}
        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data.get("records", [])
        except Exception as e:
            logger.error("Failed to query records from %s:%d — %s", host, port, e)
            return []

    async def request_witness(
        self, host: str, port: int, wire_bytes: bytes,
        verify_key: Optional[bytes] = None, signable: Optional[bytes] = None,
    ) -> dict:
        """Request a witness attestation from a remote node.

        Args:
            verify_key: If provided, verify the witness signature before returning.
            signable: The signable bytes of the record (needed for verification).
        """
        session = await self._get_session()
        url = f"http://{host}:{port}/witness"
        try:
            async with session.post(url, data=wire_bytes) as resp:
                result = await resp.json()

            # Optionally verify the witness signature
            if verify_key and signable and "signature" in result:
                from network.types import WitnessAttestation
                sig_bytes = bytes.fromhex(result["signature"])
                if not WitnessAttestation.verify(signable, sig_bytes, verify_key):
                    return {"error": "witness signature verification failed"}
                result["verified"] = True

            return result
        except Exception as e:
            logger.error("Failed to request witness from %s:%d — %s", host, port, e)
            return {"error": str(e)}

    async def get_status(self, host: str, port: int) -> dict:
        """Get status from a remote node."""
        session = await self._get_session()
        url = f"http://{host}:{port}/status"
        try:
            async with session.get(url) as resp:
                return await resp.json()
        except Exception as e:
            logger.error("Failed to get status from %s:%d — %s", host, port, e)
            return {"error": str(e)}

    async def ping(self, host: str, port: int) -> Optional[float]:
        """Ping a remote node. Returns RTT in seconds, or None on failure."""
        import time
        session = await self._get_session()
        url = f"http://{host}:{port}/ping"
        try:
            t0 = time.monotonic()
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("pong"):
                    return time.monotonic() - t0
            return None
        except Exception:
            return None

    async def query_attestations(self, host: str, port: int, record_id: str) -> List[dict]:
        """Query attestations for a record from a remote node."""
        session = await self._get_session()
        url = f"http://{host}:{port}/attestations"
        params = {"record_id": record_id}
        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data.get("attestations", [])
        except Exception as e:
            logger.error("Failed to query attestations from %s:%d — %s", host, port, e)
            return []
