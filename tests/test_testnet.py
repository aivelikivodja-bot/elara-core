# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Integration tests — Layer 2 record exchange, witnessing, and testnet hardening."""

import asyncio
import time

import pytest

# Skip entire module if elara_protocol not installed
pytest.importorskip("elara_protocol")

from elara_protocol.identity import Identity, EntityType, CryptoProfile
from elara_protocol.record import ValidationRecord, Classification
from elara_protocol.dag import LocalDAG

from network.server import NetworkServer
from network.client import NetworkClient
from network.trust import TrustScore
from network.ratelimit import PeerRateLimiter
from network.types import PeerInfo, PeerState, NodeType, WitnessAttestation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def node_a(tmp_path):
    """Node A: identity + DAG + server on port 19473."""
    identity = Identity.generate(EntityType.AI, CryptoProfile.PROFILE_A)
    (tmp_path / "a").mkdir()
    dag = LocalDAG(tmp_path / "a" / "dag.sqlite")
    server = NetworkServer(identity, dag, port=19473)
    yield {"identity": identity, "dag": dag, "server": server, "port": 19473}
    dag.close()


@pytest.fixture
def node_b(tmp_path):
    """Node B: identity + DAG + server on port 19474."""
    identity = Identity.generate(EntityType.AI, CryptoProfile.PROFILE_A)
    (tmp_path / "b").mkdir()
    dag = LocalDAG(tmp_path / "b" / "dag.sqlite")
    server = NetworkServer(identity, dag, port=19474)
    yield {"identity": identity, "dag": dag, "server": server, "port": 19474}
    dag.close()


@pytest.fixture
def node_c(tmp_path):
    """Node C: identity + DAG + server on port 19475."""
    identity = Identity.generate(EntityType.AI, CryptoProfile.PROFILE_A)
    (tmp_path / "c").mkdir()
    dag = LocalDAG(tmp_path / "c" / "dag.sqlite")
    server = NetworkServer(identity, dag, port=19475)
    yield {"identity": identity, "dag": dag, "server": server, "port": 19475}
    dag.close()


def _create_signed_record(identity, dag, content=b"test-record"):
    """Helper: create, sign, and insert a record."""
    tips = dag.tips()
    parents = [tips[-1]] if tips else []

    record = ValidationRecord.create(
        content=content,
        creator_public_key=identity.public_key,
        parents=parents,
        classification=Classification.PUBLIC,
        metadata={"source": "test"},
    )
    signable = record.signable_bytes()
    record.signature = identity.sign(signable)
    if identity.profile == CryptoProfile.PROFILE_A:
        record.sphincs_signature = identity.sign_sphincs(signable)

    dag.insert(record, verify_signature=True)
    return record


# ---------------------------------------------------------------------------
# Original Tests (unchanged)
# ---------------------------------------------------------------------------

