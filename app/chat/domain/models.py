"""Chat domain models independent of frameworks and infrastructure."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConversationRelation(str, Enum):
    FOLLOW_UP = "follow_up"
    NEW_TOPIC = "new_topic"
    MIXED = "mixed"
    CLARIFICATION = "clarification"


class Intent(str, Enum):
    KNOWLEDGE_QA = "knowledge_qa"
    SOP = "sop"
    NL2SQL = "nl2sql"
    MIXED = "mixed"
    CLARIFICATION = "clarification"
    CHITCHAT = "chitchat"


class ChatStatus(str, Enum):
    ANSWERED = "answered"
    CLARIFICATION = "clarification"
    NO_CONTEXT = "no_context"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class Citation:
    source_type: str
    source_id: str
    document_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    title: str | None = None
    version: str | None = None
    step_id: str | None = None


@dataclass(frozen=True)
class RetrievalItem:
    """A single retrieved chunk (decoupled from ingestion's result type)."""
    text: str
    score: float
    document_id: str
    chunk_id: str | None = None
    page: int | None = None
    section_path: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    confidence: float
    reason: str = ""
    domain: str | None = None
    needs_clarification: bool = False


@dataclass(frozen=True)
class CitationAudit:
    sent: tuple[int, ...] = ()
    used: tuple[int, ...] = ()
    unused: tuple[int, ...] = ()
    grounded: bool = False
    # 带真实来源的审计详情；编号对应 sent/used/unused。
    sent_details: tuple[dict[str, Any], ...] = ()
    used_details: tuple[dict[str, Any], ...] = ()
    unused_details: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    trace_id: str
    stage: str
    status: str
    tenant_id: str = ""
    user_id: str = ""
    conversation_id: str | None = None
    mode: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResult:
    answer: str
    status: ChatStatus
    mode: Intent
    conversation_id: str
    citations: tuple[Citation, ...] = ()
    sql: dict[str, Any] | None = None
    sop: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    trace_id: str = ""
    citation_audit: CitationAudit | None = None


@dataclass(frozen=True)
class SopStep:
    step_id: str
    sequence: int
    instruction: str
    preconditions: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    requires_confirmation: bool = False
    role_required: str | None = None


@dataclass(frozen=True)
class SopDefinition:
    sop_id: str
    version: str
    title: str
    steps: tuple[SopStep, ...]
    scope: str = ""
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class SopExecutionState:
    sop_id: str
    version: str
    current_step_id: str
    params: dict[str, Any] = field(default_factory=dict)
    completed_steps: tuple[str, ...] = ()
    awaiting_confirmation: bool = False


@dataclass(frozen=True)
class SqlResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    query_id: str
    row_count: int


@dataclass(frozen=True)
class SessionState:
    """Structured state for multi-turn routing and follow-up resolution."""
    last_intent: Intent | None = None
    last_domain: str | None = None
    last_query_id: str | None = None
    current_sop_id: str | None = None
    current_sop_version: str | None = None
    current_step_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    version_no: int = 1


@dataclass(frozen=True)
class ResolvedQuestion:
    question: str
    intent_hint: Intent | None = None
    needs_clarification: bool = False
    reason: str = ""
    relation: ConversationRelation = ConversationRelation.NEW_TOPIC
    topic: str | None = None
    confidence: float = 1.0
    referenced_turns: tuple[int, ...] = ()
    subtasks: tuple[dict[str, Any], ...] = ()
