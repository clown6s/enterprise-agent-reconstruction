"""盘点 PDF 页面资源，不调用 OCR、不写入索引。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.processing.parsers.pdf_image import PdfImageExtractor

# 只改这一行，填入要测试的 PDF 文件完整路径。
PDF_PATH = r"D:\datum\AI-Agents-in-Depth-zh-CN.pdf"


def main() -> int:
    path = Path(PDF_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1
    pages = PdfImageExtractor().extract(path.read_bytes())
    print(f"文件: {path}")
    print(f"提取到的内嵌位图数量: {sum(len(images) for images in pages.values())}")
    print(f"涉及页数: {len(pages)}")
    for page, images in sorted(pages.items()):
        print(f"第 {page} 页: {len(images)} 张，大小=" + ", ".join(f"{len(image)} 字节" for image in images))
    print("说明：矢量图、文字和页面绘图对象不会被 page.images 统计。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