class TestTwoNodeExchange:
    """End-to-end tests for 2-node record exchange."""

    @pytest.mark.asyncio
    async def test_node_status_endpoint(self, node_a):
        """GET /status returns correct identity and DAG info."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            status = await client.get_status("127.0.0.1", node_a["port"])
            await client.close()

            assert status["identity"] == node_a["identity"].identity_hash
            assert status["entity_type"] == "AI"
            assert status["dag_records"] == 0
            assert status["port"] == node_a["port"]
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_nodes_exchange_record(self, node_a, node_b):
        """Full flow: Node A creates record, Node B syncs it."""
        await node_a["server"].start()
        await node_b["server"].start()
        try:
            # Node A creates a record
            record = _create_signed_record(
                node_a["identity"], node_a["dag"], b"exchange-test"
            )
            assert node_a["dag"].stats()["total_records"] == 1

            client = NetworkClient(timeout=5.0)

            # Node B queries records from Node A
            remote = await client.query_records("127.0.0.1", node_a["port"])
            assert len(remote) == 1
            assert remote[0]["record_id"] == record.id

            # Node B inserts the synced record
            wire = bytes.fromhex(remote[0]["wire_hex"])
            synced = ValidationRecord.from_bytes(wire)
            node_b["dag"].insert(synced, verify_signature=False)

            assert node_b["dag"].stats()["total_records"] == 1

            # Verify it's the same record
            retrieved = node_b["dag"].get(record.id)
            assert retrieved is not None
            assert retrieved.id == record.id

            await client.close()
        finally:
            await node_a["server"].stop()
            await node_b["server"].stop()

    @pytest.mark.asyncio
    async def test_nodes_witness_record(self, node_a, node_b):
        """Full flow: Node A creates record, Node B witnesses it, trust goes up."""
        await node_a["server"].start()
        await node_b["server"].start()
        try:
            # Node A creates a record
            record = _create_signed_record(
                node_a["identity"], node_a["dag"], b"witness-test"
            )

            client = NetworkClient(timeout=5.0)

            # Node B requests witness from Node A
            wire = record.to_bytes()
            result = await client.request_witness("127.0.0.1", node_a["port"], wire)

            assert "error" not in result
            assert result["witness"] == node_a["identity"].identity_hash
            assert result["record_id"] == record.id

            # Verify attestation stored on Node A's server
            wm = node_a["server"]._witness_manager
            assert wm.witness_count(record.id) == 1

            attestations = wm.get_attestations(record.id)
            assert len(attestations) == 1
            assert attestations[0].witness_identity_hash == node_a["identity"].identity_hash

            # Verify trust score
            score = TrustScore.compute(wm.witness_count(record.id))
            assert abs(score - 0.5) < 0.01
            assert TrustScore.level(score) == "moderate"

            await client.close()
        finally:
            await node_a["server"].stop()
            await node_b["server"].stop()

    @pytest.mark.asyncio
    async def test_submit_record_to_remote(self, node_a, node_b):
        """Node A pushes a record directly to Node B via POST /records."""
        await node_b["server"].start()
        try:
            # Node A creates a record
            record = _create_signed_record(
                node_a["identity"], node_a["dag"], b"push-test"
            )

            client = NetworkClient(timeout=5.0)

            # Push to Node B
            wire = record.to_bytes()
            result = await client.submit_record("127.0.0.1", node_b["port"], wire)

            assert result.get("accepted") is True
            assert result["record_id"] == record.id

            # Verify Node B has the record
            assert node_b["dag"].stats()["total_records"] == 1
            retrieved = node_b["dag"].get(record.id)
            assert retrieved is not None

            await client.close()
        finally:
            await node_b["server"].stop()


# ---------------------------------------------------------------------------
# Phase 1: Security Tests
# ---------------------------------------------------------------------------

class TestWitnessVerification:
    """Witness signature verification tests."""

    @pytest.mark.asyncio
    async def test_witness_sig_verifiable(self, node_a, node_b):
        """Witness counter-signature can be verified with the witness's public key."""
        await node_a["server"].start()
        try:
            record = _create_signed_record(
                node_b["identity"], node_b["dag"], b"verify-test"
            )

            client = NetworkClient(timeout=5.0)

            # Get Node A's public key from status
            status = await client.get_status("127.0.0.1", node_a["port"])
            assert "public_key" in status
            pub_key = bytes.fromhex(status["public_key"])

            # Request witness with verification
            wire = record.to_bytes()
            signable = record.signable_bytes()
            result = await client.request_witness(
                "127.0.0.1", node_a["port"], wire,
                verify_key=pub_key, signable=signable,
            )

            assert "error" not in result
            assert result.get("verified") is True
            assert result["witness"] == node_a["identity"].identity_hash

            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_bad_sig_rejected(self, node_a, node_b):
        """Verification fails with wrong public key."""
        await node_a["server"].start()
        try:
            record = _create_signed_record(
                node_b["identity"], node_b["dag"], b"bad-sig-test"
            )

            client = NetworkClient(timeout=5.0)

            # Use Node B's key to "verify" Node A's signature — should fail
            wire = record.to_bytes()
            signable = record.signable_bytes()
            result = await client.request_witness(
                "127.0.0.1", node_a["port"], wire,
                verify_key=node_b["identity"].public_key,
                signable=signable,
            )

            assert "error" in result
            assert "verification failed" in result["error"]

            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_status_has_public_key(self, node_a):
        """GET /status includes public_key and node_type."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            status = await client.get_status("127.0.0.1", node_a["port"])
            await client.close()

            assert "public_key" in status
            assert len(status["public_key"]) > 0
            assert "node_type" in status
            assert status["node_type"] == "leaf"
        finally:
            await node_a["server"].stop()


class TestRateLimiting:
    """Rate limiting tests."""

    def test_normal_traffic_passes(self):
        """Requests under the limit pass through."""
        limiter = PeerRateLimiter(max_requests=10, window_seconds=60.0)
        for _ in range(10):
            assert limiter.allow("192.168.1.1") is True

    def test_burst_blocked(self):
        """Requests exceeding the limit are blocked."""
        limiter = PeerRateLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert limiter.allow("192.168.1.1") is True
        # 6th should be blocked
        assert limiter.allow("192.168.1.1") is False

    def test_different_peers_independent(self):
        """Rate limits are per-peer, not global."""
        limiter = PeerRateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.allow("10.0.0.1") is True
        assert limiter.allow("10.0.0.1") is True
        assert limiter.allow("10.0.0.1") is False
        # Different peer should be fine
        assert limiter.allow("10.0.0.2") is True

    def test_reset_clears_state(self):
        """Reset allows traffic again."""
        limiter = PeerRateLimiter(max_requests=1, window_seconds=60.0)
        assert limiter.allow("10.0.0.1") is True
        assert limiter.allow("10.0.0.1") is False
        limiter.reset("10.0.0.1")
        assert limiter.allow("10.0.0.1") is True

    @pytest.mark.asyncio
    async def test_server_returns_429(self, node_a):
        """Server returns 429 when rate limit exceeded on /records."""
        # Set very low rate limit
        await node_a["server"].start()
        node_a["server"]._rate_limiter = PeerRateLimiter(
            max_requests=1, window_seconds=60.0
        )
        try:
            record = _create_signed_record(
                node_a["identity"], node_a["dag"], b"rate-test"
            )
            wire = record.to_bytes()

            client = NetworkClient(timeout=5.0)

            # First request: should pass
            result1 = await client.submit_record("127.0.0.1", node_a["port"], wire)
            # Second request: should be rate-limited
            result2 = await client.submit_record("127.0.0.1", node_a["port"], wire)

            assert result2.get("error") == "rate limited"

            await client.close()
        finally:
            await node_a["server"].stop()


# ---------------------------------------------------------------------------
# Phase 2: Attestation & Heartbeat Tests
# ---------------------------------------------------------------------------

class TestAttestationBackProp:
    """Attestation query endpoint tests."""

    @pytest.mark.asyncio
    async def test_query_attestations(self, node_a, node_b):
        """After witnessing, attestations can be queried back."""
        await node_a["server"].start()
        try:
            record = _create_signed_record(
                node_b["identity"], node_b["dag"], b"backprop-test"
            )

            client = NetworkClient(timeout=5.0)

            # Witness the record
            wire = record.to_bytes()
            await client.request_witness("127.0.0.1", node_a["port"], wire)

            # Query attestations
            attestations = await client.query_attestations(
                "127.0.0.1", node_a["port"], record.id
            )

            assert len(attestations) == 1
            assert attestations[0]["record_id"] == record.id
            assert attestations[0]["witness_identity_hash"] == node_a["identity"].identity_hash

            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_empty_attestations(self, node_a):
        """Query attestations for unwitnessed record returns empty."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            attestations = await client.query_attestations(
                "127.0.0.1", node_a["port"], "nonexistent-record-id"
            )

            assert attestations == []

            await client.close()
        finally:
            await node_a["server"].stop()


