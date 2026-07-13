"""Formula version constants for all score/model computations (issue #1361).

Each constant is a short opaque string written into persisted score rows so
that before/after comparisons after a formula change remain unambiguous.
Bump only when the output for the same inputs changes meaningfully — not for
cosmetic or logging changes.
"""

SCORE_VERSION = "v1"
READINESS_VERSION = "v1"
TSS_VERSION = "v1"
PROJECTION_VERSION = "v1"
