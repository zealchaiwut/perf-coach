"""
Custom exception hierarchy for perf-coach backend.

Usage example:
    raise NotFound(user_message="Workout not found", details={"workout_id": str(id)})
"""


class AppError(Exception):
    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, *, user_message: str, details: dict | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.details = details if details is not None else {}

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "message": self.user_message,
            "details": self.details,
        }


class BadRequest(AppError):
    status_code = 400
    error_code = "bad_request"


class NotFound(AppError):
    status_code = 404
    error_code = "not_found"


class Unauthorized(AppError):
    status_code = 401
    error_code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    error_code = "forbidden"


class Conflict(AppError):
    status_code = 409
    error_code = "conflict"


class UnprocessableEntity(AppError):
    status_code = 422
    error_code = "unprocessable"


class ExternalServiceError(AppError):
    status_code = 502
    error_code = "external_service_failed"


class RateLimited(AppError):
    status_code = 429
    error_code = "rate_limited"