class TestHeartbeat:
    """Heartbeat / ping tests."""

    @pytest.mark.asyncio
    async def test_ping_endpoint(self, node_a):
        """GET /ping returns pong with identity and timestamp."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            rtt = await client.ping("127.0.0.1", node_a["port"])

            assert rtt is not None
            assert rtt > 0
            assert rtt < 5.0  # Should be very fast on localhost

            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_ping_unreachable(self):
        """Ping to unreachable host returns None."""
        client = NetworkClient(timeout=1.0)
        rtt = await client.ping("127.0.0.1", 19999)  # Nothing running here
        assert rtt is None
        await client.close()

    @pytest.mark.asyncio
    async def test_stale_after_heartbeat_failures(self, node_a):
        """Peer goes STALE after 2 heartbeat failures."""
        from network.discovery import PeerDiscovery

        discovery = PeerDiscovery(
            identity_hash="test-discovery",
            port=19999,
        )
        discovery._running = True

        # Add a peer pointing to a port with nothing running
        peer = discovery.add_peer("127.0.0.1", 19998, "fake-peer-001")
        assert peer.state == PeerState.DISCOVERED
        assert peer.heartbeat_failures == 0

        client = NetworkClient(timeout=1.0)

        # First heartbeat — 1 failure
        await discovery.heartbeat_once(client)
        assert peer.heartbeat_failures == 1
        assert peer.state != PeerState.STALE

        # Second heartbeat — 2 failures → STALE
        await discovery.heartbeat_once(client)
        assert peer.heartbeat_failures >= 2
        assert peer.state == PeerState.STALE

        await client.close()


# ---------------------------------------------------------------------------
# Phase 3: Trust & Role Tests
# ---------------------------------------------------------------------------

class TestTrustWeighted:
    """Weighted trust scoring tests."""

    def test_empty_attestations(self):
        """No attestations → 0.0."""
        assert TrustScore.compute_weighted([]) == 0.0

    def test_fresh_attestation(self):
        """Single fresh attestation ≈ simple compute(1)."""
        now = time.time()
        att = [{"timestamp": now, "witness_identity_hash": "aaaa1111"}]
        score = TrustScore.compute_weighted(att, now=now)
        # Fresh attestation has weight ~1.0, so score ≈ 0.5
        assert abs(score - 0.5) < 0.05

    def test_temporal_decay(self):
        """Old attestations contribute less than fresh ones."""
        now = time.time()
        fresh = [{"timestamp": now, "witness_identity_hash": "aaaa1111"}]
        old = [{"timestamp": now - 30 * 86400, "witness_identity_hash": "aaaa1111"}]  # 30 days

        score_fresh = TrustScore.compute_weighted(fresh, now=now)
        score_old = TrustScore.compute_weighted(old, now=now)
        assert score_fresh > score_old

    def test_diversity_bonus(self):
        """Multiple unique witnesses score higher than same witness repeated."""
        now = time.time()
        diverse = [
            {"timestamp": now, "witness_identity_hash": "aaaa1111bbbb"},
            {"timestamp": now, "witness_identity_hash": "cccc2222dddd"},
        ]
        same = [
            {"timestamp": now, "witness_identity_hash": "aaaa1111bbbb"},
            {"timestamp": now, "witness_identity_hash": "aaaa1111cccc"},  # Same 8-char prefix
        ]
        score_diverse = TrustScore.compute_weighted(diverse, now=now)
        score_same = TrustScore.compute_weighted(same, now=now)
        assert score_diverse > score_same

    def test_backward_compat(self):
        """compute() still works unchanged."""
        assert TrustScore.compute(0) == 0.0
        assert abs(TrustScore.compute(1) - 0.5) < 0.01
        assert abs(TrustScore.compute(3) - 0.75) < 0.01
        assert abs(TrustScore.compute(10) - 0.909) < 0.01

    def test_score_capped_below_one(self):
        """Weighted score never reaches 1.0."""
        now = time.time()
        many = [
            {"timestamp": now, "witness_identity_hash": f"peer{i:04d}xx"}
            for i in range(100)
        ]
        score = TrustScore.compute_weighted(many, now=now)
        assert score < 1.0


# ---------------------------------------------------------------------------
# Phase 4: Error & Stress Tests
# ---------------------------------------------------------------------------

class TestErrorCases:
    """Error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_body_records(self, node_a):
        """POST /records with empty body returns 400."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            session = await client._get_session()
            async with session.post(f"http://127.0.0.1:{node_a['port']}/records", data=b"") as resp:
                assert resp.status == 400
                data = await resp.json()
                assert "error" in data
            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_garbage_bytes_records(self, node_a):
        """POST /records with garbage bytes returns 500."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            result = await client.submit_record(
                "127.0.0.1", node_a["port"], b"\x00\x01\x02garbage"
            )
            # Should get an error (either parse or validation failure)
            assert "error" in result
            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_empty_body_witness(self, node_a):
        """POST /witness with empty body returns 400."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            session = await client._get_session()
            async with session.post(f"http://127.0.0.1:{node_a['port']}/witness", data=b"") as resp:
                assert resp.status == 400
                data = await resp.json()
                assert "error" in data
            await client.close()
        finally:
            await node_a["server"].stop()

    @pytest.mark.asyncio
    async def test_attestations_missing_record_id(self, node_a):
        """GET /attestations without record_id returns 400."""
        await node_a["server"].start()
        try:
            client = NetworkClient(timeout=5.0)
            session = await client._get_session()
            async with session.get(f"http://127.0.0.1:{node_a['port']}/attestations") as resp:
                assert resp.status == 400
                data = await resp.json()
                assert "error" in data
            await client.close()
        finally:
            await node_a["server"].stop()


class TestStress:
    """Stress / volume tests."""

    @pytest.mark.asyncio
    async def test_50_record_exchange(self, node_a, node_b):
        """50 records pushed from A to B."""
        await node_b["server"].start()
        try:
            client = NetworkClient(timeout=10.0)

            pushed = 0
            for i in range(50):
                record = _create_signed_record(
                    node_a["identity"], node_a["dag"],
                    f"stress-{i}".encode(),
                )
                wire = record.to_bytes()
                result = await client.submit_record("127.0.0.1", node_b["port"], wire)
                if result.get("accepted"):
                    pushed += 1

            assert pushed == 50
            assert node_b["dag"].stats()["total_records"] == 50

            await client.close()
        finally:
            await node_b["server"].stop()

    @pytest.mark.asyncio
    async def test_bidirectional_sync(self, node_a, node_b):
        """Both nodes create records and sync with each other."""
        await node_a["server"].start()
        await node_b["server"].start()
        try:
            # Each node creates 5 records
            for i in range(5):
                _create_signed_record(
                    node_a["identity"], node_a["dag"],
                    f"a-record-{i}".encode(),
                )
                _create_signed_record(
                    node_b["identity"], node_b["dag"],
                    f"b-record-{i}".encode(),
                )

            assert node_a["dag"].stats()["total_records"] == 5
            assert node_b["dag"].stats()["total_records"] == 5

            client = NetworkClient(timeout=5.0)

            # Sync A → B (push A's records to B via submit endpoint)
            records_from_a = await client.query_records("127.0.0.1", node_a["port"])
            synced_to_b = 0
            for rec_data in records_from_a:
                wire = bytes.fromhex(rec_data["wire_hex"])
                result = await client.submit_record("127.0.0.1", node_b["port"], wire)
                if result.get("accepted"):
                    synced_to_b += 1

            # Sync B → A (push B's records to A via submit endpoint)
            records_from_b = await client.query_records("127.0.0.1", node_b["port"])
            synced_to_a = 0
            for rec_data in records_from_b:
                wire = bytes.fromhex(rec_data["wire_hex"])
                result = await client.submit_record("127.0.0.1", node_a["port"], wire)
                if result.get("accepted"):
                    synced_to_a += 1

            # Both should have received some records from each other
            assert synced_to_b > 0
            assert synced_to_a > 0

            await client.close()
        finally:
            await node_a["server"].stop()
            await node_b["server"].stop()


class TestConcurrent:
    """Concurrent multi-node tests."""

    @pytest.mark.asyncio
    async def test_three_nodes_witness_same_record(self, node_a, node_b, node_c):
        """Three nodes can all witness the same record."""
        await node_a["server"].start()
        await node_b["server"].start()
        await node_c["server"].start()
        try:
            # Node A creates a record
            record = _create_signed_record(
                node_a["identity"], node_a["dag"], b"concurrent-test"
            )
            wire = record.to_bytes()

            client = NetworkClient(timeout=5.0)

            # All 3 nodes witness the record
            witnesses = []
            for port in [node_a["port"], node_b["port"], node_c["port"]]:
                result = await client.request_witness("127.0.0.1", port, wire)
                if "error" not in result:
                    witnesses.append(result["witness"])

            assert len(witnesses) == 3

            # All should be unique identities
            assert len(set(witnesses)) == 3

            # Trust score with 3 witnesses
            score = TrustScore.compute(3)
            assert abs(score - 0.75) < 0.01
            assert TrustScore.level(score) == "strong"

            await client.close()
        finally:
            await node_a["server"].stop()
            await node_b["server"].stop()
            await node_c["server"].stop()

    @pytest.mark.asyncio
    async def test_duplicate_witness_dedup(self, node_a, node_b):
        """Same node witnessing twice doesn't create duplicate attestation."""
        await node_a["server"].start()
        try:
            record = _create_signed_record(
                node_b["identity"], node_b["dag"], b"dedup-test"
            )
            wire = record.to_bytes()

            client = NetworkClient(timeout=5.0)

            # Witness twice
            await client.request_witness("127.0.0.1", node_a["port"], wire)
            await client.request_witness("127.0.0.1", node_a["port"], wire)

            # Should still only have 1 attestation (dedup by witness identity)
            wm = node_a["server"]._witness_manager
            assert wm.witness_count(record.id) == 1

            await client.close()
        finally:
            await node_a["server"].stop()
