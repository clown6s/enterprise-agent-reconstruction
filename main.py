from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
import structlog
from fastapi import FastAPI, Request

from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.container import build_ingestion, build_reranker
from app.ingestion.bootstrap.handlers import register_exception_handlers
from app.ingestion.bootstrap.logging import setup_logging
from app.chat.api.router import create_router
from app.chat.bootstrap.container import build_chat
from app.chat.mcp.bridge import LazyService
from app.chat.mcp.server import build_http_app
from app.auth.api.dependencies import make_principal_provider
from app.auth.api.router import create_router as create_auth_router
from app.auth.bootstrap.container import build_auth
from app.chat.mcp.config import McpPolicy

setup_logging()
logger = structlog.get_logger(__name__)


def _chat_service():
    """Build a ChatService for this process. Kept separate so closing and
    re-opening (e.g. across reloads) can build a fresh instance."""
    ingestion = build_ingestion()
    retriever = RetrieveDocuments(
        ingestion.embedder, ingestion.vectors,
        lexical=ingestion.lexical, reranker=build_reranker(),
    )
    return build_chat(retriever=retriever)


# Process-level singleton: built lazily on first use, closed on shutdown so the
# LLM/retriever/DB connections are created once and released together.
singleton = LazyService(_chat_service)
auth_singleton = LazyService(build_auth)


@asynccontextmanager
async def lifespan(_app):
    try:
        yield
    finally:
        for holder in (singleton, auth_singleton):
            service = holder._service
            if service is not None:
                closer = getattr(service, "close", None)
                if callable(closer):
                    closer()


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)

principal_provider = make_principal_provider(auth_singleton)
chat_principal_provider = make_principal_provider(auth_singleton, "chat:ask")
app.include_router(create_auth_router(auth_singleton, principal_provider))
app.include_router(create_router(lambda: singleton._get(), chat_principal_provider))

app.mount(
    "/mcp",
    build_http_app(
        singleton, auth=auth_singleton,
        policy=McpPolicy(auth_enabled=True), path="/",
    ),
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """为每个请求绑定 trace_id，并记录完成状态。

    用 anyio 桥接让 contextvars 贯穿到线程池中的同步 handler，
    避免同步 route 里丢失 trace_id。
    """
    trace_id = request.headers.get("X-Trace-Id") or str(uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        method=request.method,
        path=request.url.path,
    )
    try:
        response = await anyio.to_thread.run_sync(
            lambda: anyio.from_thread.run(call_next, request)
        )
    except Exception:
        # 完整堆栈由全局 exception handler 统一记录，这里不再重复打印。
        raise
    response.headers["X-Trace-Id"] = trace_id
    logger.info("request_completed", status_code=response.status_code)
    return response


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
