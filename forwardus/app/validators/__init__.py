"""Server-side input validation."""


class ValidationError(ValueError):
    """Raised when user input is missing or invalid."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field
