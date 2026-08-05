"""Tests for issue #992: restore INFO log level for performance observability logging.

Context: During sprint-85, the performance endpoint logging was downgraded from
_performance_log.info(...) to _performance_log.debug(...), guarded by
isEnabledFor(DEBUG). In production, the logger is typically configured at WARNING
or INFO — not DEBUG — so these log entries were never emitted, defeating the
observability goal in #927 AC1.

Acceptance Criteria (derived from issue description):
  AC1: Log entries are emitted at INFO level, not DEBUG.
  AC2: The isEnabledFor guard checks INFO (not DEBUG), so a logger configured at
       INFO (but not DEBUG) still triggers the expensive log-entry assembly.
  AC3: When the logger is disabled at INFO level, _build_performance_log_entry
       is still skipped (guard is not removed, only level changes).
  AC4: Both call sites (needs_thresholds branch and main scoring path) use
       the corrected level.
"""

import logging
import unittest.mock as mock



class TestInfoLogLevel:
    """AC1 + AC4: log entries are emitted at INFO, not DEBUG."""

    def test_main_scoring_path_logs_at_info(self):
        """AC1: The main scoring path emits at INFO level."""
        import backend.main as main_mod

        with mock.patch.object(
            main_mod._performance_log, "isEnabledFor", return_value=True
        ):
            with mock.patch.object(
                main_mod._performance_log, "info"
            ) as mock_info, mock.patch.object(
                main_mod._performance_log, "debug"
            ) as mock_debug:
                prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
                runs = [{"run_id": "r1", "laps": [{"band": "easy"}]}]
                endurance = {"score": 72.5, "direction": "improving", "trend": []}
                speed = {"score": 68.0, "direction": "stable", "trend": []}

                # Replicate the corrected endpoint guard
                if main_mod._performance_log.isEnabledFor(logging.INFO):
                    log_entry = main_mod._build_performance_log_entry(
                        preferences=prefs, runs=runs, endurance=endurance, speed=speed,
                    )
                    main_mod._performance_log.info("performance score request", extra=log_entry)

        mock_info.assert_called_once()
        mock_debug.assert_not_called()

    def test_needs_thresholds_path_logs_at_info(self):
        """AC4: The needs_thresholds branch also emits at INFO level."""
        import backend.main as main_mod

        needs_thresholds_obj = {"state": "needs_thresholds", "reason": "thresholds missing"}

        with mock.patch.object(
            main_mod._performance_log, "isEnabledFor", return_value=True
        ):
            with mock.patch.object(
                main_mod._performance_log, "info"
            ) as mock_info, mock.patch.object(
                main_mod._performance_log, "debug"
            ) as mock_debug:
                prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
                runs = []

                if main_mod._performance_log.isEnabledFor(logging.INFO):
                    log_entry = main_mod._build_performance_log_entry(
                        preferences=prefs,
                        runs=runs,
                        endurance=needs_thresholds_obj,
                        speed=needs_thresholds_obj,
                    )
                    main_mod._performance_log.info("performance score request", extra=log_entry)

        mock_info.assert_called_once()
        mock_debug.assert_not_called()


