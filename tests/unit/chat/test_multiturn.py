"""Multi-turn resolution and session state tests (offline, no DB)."""
from app.chat.adapters.memory_session_state_store import MemorySessionStateStore
from app.chat.application.context import RequestContext
from app.chat.application.question_resolver import QuestionResolver
from app.chat.domain.models import ChatMessage, Intent, SessionState


_CTX = RequestContext(tenant_id="t", user_id="u", authenticated=True)


def test_resolver_continues_sop_followup():
    state = SessionState(last_intent=Intent.SOP, current_sop_id="expense_claim",
                         current_sop_version="v3", current_step_id="s1")
    resolved = QuestionResolver().resolve("那下一步呢", None, state)
    assert resolved.intent_hint == Intent.SOP
    assert resolved.question == "那下一步呢"


def test_resolver_continues_nl2sql_followup():
    state = SessionState(last_intent=Intent.NL2SQL, last_domain="orders")
    resolved = QuestionResolver().resolve("和上月比呢", None, state)
    assert resolved.intent_hint == Intent.NL2SQL


def test_resolver_merges_anaphora_with_prev_question():
    history = [ChatMessage("user", "MCP 是什么")]
    state = SessionState(last_intent=Intent.KNOWLEDGE_QA)
    resolved = QuestionResolver().resolve("它和 function calling 有什么区别",
                                          history, state)
    assert "MCP" in resolved.question
    assert resolved.intent_hint == Intent.KNOWLEDGE_QA


def test_resolver_no_context_returns_question():
    resolved = QuestionResolver().resolve("报销标准是什么", [], None)
    assert resolved.question == "报销标准是什么"
    assert resolved.intent_hint is None


def test_session_state_store_roundtrip_and_isolation():
    store = MemorySessionStateStore()
    state = SessionState(last_intent=Intent.NL2SQL, last_domain="orders")
    store.save("conv-1", state, context=_CTX)
    loaded = store.get("conv-1", context=_CTX)
    assert loaded is not None and loaded.last_domain == "orders"
    # 不同的用户看不到它
    other = RequestContext(tenant_id="t", user_id="other", authenticated=True)
    assert store.get("conv-1", context=other) is None