"""聊天领域专属异常；HTTP 翻译仍留在 API 层。"""
from app.ingestion.domain.exceptions import AppError, InfrastructureError, ProcessingError, ValidationError


class ChatError(AppError):
    """聊天应用失败的基类异常。"""


class LlmError(InfrastructureError):
    """已配置的 LLM 提供商调用失败。"""


class ConversationError(InfrastructureError):
    """会话持久化失败。"""


class SopError(ProcessingError):
    """SOP 定义或执行状态无效。"""


class SqlGenerationError(ProcessingError):
    """模型未能生成可用的 SQL 候选。"""


class SqlPolicyError(ValidationError):
    """生成的 SQL 违反只读策略。"""


class SessionConflictError(ValidationError):
    """并发更新丢失了会话状态的乐观锁。"""