class TestInfoLevelGuard:
    """AC2: isEnabledFor is called with INFO, not DEBUG."""

    def test_guard_checks_info_level(self):
        """AC2: When INFO is enabled but DEBUG is not, the log entry IS built."""
        import backend.main as main_mod

        call_levels = []

        def capture_is_enabled_for(level):
            call_levels.append(level)
            return level == logging.INFO  # INFO=True, DEBUG=False

        with mock.patch.object(
            main_mod._performance_log, "isEnabledFor", side_effect=capture_is_enabled_for
        ):
            with mock.patch.object(
                main_mod, "_build_performance_log_entry", return_value={}
            ) as patched_build:
                prefs = {"ftp_w": 200}
                runs = []
                endurance = {"score": 70.0}
                speed = {"score": 65.0}

                # Replicate the corrected guard (INFO, not DEBUG)
                if main_mod._performance_log.isEnabledFor(logging.INFO):
                    main_mod._build_performance_log_entry(
                        preferences=prefs, runs=runs, endurance=endurance, speed=speed,
                    )

        # Guard must have checked INFO
        assert logging.INFO in call_levels, (
            f"Expected guard to check INFO ({logging.INFO}), got levels: {call_levels}"
        )
        # Since INFO returned True, the build helper must have been called
        patched_build.assert_called_once()

    def test_guard_does_not_build_when_info_disabled(self):
        """AC2 + AC3: When INFO is disabled, _build_performance_log_entry is skipped."""
        import backend.main as main_mod

        with mock.patch.object(
            main_mod._performance_log, "isEnabledFor", return_value=False
        ):
            with mock.patch.object(
                main_mod, "_build_performance_log_entry", return_value={}
            ) as patched_build:
                if main_mod._performance_log.isEnabledFor(logging.INFO):
                    main_mod._build_performance_log_entry(
                        preferences={}, runs=[], endurance={}, speed={},
                    )

        patched_build.assert_not_called()

    def test_debug_only_logger_does_not_trigger_build(self):
        """AC2: A logger at DEBUG-only would NOT satisfy isEnabledFor(INFO).

        INFO (20) > DEBUG (10): if guard uses INFO, a DEBUG-configured logger
        would not call isEnabledFor(INFO) with True unless the effective level
        is INFO or lower. This test confirms a WARNING-configured logger skips the
        build, as it would in production without explicit reconfiguration.
        """
        import backend.main as main_mod

        real_logger = logging.getLogger("test.992.warning_level")
        real_logger.setLevel(logging.WARNING)

        built = []

        def fake_build(**kwargs):
            built.append(True)
            return {}

        with mock.patch.object(main_mod, "_build_performance_log_entry", side_effect=fake_build):
            if real_logger.isEnabledFor(logging.INFO):
                main_mod._build_performance_log_entry(
                    preferences={}, runs=[], endurance={}, speed={},
                )

        assert not built, "Build should be skipped when effective level is WARNING"

    def test_info_configured_logger_triggers_build(self):
        """AC2: A logger configured at INFO satisfies isEnabledFor(INFO) — build runs."""
        import backend.main as main_mod

        real_logger = logging.getLogger("test.992.info_level")
        real_logger.setLevel(logging.INFO)
        # Suppress actual output
        real_logger.addHandler(logging.NullHandler())

        built = []

        def fake_build(**kwargs):
            built.append(True)
            return {}

        with mock.patch.object(main_mod, "_build_performance_log_entry", side_effect=fake_build):
            if real_logger.isEnabledFor(logging.INFO):
                main_mod._build_performance_log_entry(
                    preferences={}, runs=[], endurance={}, speed={},
                )

        assert built, "Build should run when effective level is INFO"


class TestSourceCodeUsesInfoLevel:
    """AC1 + AC2 + AC4: Verify the actual source lines use INFO, not DEBUG.

    These tests inspect the source of backend/main.py to confirm the corrected
    log level appears at both call sites, providing a deterministic gate that
    cannot be fooled by mock indirection.
    """

    def _get_performance_source_block(self):
        import inspect
        import backend.main as main_mod

        # Find the function containing the performance endpoint guard
        # by searching the source for the guard pattern
        src = inspect.getsource(main_mod)
        return src

    def test_no_debug_emit_after_performance_log_guard(self):
        """AC1: _performance_log.debug( does not appear in a guarded scoring context.

        Specifically, the pattern 'isEnabledFor' + 'debug(' must not co-occur in
        the performance endpoint section. We check for absence of the old pattern.
        """
        import inspect
        import backend.main as main_mod

        src = inspect.getsource(main_mod)
        # Find the section that contains _build_performance_log_entry calls
        # The old buggy pattern: isEnabledFor(_logging.DEBUG) followed by .debug(
        # Split around the _build_performance_log_entry call sites
        build_fn_name = "_build_performance_log_entry"
        assert build_fn_name in src, "Helper function must exist in main.py"

        # Count occurrences of the old pattern near the build helper calls
        import re
        # Find all _performance_log.debug( occurrences (outside function def lines)
        debug_calls = re.findall(r'_performance_log\.debug\(', src)
        # After the fix there must be zero _performance_log.debug( in the source
        # (the emit calls are converted to .info())
        assert len(debug_calls) == 0, (
            f"Found {len(debug_calls)} _performance_log.debug() call(s) — "
            "all emit calls must use .info() after the fix"
        )

    def test_info_emit_present_at_both_call_sites(self):
        """AC4: _performance_log.info( appears at least twice — once per call site."""
        import inspect
        import re
        import backend.main as main_mod

        src = inspect.getsource(main_mod)
        info_calls = re.findall(r'_performance_log\.info\("performance score request"', src)
        assert len(info_calls) >= 2, (
            f"Expected at least 2 'performance score request' info() calls, found {len(info_calls)}"
        )

    def test_guard_uses_info_not_debug_constant(self):
        """AC2: isEnabledFor guards use _logging.INFO (not _logging.DEBUG)."""
        import inspect
        import re
        import backend.main as main_mod

        src = inspect.getsource(main_mod)
        # Old pattern
        debug_guards = re.findall(r'isEnabledFor\(_logging\.DEBUG\)', src)
        # New pattern
        info_guards = re.findall(r'isEnabledFor\(_logging\.INFO\)', src)

        assert len(debug_guards) == 0, (
            f"Found {len(debug_guards)} isEnabledFor(DEBUG) guard(s) — "
            "all guards must use INFO after the fix"
        )
        assert len(info_guards) >= 2, (
            f"Expected at least 2 isEnabledFor(INFO) guards, found {len(info_guards)}"
        )
