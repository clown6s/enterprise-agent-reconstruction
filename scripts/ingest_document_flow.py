"""端到端文档入库测试：解析 -> 分类 -> 切分 -> Embedding -> Milvus 入库。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.bootstrap.logging import setup_logging
from app.ingestion.domain.models import DocumentSource

import structlog

logger = structlog.get_logger(__name__)

# DOCUMENT_PATH = r"D:\datum\内科学.pdf"
# DOCUMENT_PATH = r"D:\datum\家庭教育促进法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人工共和国刑法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人民共和国治安管理处罚法_20250627.docx"
# DOCUMENT_PATH = r"D:\datum\导游面试问答.docx"
DOCUMENT_PATH = r"D:\datum\AI-Agents-in-Depth-zh-CN.pdf"
# DOCUMENT_PATH = r"D:\datum\古代诗歌常用意象.txt"



def main(argv: list[str]) -> int:
    setup_logging()
    path = Path(DOCUMENT_PATH.strip())
    if not path.is_file():
        logger.error("文件不存在", path=str(path))
        return 1

    source = DocumentSource(path.name, path.read_bytes())
    logger.info("ingest_start", file=path.name, size=source.size)

    # 真实读取 .env 中的配置，SiliconFlow + Milvus 都启用。
    service = build_ingestion()
    logger.info("ingest_components",
                embedder=type(service.embedder).__name__,
                vectors=type(service.vectors).__name__)

    try:
        result = service.execute(source)
    except Exception as exc:  # 让 adapter 和外部的真实异常都暴露出来
        logger.exception("ingest_failed", error=f"{type(exc).__name__}: {exc}")
        return 1

    logger.info("ingest_done",
                status=result.status.value,
                chunks=result.chunks,
                document_id=result.document_id,
                diagnostics=result.diagnostics)
    if result.message:
        logger.info("ingest_message", message=result.message)
    if result.warnings:
        logger.warning("ingest_warnings", warnings=list(result.warnings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))