# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Trust scoring — witness-count and weighted formulas.

Simple formula (MVP):     T = 1 - 1/(1 + n)
Weighted formula (v2):    Temporal decay + diversity bonus

  0 witnesses → 0.0
  1 witness   → 0.5
  3 witnesses → 0.75
  10 witnesses → 0.91
"""

import math
import time
from typing import List, Optional


class TrustScore:
    """Trust scoring based on witness count and attestation quality."""

    @staticmethod
    def compute(witness_count: int) -> float:
        """
        Compute trust score from witness count.

        T = 1 - 1/(1 + n)

        Returns float in [0.0, 1.0).
        """
        if witness_count < 0:
            return 0.0
        return 1.0 - 1.0 / (1.0 + witness_count)

    @staticmethod
    def compute_weighted(
        attestations: List[dict],
        now: Optional[float] = None,
    ) -> float:
        """
        Weighted trust score with temporal decay and diversity bonus.

        Each attestation dict should have:
          - timestamp: float (epoch seconds)
          - witness_identity_hash: str

        Decay: exp(-0.03 * age_days) — ~23-day half-life
        Diversity: 20% bonus for unique identity prefixes (first 8 chars)

        Returns float in [0.0, 1.0).
        """
        if not attestations:
            return 0.0

        if now is None:
            now = time.time()

        # Sum decayed weights
        total_weight = 0.0
        prefixes = set()
        for att in attestations:
            ts = att.get("timestamp", now)
            age_days = max(0, (now - ts)) / 86400.0
            weight = math.exp(-0.03 * age_days)
            total_weight += weight

            identity = att.get("witness_identity_hash", "")
            if identity:
                prefixes.add(identity[:8])

        # Diversity bonus: 20% per unique prefix beyond 1
        diversity_bonus = 0.0
        if len(prefixes) > 1:
            diversity_bonus = 0.20 * (len(prefixes) - 1) / len(prefixes)

        # Base score from weighted count
        base = 1.0 - 1.0 / (1.0 + total_weight)
        score = min(base + diversity_bonus, 0.999)
        return score

    @staticmethod
    def level(score: float) -> str:
        """Human-readable trust level."""
        if score < 0.1:
            return "unwitnessed"
        if score < 0.5:
            return "minimal"
        if score < 0.75:
            return "moderate"
        if score < 0.9:
            return "strong"
        return "very strong"
