"""Chat-specific errors; HTTP translation remains in the API layer."""
from app.ingestion.domain.exceptions import AppError, InfrastructureError, ProcessingError, ValidationError


class ChatError(AppError):
    """Base error for chat application failures."""


class LlmError(InfrastructureError):
    """The configured LLM provider failed."""


class ConversationError(InfrastructureError):
    """Conversation persistence failed."""


class SopError(ProcessingError):
    """SOP definition or execution state is invalid."""


class SqlGenerationError(ProcessingError):
    """The model did not produce a usable SQL candidate."""


class SqlPolicyError(ValidationError):
    """Generated SQL violates the read-only policy."""


class SessionConflictError(ValidationError):
    """Concurrent update lost the optimistic lock on session state."""
