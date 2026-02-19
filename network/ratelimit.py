# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Sliding-window rate limiter for network endpoints."""

import time
from collections import defaultdict
from typing import Dict, List


class PeerRateLimiter:
    """Per-peer sliding window rate limiter.

    Tracks request timestamps per peer IP. Denies requests
    exceeding max_requests within window_seconds.
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0):
        self._max_requests = max_requests
        self._window = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def allow(self, peer_ip: str) -> bool:
        """Check if a request from peer_ip is allowed.

        Returns True if under limit, False if rate-limited.
        """
        now = time.time()
        cutoff = now - self._window

        # Prune old entries
        timestamps = self._requests[peer_ip]
        self._requests[peer_ip] = [t for t in timestamps if t > cutoff]

        if len(self._requests[peer_ip]) >= self._max_requests:
            return False

        self._requests[peer_ip].append(now)
        return True

    def reset(self, peer_ip: str = "") -> None:
        """Reset rate limit state. If peer_ip given, reset only that peer."""
        if peer_ip:
            self._requests.pop(peer_ip, None)
        else:
            self._requests.clear()
