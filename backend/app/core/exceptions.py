from http import HTTPStatus


class AppException(Exception):
    """Base exception for all application errors."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class NotFoundError(AppException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "Resource not found."


class UnauthorizedError(AppException):
    status_code = HTTPStatus.UNAUTHORIZED
    detail = "Authentication required."


class ForbiddenError(AppException):
    status_code = HTTPStatus.FORBIDDEN
    detail = "You do not have permission to perform this action."


class ConflictError(AppException):
    status_code = HTTPStatus.CONFLICT
    detail = "Resource already exists."


class ValidationError(AppException):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    detail = "Validation failed."
