import pytest

from backend.utils.errors import (
    AppError,
    BadRequest,
    Conflict,
    ExternalServiceError,
    Forbidden,
    NotFound,
    RateLimited,
    Unauthorized,
    UnprocessableEntity,
)


def test_app_error_defaults():
    e = AppError(user_message="oops")
    assert e.status_code == 500
    assert e.error_code == "internal_error"
    assert e.user_message == "oops"
    assert e.details == {}


def test_to_dict():
    e = NotFound(user_message="Workout not found", details={"workout_id": "42"})
    assert e.to_dict() == {
        "error_code": "not_found",
        "message": "Workout not found",
        "details": {"workout_id": "42"},
    }


def test_subclass_attributes():
    cases = [
        (BadRequest, 400, "bad_request"),
        (NotFound, 404, "not_found"),
        (Unauthorized, 401, "unauthorized"),
        (Forbidden, 403, "forbidden"),
        (Conflict, 409, "conflict"),
        (UnprocessableEntity, 422, "unprocessable"),
        (ExternalServiceError, 502, "external_service_failed"),
        (RateLimited, 429, "rate_limited"),
    ]
    for cls, expected_status, expected_code in cases:
        e = cls(user_message="test")
        assert e.status_code == expected_status, f"{cls.__name__} status_code"
        assert e.error_code == expected_code, f"{cls.__name__} error_code"


def test_user_message_required():
    with pytest.raises(TypeError):
        BadRequest()


def test_details_optional_defaults_to_empty():
    e = Conflict(user_message="duplicate")
    assert e.details == {}


def test_details_accepted():
    e = ExternalServiceError(user_message="Strava unreachable", details={"service": "strava"})
    assert e.details == {"service": "strava"}
    assert e.status_code == 502
