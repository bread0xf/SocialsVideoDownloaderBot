from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    PRIVATE_OR_RESTRICTED_CONTENT = "PRIVATE_OR_RESTRICTED_CONTENT"
    URL_BLOCKED = "URL_BLOCKED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    DURATION_LIMIT = "DURATION_LIMIT"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TELEGRAM_DELIVERY_FAILED = "TELEGRAM_DELIVERY_FAILED"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    def __init__(self, code: ErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class UrlValidationError(AppError):
    pass
