"""单独查看文档切分结果，只读取文件，不调用外部服务。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.chunker_registry import ChunkerRegistry
from app.ingestion.processing.parsers.docx import DocxParser
from app.ingestion.processing.parsers.pdf import PdfParser
from app.ingestion.processing.profiles import default_profiles
from app.ingestion.processing.chunkers.qa import QaChunker
from app.ingestion.processing.chunkers.legal import LegalChunker
from app.ingestion.processing.chunkers.generic import GenericChunker
from app.ingestion.processing.chunkers.technical import TechnicalChunker
from app.ingestion.processing.chunkers.medical import MedicalChunker
from app.ingestion.processing.parsers.csv import CsvParser
from app.ingestion.processing.parsers.registry import ParserRegistry
from app.ingestion.processing.parsers.text import TextParser


# 只改这一行，填入要测试的文档完整路径。
DOCUMENT_PATH = r"D:\datum\AI-Agents-in-Depth-zh-CN.pdf"


def main() -> int:
    if not DOCUMENT_PATH.strip():
        print("请先在 DOCUMENT_PATH = r\"\" 中填入文件路径")
        return 2
    path = Path(DOCUMENT_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1
    source = DocumentSource(path.name, path.read_bytes())
    parsed = ParserRegistry([TextParser(), CsvParser(), DocxParser(), PdfParser()]).parse(source)
    classification = default_profiles().classify(parsed)
    chunkers = ChunkerRegistry({"qa": QaChunker(), "legal": LegalChunker(), "technical_book": TechnicalChunker(), "medical_book": MedicalChunker(), "generic": GenericChunker()})
    chunks = chunkers.chunk(classification.kind, parsed, source)
    print(f"文件: {path}")
    print(f"解析器: {parsed.parser}")
    print(f"分类: {classification.kind} (confidence={classification.confidence:.3f})")
    print(f"Chunk 数量: {len(chunks)}")
    print("=" * 80)
    for index, chunk in enumerate(chunks, 1):
        print(f"[{index}] kind={chunk.kind} article={chunk.metadata.get('article')} "
              f"question={chunk.metadata.get('question_number')} page={chunk.page} "
              f"continuation={chunk.continuation}")
        print(chunk.text)
        print("-" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
