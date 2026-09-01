from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
import os
import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.observability import metrics
from app.observability.tracing import setup_tracing, shutdown_tracing, span

from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.container import build_ingestion, build_reranker
from app.ingestion.bootstrap.handlers import register_exception_handlers
from app.ingestion.bootstrap.logging import close_log_sink, setup_logging
from app.observability.es_log_sink import ElasticsearchLogSink
from app.chat.api.router import create_router
from app.chat.bootstrap.container import build_chat
from app.chat.bootstrap.config import read_settings
from app.chat.adapters.redis_rate_limiter import RedisRateLimiter
from app.chat.adapters.memory_usage_meter import MemoryUsageMeter
from app.chat.adapters.health_checkers import CompositeHealthChecker, configured, tcp_endpoint
from app.chat.mcp.bridge import LazyService
from app.chat.mcp.server import build_http_app
from app.auth.api.dependencies import make_principal_provider
from app.auth.api.router import create_router as create_auth_router
from app.auth.bootstrap.container import build_auth
from app.chat.mcp.config import McpPolicy

# 先加载部署配置，日志 sink 只在显式配置日志 ES 时创建。
load_dotenv(".env")
_log_sink = None
if os.getenv("ES_LOG_URL"):
    _log_sink = ElasticsearchLogSink(
        host=os.environ["ES_LOG_URL"],
        index_prefix=os.getenv("ES_LOG_INDEX_PREFIX", "enterprise-agent-logs"),
        username=os.getenv("ES_LOG_USERNAME", ""),
        password=os.getenv("ES_LOG_PASSWORD", ""),
        cert_fingerprint=os.getenv("ES_LOG_CERT_FINGERPRINT", ""),
    )
setup_logging(_log_sink)
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
    setup_tracing()
    try:
        yield
    finally:
        for holder in (singleton, auth_singleton):
            service = holder._service
            if service is not None:
                closer = getattr(service, "close", None)
                if callable(closer):
                    closer()
        rate_limiter.close()
        shutdown_tracing()
        close_log_sink()


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)

principal_provider = make_principal_provider(auth_singleton)
chat_principal_provider = make_principal_provider(auth_singleton, "chat:ask")
chat_settings = read_settings()
usage_meter = MemoryUsageMeter()
rate_limiter = RedisRateLimiter(
    host=__import__("os").getenv("REDIS_HOST", "127.0.0.1"),
    port=int(__import__("os").getenv("REDIS_PORT", "6379")),
    password=__import__("os").getenv("REDIS_PASSWORD", ""),
    limit=chat_settings.rate_limit,
    window_seconds=chat_settings.rate_window_seconds,
)
app.include_router(create_auth_router(auth_singleton, principal_provider))
app.include_router(create_router(lambda: singleton._get(), chat_principal_provider,
                                rate_limiter=rate_limiter, usage_meter=usage_meter))

app.mount(
    "/mcp",
    build_http_app(
        singleton, auth=auth_singleton,
        policy=McpPolicy(auth_enabled=True), path="/",
        rate_limiter=rate_limiter,
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
        with span("http.request", http_method=request.method,
                   http_route=request.url.path):
            response = await anyio.to_thread.run_sync(
                lambda: anyio.from_thread.run(call_next, request)
            )
    except Exception:
        # 完整堆栈由全局 exception handler 统一记录，这里不再重复打印。
        raise
    response.headers["X-Trace-Id"] = trace_id
    metrics.chat_requests_total.labels("http", str(response.status_code)).inc()
    logger.info("request_completed", status_code=response.status_code)
    return response


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus 抓取端点，不返回业务数据。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz():
    """Liveness probe: process is alive; no external dependency calls."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness probe with safe configuration/dependency summaries."""
    import os
    mysql_host = os.getenv("MYSQL_HOST", "")
    milvus_host = os.getenv("MILVUS_HOST", "")
    es_host = os.getenv("ES_HOST", "")
    redis_host = os.getenv("REDIS_HOST", "")
    es_port = 443 if es_host.startswith("https://") and ":" not in es_host.removeprefix("https://") else 9200
    checks = CompositeHealthChecker({
        "mysql": tcp_endpoint(mysql_host, int(os.getenv("MYSQL_PORT", "3306"))),
        "milvus": tcp_endpoint(milvus_host, int(os.getenv("MILVUS_PORT", "19530"))),
        "elasticsearch": tcp_endpoint(es_host, es_port),
        "redis": tcp_endpoint(redis_host, int(os.getenv("REDIS_PORT", "6379"))),
        # 不主动调用 LLM，避免 readiness 检查产生计费请求。
        "llm": configured(os.getenv("DEEPSEEK_API_KEY") or os.getenv("SILICONFLOW_API_KEY")),
    })
    statuses = checks.statuses()
    ready = all(value == "ok" for value in statuses.values())
    payload = {"status": "ready" if ready else "unavailable",
               "checks": statuses,
               "chat_initialized": singleton._service is not None}
    if not ready:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
