"""Use-case orchestration between routes, processors, collectors, and repositories."""


class ServiceError(Exception):
    """A user-facing failure that is not a field validation error (e.g. API failure)."""

    def __init__(self, message: str, error_code: str = "SERVICE_ERROR", status: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.status = status
