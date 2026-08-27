"""单独查看文档切分结果，只读取文件，不调用外部服务。"""
from pathlib import Path
import sys
from collections import Counter
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.domain.models import DocumentSource
from app.ingestion.bootstrap.container import build_parser, build_chunkers
from app.ingestion.processing.profiles import default_profiles


# DOCUMENT_PATH = r"D:\datum\内科学.pdf"
# DOCUMENT_PATH = r"D:\datum\家庭教育促进法.pdf"
DOCUMENT_PATH = r"D:\datum\中华人工共和国刑法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人民共和国治安管理处罚法_20250627.docx"
# DOCUMENT_PATH = r"D:\datum\导游面试问答.docx"
# DOCUMENT_PATH = r"D:\datum\AI-Agents-in-Depth-zh-CN.pdf"
# DOCUMENT_PATH = r"D:\datum\古代诗歌常用意象.txt"



def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1:
        global DOCUMENT_PATH
        DOCUMENT_PATH = sys.argv[1]
    if not DOCUMENT_PATH.strip():
        print("请先在 DOCUMENT_PATH = r\"\" 中填入文件路径")
        return 2
    path = Path(DOCUMENT_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1
    source = DocumentSource(path.name, path.read_bytes())
    parsed = build_parser().parse(source)
    classification = default_profiles().classify(parsed)
    parsed = replace(parsed, profile=classification.kind)
    chunks = build_chunkers().chunk(classification.kind, parsed, source)
    print(f"文件: {path}")
    print(f"解析器: {parsed.parser}")
    print(f"分类: {classification.kind} (confidence={classification.confidence:.3f})")
    print(f"Chunk 数量: {len(chunks)}")
    print(f"类型统计: {dict(Counter(chunk.kind for chunk in chunks))}")
    print(f"空文本: {sum(not chunk.text.strip() for chunk in chunks)}; 超长: {sum(len(chunk.text) > 600 for chunk in chunks)}")
    print("=" * 80)
    for index, chunk in enumerate(chunks, 1):
        print(f"[{index}] kind={chunk.kind} article={chunk.metadata.get('article')} "
              f"question={chunk.metadata.get('question_number')} page={chunk.page} "
              f"section={' > '.join(chunk.section_path)} continuation={chunk.continuation}")
        print(chunk.text)
        print("-" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
