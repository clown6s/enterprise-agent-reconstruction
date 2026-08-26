"""Pure deterministic policies for ingestion."""
import hashlib
import os
import re

DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalized_filename(filename: str | None) -> str:
    return os.path.basename((filename or "未命名").strip()) or "未命名"


def normalized_extension(filename: str | None) -> str:
    name = normalized_filename(filename).lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def document_title(title: str | None, filename: str | None) -> str:
    return (title or normalized_filename(filename)).strip() or "未命名文档"


def validate_size(size: int, maximum: int = DEFAULT_MAX_FILE_BYTES) -> None:
    if size < 0:
        raise ValueError("文件大小不能为负数")
    if size > maximum:
        raise ValueError(f"文件超过 {maximum // (1024 * 1024)}MB 上限，请拆分后上传。")


def archive_extension(filename: str | None) -> str:
    ext = normalized_extension(filename)
    return ext if re.fullmatch(r"[a-z0-9]{1,8}", ext or "") else "bin"
