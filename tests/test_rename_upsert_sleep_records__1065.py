"""Tests for issue #1065: rename sleep_csv_parser.upsert_sleep_records → upsert_parsed_sleep_rows.

Derived acceptance criteria:
  AC1 – sleep_csv_parser no longer exports 'upsert_sleep_records' at the module level.
  AC2 – sleep_csv_parser exports 'upsert_parsed_sleep_rows' with a 2-param signature (rows, session).
  AC3 – drive_sleep_sync.upsert_sleep_records is unchanged with its 3-param signature (user_id, records, session).
  AC4 – No naming collision: the two modules export different function names so an incorrect import
         is a clear AttributeError, not a silent signature mismatch.
  AC5 – import_sleep_csv_for_user (internal caller in sleep_csv_parser) calls upsert_parsed_sleep_rows,
         not the old name.
"""
import inspect
import types


def test_sleep_csv_parser_does_not_export_upsert_sleep_records():
    """AC1: sleep_csv_parser must not export the old 'upsert_sleep_records' name."""
    import services.health_sync.sleep_csv_parser as mod
    assert not hasattr(mod, "upsert_sleep_records"), (
        "sleep_csv_parser still exports 'upsert_sleep_records' — rename it to "
        "'upsert_parsed_sleep_rows' to resolve the naming collision with drive_sleep_sync"
    )


def test_sleep_csv_parser_exports_upsert_parsed_sleep_rows():
    """AC2: sleep_csv_parser must export 'upsert_parsed_sleep_rows'."""
    import services.health_sync.sleep_csv_parser as mod
    assert hasattr(mod, "upsert_parsed_sleep_rows"), (
        "sleep_csv_parser does not export 'upsert_parsed_sleep_rows' — add the renamed function"
    )
    assert callable(mod.upsert_parsed_sleep_rows)


def test_upsert_parsed_sleep_rows_signature_has_two_params():
    """AC2: upsert_parsed_sleep_rows takes exactly (rows, session) — no user_id."""
    from services.health_sync.sleep_csv_parser import upsert_parsed_sleep_rows
    sig = inspect.signature(upsert_parsed_sleep_rows)
    params = list(sig.parameters.keys())
    assert len(params) == 2, f"Expected 2 params (rows, session), got {params}"
    assert params[0] == "rows", f"First param should be 'rows', got '{params[0]}'"
    assert params[1] == "session", f"Second param should be 'session', got '{params[1]}'"


def test_drive_sleep_sync_upsert_sleep_records_unchanged():
    """AC3: drive_sleep_sync.upsert_sleep_records keeps its 3-param signature (user_id, records, session)."""
    from backend.services.drive_sleep_sync import upsert_sleep_records
    sig = inspect.signature(upsert_sleep_records)
    params = list(sig.parameters.keys())
    assert len(params) == 3, f"Expected 3 params (user_id, records, session), got {params}"
    assert params[0] == "user_id"
    assert params[1] == "records"
    assert params[2] == "session"


def test_no_naming_collision_across_modules():
    """AC4: the two modules export different function names — no silent signature mismatch."""
    import backend.services.drive_sleep_sync as dss
    import services.health_sync.sleep_csv_parser as parser

    # drive_sleep_sync has upsert_sleep_records (3-param)
    assert hasattr(dss, "upsert_sleep_records")
    # sleep_csv_parser has upsert_parsed_sleep_rows (2-param), NOT upsert_sleep_records
    assert hasattr(parser, "upsert_parsed_sleep_rows")
    assert not hasattr(parser, "upsert_sleep_records")

    # The two are genuinely different objects
    assert dss.upsert_sleep_records is not parser.upsert_parsed_sleep_rows


def test_import_sleep_csv_for_user_calls_renamed_function():
    """AC5: import_sleep_csv_for_user source must reference upsert_parsed_sleep_rows, not the old name."""
    import inspect
    import services.health_sync.sleep_csv_parser as mod

    source = inspect.getsource(mod.import_sleep_csv_for_user)
    assert "upsert_parsed_sleep_rows" in source, (
        "import_sleep_csv_for_user still calls 'upsert_sleep_records' instead of "
        "'upsert_parsed_sleep_rows'"
    )
    assert "upsert_sleep_records" not in source, (
        "import_sleep_csv_for_user still references the old name 'upsert_sleep_records'"
    )
