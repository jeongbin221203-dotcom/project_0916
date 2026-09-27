"""Server-side input validation."""


class ValidationError(ValueError):
    """Raised when user input is missing or invalid."""

    def __init__(self, message: str, field: str | None = None, code: str = ""):
        super().__init__(message)
        self.field = field
        # 화면이 다르게 다뤄야 하는 오류를 가려내는 데 씁니다.
        # (예: INCOTERMS_CONFIRM은 막는 것이 아니라 한 번 더 확인받는 것입니다)
        self.code = code
