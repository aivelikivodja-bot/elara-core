# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Trust scoring — simple witness-count formula.

Full AWC (Accumulated Witness Credibility) formula deferred to Layer 2
production release. This MVP uses: T = 1 - 1/(1 + n)

  0 witnesses → 0.0
  1 witness   → 0.5
  3 witnesses → 0.75
  10 witnesses → 0.91
"""


class TrustScore:
    """Simple trust score based on witness count."""

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
