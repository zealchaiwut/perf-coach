"""Tests for issue #1718: remove unused user_id field from _SleepImportBody.

The _SleepImportBody model accepted a client-supplied user_id field that was
never used for authorization — the handler always used current_user.id.  The
stray field was echoed into raw_data / parsed_data.  These tests verify the
field is gone and that the stored model dump does not contain it.
"""


def test_sleep_import_body_has_no_user_id_field():
    """AC: _SleepImportBody does not declare user_id as a model field."""
    from backend.main import _SleepImportBody

    assert "user_id" not in _SleepImportBody.model_fields


def test_sleep_import_body_model_dump_excludes_user_id():
    """model_dump() must not contain user_id so it won't pollute raw_data/parsed_data."""
    from backend.main import _SleepImportBody

    body = _SleepImportBody(
        import_date="2026-05-01",
        source="manual_json",
        data={"sleep_score": 80},
    )
    assert "user_id" not in body.model_dump()


def test_sleep_import_body_old_client_payload_accepted():
    """Extra user_id from old/unupdated clients is silently ignored (Pydantic extra=ignore)."""
    from backend.main import _SleepImportBody

    body = _SleepImportBody.model_validate(
        {
            "user_id": "old-client-supplied-id",
            "import_date": "2026-05-01",
            "source": "manual_json",
            "data": {"sleep_score": 80},
        }
    )
    assert body.import_date == "2026-05-01"
    assert "user_id" not in body.model_dump()


def test_sleep_import_body_required_fields_are_import_date_source_data():
    """The three required fields remain: import_date, source, data."""
    from backend.main import _SleepImportBody

    fields = set(_SleepImportBody.model_fields.keys())
    assert fields == {"import_date", "source", "data"}
