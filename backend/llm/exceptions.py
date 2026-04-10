"""
LLM Client exception definitions.
"""


class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when LLM configuration is invalid or missing."""
    pass


class LLMAPIError(LLMError):
    """Raised when the LLM API returns an error."""

    def __init__(self, message: str, status_code: int = None, response_body: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class LLMTimeoutError(LLMError):
    """Raised when the LLM API request times out."""
    pass


class LLMMaxRetriesExceededError(LLMError):
    """Raised when max retries are exceeded."""
    pass
