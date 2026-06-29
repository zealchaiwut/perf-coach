"""User-facing message constants for running performance scoring (issue #929).

Centralises all human-readable strings so they can be updated without touching
business logic in main.py or the score computation modules.
"""

NEEDS_THRESHOLDS_REASON = (
    "Set your FTP, threshold heart rate, or threshold pace to unlock performance scores."
)
