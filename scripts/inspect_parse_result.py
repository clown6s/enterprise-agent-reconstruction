"""单独查看文档解析结果，只读取文件，不调用外部服务。"""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.docx import DocxParser
from app.ingestion.bootstrap.container import build_parser


DOCUMENT_PATH = r"D:\datum\内科学.pdf"
# DOCUMENT_PATH = r"D:\datum\家庭教育促进法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人工共和国刑法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人民共和国治安管理处罚法_20250627.docx"
# DOCUMENT_PATH = r"D:\datum\导游面试问答.docx"
# DOCUMENT_PATH = r"D:\datum\AI-Agents-in-Depth-zh-CN.pdf"
# DOCUMENT_PATH = r"D:\datum\古代诗歌常用意象.txt"


def main() -> int:
    if not DOCUMENT_PATH.strip():
        print("请先在 DOCUMENT_PATH = r\"\" 中填入文件路径")
        return 2
    path = Path(DOCUMENT_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1
    parser = build_parser()
    result = parser.parse(DocumentSource(path.name, path.read_bytes()))
    print(f"文件: {path}")
    print(f"解析器: {result.parser}")
    print(f"诊断: {result.diagnostics}")
    print(f"Block 类型: {dict(Counter(block.kind for block in result.layout_blocks))}")
    print(f"Block 数量: {len(result.layout_blocks)}")
    print("=" * 80)
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
