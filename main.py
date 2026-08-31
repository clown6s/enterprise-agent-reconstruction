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

setup_logging()
logger = structlog.get_logger(__name__)

app = FastAPI()
register_exception_handlers(app)


def _chat_service():
    ingestion = build_ingestion()
    retriever = RetrieveDocuments(
        ingestion.embedder, ingestion.vectors,
        lexical=ingestion.lexical, reranker=build_reranker(),
    )
    return build_chat(retriever=retriever)


app.include_router(create_router(_chat_service))


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
